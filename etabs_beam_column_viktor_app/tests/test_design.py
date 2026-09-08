from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

try:
    from ._viktor_stub import install
except ImportError:  # pragma: no cover - supports direct discovery execution
    from _viktor_stub import install

install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402
from interaction_diagrams import column_interaction_figure  # noqa: E402
from models import DesignInputError, DesignSettings  # noqa: E402
from project_design import design_project  # noqa: E402


class DesignEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = DesignSettings()
        self.beam_members = copy.deepcopy(app.DEFAULT_BEAM_MEMBERS)
        self.beam_forces = copy.deepcopy(app.DEFAULT_BEAM_FORCES)
        self.column_members = copy.deepcopy(app.DEFAULT_COLUMN_MEMBERS)
        self.column_forces = copy.deepcopy(app.DEFAULT_COLUMN_FORCES)

    def design(self):
        return design_project(
            self.beam_members,
            self.beam_forces,
            self.column_members,
            self.column_forces,
            self.settings,
        )

    def test_default_project_produces_beam_column_and_two_interaction_diagrams(self) -> None:
        project = self.design()

        self.assertEqual(len(project.beams), 1)
        self.assertEqual(len(project.columns), 1)

        beam = project.beams[0]
        self.assertGreater(beam.top_left.area_mm2, 0.0)
        self.assertGreater(beam.bottom_mid.area_mm2, 0.0)
        self.assertGreater(beam.stirrup_left.shear_capacity_kn, 0.0)
        self.assertIn(beam.status, {"OK", "WARNING", "FAIL"})

        column = project.columns[0]
        self.assertGreaterEqual(column.layout.count, 4)
        self.assertGreater(len(column.interaction_m2), 20)
        self.assertGreater(len(column.interaction_m3), 20)
        self.assertGreater(column.shear_capacity_kn, 0.0)
        self.assertTrue(column.demand_checks)

        figure = column_interaction_figure(column)
        self.assertEqual(len(figure["data"]), 8)
        trace_names = {trace["name"] for trace in figure["data"]}
        self.assertTrue(any("M2" in str(name) for name in trace_names))
        self.assertTrue(any("M3" in str(name) for name in trace_names))

    def test_non_square_column_has_stronger_m3_capacity_for_deeper_m3_section(self) -> None:
        self.column_members[0]["width_mm"] = 300.0
        self.column_members[0]["depth_mm"] = 600.0
        self.column_members[0]["section_name"] = "C300x600"

        column = self.design().columns[0]
        max_m2 = max(abs(point.moment_knm) for point in column.interaction_m2)
        max_m3 = max(abs(point.moment_knm) for point in column.interaction_m3)

        self.assertGreater(max_m3, max_m2 * 1.25)

    def test_extreme_column_shear_returns_failed_design(self) -> None:
        for force in self.column_forces:
            force["v2_kn"] = 10_000.0
            force["v3_kn"] = 8_000.0

        column = self.design().columns[0]
        self.assertGreater(column.maximum_shear_utilization, 1.0)
        self.assertEqual(column.status, "FAIL")
        self.assertTrue(any("shear" in warning.lower() for warning in column.warnings))

    def test_invalid_beam_station_is_rejected(self) -> None:
        self.beam_forces[0]["station_m"] = 20.0
        with self.assertRaisesRegex(DesignInputError, "outside the member length"):
            self.design()

    def test_force_for_unknown_member_is_rejected(self) -> None:
        self.beam_forces[0]["member_id"] = "DOES-NOT-EXIST"
        with self.assertRaisesRegex(DesignInputError, "not in the beam-member table"):
            self.design()

    def test_circular_column_generates_both_curves(self) -> None:
        self.column_members[0].update(
            {
                "shape": "Circular",
                "diameter_mm": 600.0,
                "width_mm": 600.0,
                "depth_mm": 600.0,
                "section_name": "CIRC600",
            }
        )
        column = self.design().columns[0]
        self.assertEqual(column.member.shape, "Circular")
        self.assertGreater(len(column.interaction_m2), 20)
        self.assertGreater(len(column.interaction_m3), 20)
        self.assertGreater(column.layout.count, 4)


if __name__ == "__main__":
    unittest.main()

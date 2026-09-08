from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from ._viktor_stub import install
except ImportError:  # pragma: no cover
    from _viktor_stub import install

vkt = install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etabs_reader import ETABSImportSettings, ETABSReadError, read_attached_etabs_model  # noqa: E402


class FakeSetup:
    def __init__(self) -> None:
        self.deselect_calls = 0
        self.selected: list[tuple[str, bool]] = []

    def DeselectAllCasesAndCombosForOutput(self):
        self.deselect_calls += 1
        return 0

    def SetComboSelectedForOutput(self, name, selected):
        self.selected.append((str(name), bool(selected)))
        return 0


class FakeResults:
    def __init__(self, setup: FakeSetup, fail_group: bool = False) -> None:
        self.Setup = setup
        self.fail_group = fail_group
        self.frame_force_calls: list[tuple[str, int]] = []

    @staticmethod
    def _all_rows():
        rows = []
        beam_stations = [0.0, 1.5, 3.0, 4.5, 6.0]
        beam_m3 = [-185.0, -70.0, 135.0, -62.0, -172.0]
        beam_v2 = [145.0, 78.0, 28.0, -72.0, -138.0]
        for station, moment, shear in zip(beam_stations, beam_m3, beam_v2):
            rows.append(("B1", station, "B1-E", station, "ULS-1", "", 0.0, -10.0, shear, 0.0, 5.0, 0.0, moment))
        rows.extend(
            [
                ("B1", 3.0, "B1-E", 3.0, "SLS-1", "", 0.0, -6.0, 18.0, 0.0, 1.0, 0.0, 80.0),
                ("C1", 0.0, "C1-E", 0.0, "ULS-1", "", 0.0, -1800.0, 95.0, 82.0, 4.0, 140.0, 120.0),
                ("C1", 3.2, "C1-E", 3.2, "ULS-1", "", 0.0, -1620.0, 80.0, 68.0, 3.0, 118.0, 104.0),
                ("C1", 1.6, "C1-E", 1.6, "SLS-1", "", 0.0, -1100.0, 30.0, 25.0, 1.0, 55.0, 45.0),
            ]
        )
        return rows

    def FrameForce(self, name, item_type, *_args):
        self.frame_force_calls.append((str(name), int(item_type)))
        if self.fail_group and int(item_type) == vkt.etabs.eItemTypeElm.GroupElm:
            raise vkt.errors.ExecutionError("group unavailable")
        rows = self._all_rows()
        if int(item_type) == vkt.etabs.eItemTypeElm.ObjectElm:
            rows = [row for row in rows if row[0] == name]
        arrays = list(zip(*rows)) if rows else [tuple() for _ in range(13)]
        return [len(rows), *[list(values) for values in arrays], 0]


class FakeFrameObj:
    def GetLabelNameList(self, *_args):
        return [2, ["B1", "C1"], ["B-1", "C-1"], ["Story 1", "Story 1"], 0]

    def GetAllFrames(self, *_args):
        number = 2
        names = ["B1", "C1"]
        sections = ["B300x600", "C500x500"]
        stories = ["Story 1", "Story 1"]
        point_i = ["P1", "P3"]
        point_j = ["P2", "P4"]
        xi = [0.0, 0.0]
        yi = [0.0, 0.0]
        zi = [3.2, 0.0]
        xj = [6.0, 0.0]
        yj = [0.0, 0.0]
        zj = [3.2, 3.2]
        angle = [0.0, 0.0]
        # GetAllFrames returns additional cardinal/insertion arrays after the angle.
        remaining = [[0, 0] for _ in range(7)]
        return [
            number,
            names,
            sections,
            stories,
            point_i,
            point_j,
            xi,
            yi,
            zi,
            xj,
            yj,
            zj,
            angle,
            *remaining,
            0,
        ]


class FakePropFrame:
    def GetRectangle(self, name, *_args):
        if name == "B300x600":
            return [name, "C28", 0.6, 0.3, 0, "", "", 0]
        if name == "C500x500":
            return [name, "C28", 0.5, 0.5, 0, "", "", 0]
        return [name, "", 0.0, 0.0, 0, "", "", 1]

    def GetCircle(self, name, *_args):
        return [name, "", 0.0, 0, "", "", 1]


class FakePropMaterial:
    def GetTypeOAPI(self, *_args):
        return [2, 0, 0]


class FakeRespCombo:
    def GetNameList(self, *_args):
        return [2, ["ULS-1", "SLS-1"], 0]


class FakeSap:
    def __init__(self, *, fail_group: bool = False) -> None:
        self.units_calls: list[int] = []
        self.Setup = FakeSetup()
        self.Results = FakeResults(self.Setup, fail_group=fail_group)
        self.RespCombo = FakeRespCombo()
        self.FrameObj = FakeFrameObj()
        self.PropFrame = FakePropFrame()
        self.PropMaterial = FakePropMaterial()

    def GetPresentUnits(self):
        return 9

    def SetPresentUnits(self, units):
        self.units_calls.append(int(units))
        return 0


class ETABSReaderTests(unittest.TestCase):
    def test_reads_geometry_and_strength_results_and_restores_etabs_state(self) -> None:
        sap = FakeSap()
        result = read_attached_etabs_model(
            sap,
            ETABSImportSettings(
                combination_filter="ULS*",
                maximum_beam_rows_per_combination=5,
            ),
        )

        self.assertEqual(result.selected_combinations, ("ULS-1",))
        self.assertEqual(len(result.beam_members), 1)
        self.assertEqual(len(result.column_members), 1)
        self.assertEqual(len(result.beam_forces), 5)
        self.assertEqual(len(result.column_forces), 2)
        self.assertEqual(result.beam_members[0]["width_mm"], 300.0)
        self.assertEqual(result.beam_members[0]["depth_mm"], 600.0)
        self.assertEqual(result.column_forces[0]["p_kn"], 1800.0)
        self.assertEqual(result.beam_forces[0]["p_kn"], -10.0)

        self.assertEqual(sap.units_calls, [vkt.etabs.eUnits.kN_m_C, 9])
        self.assertEqual(sap.Setup.deselect_calls, 2)
        self.assertEqual(sap.Setup.selected, [("ULS-1", True)])

    def test_falls_back_to_object_force_queries_when_group_query_fails(self) -> None:
        sap = FakeSap(fail_group=True)
        result = read_attached_etabs_model(
            sap,
            ETABSImportSettings(combination_filter="ULS*"),
        )
        self.assertEqual(len(result.beam_forces), 5)
        self.assertEqual(len(result.column_forces), 2)
        self.assertIn(("B1", vkt.etabs.eItemTypeElm.ObjectElm), sap.Results.frame_force_calls)
        self.assertIn(("C1", vkt.etabs.eItemTypeElm.ObjectElm), sap.Results.frame_force_calls)

    def test_no_matching_response_combination_is_reported(self) -> None:
        sap = FakeSap()
        with self.assertRaisesRegex(ETABSReadError, "No response combinations match"):
            read_attached_etabs_model(
                sap,
                ETABSImportSettings(combination_filter="NOT-THERE*"),
            )
        self.assertEqual(sap.units_calls, [vkt.etabs.eUnits.kN_m_C, 9])
        self.assertEqual(sap.Setup.deselect_calls, 0)


if __name__ == "__main__":
    unittest.main()

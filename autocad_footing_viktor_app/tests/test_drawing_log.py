import unittest

from drawing_log import DrawingRunSummary, build_drawing_log
from foundation_design import DesignSettings, design_project

from test_foundation_design import NODES, REACTIONS


class DrawingLogTests(unittest.TestCase):
    def test_log_describes_the_created_drawing_items(self):
        project = design_project(
            NODES,
            REACTIONS,
            DesignSettings(
                allowable_bearing_pressure_kpa=200.0,
                minimum_reinforcement_ratio=0.0018,
                concrete_strength_mpa=28.0,
                steel_yield_strength_mpa=420.0,
                cover_mm=75.0,
                preferred_bar_diameter_mm=16,
            ),
        )
        run = DrawingRunSummary(
            document_name="foundation-plan.dwg",
            entities_created=42,
            layers_ready=("VKT-FDN-GRID", "VKT-FDN-FOOTING"),
            layers_created=("VKT-FDN-GRID",),
            x_grid_count=2,
            y_grid_count=1,
        )

        log = build_drawing_log(project, run)

        self.assertIn("Drawing: foundation-plan.dwg", log)
        self.assertIn("Model-space entities created: 42", log)
        self.assertIn("VKT-FDN-GRID (created)", log)
        self.assertIn("VKT-FDN-FOOTING (already existed)", log)
        self.assertIn("Footing outlines drawn: 2", log)
        self.assertIn("N1 (", log)
        self.assertIn("The drawing remains open in AutoCAD", log)


if __name__ == "__main__":
    unittest.main()

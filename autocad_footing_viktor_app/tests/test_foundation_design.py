import unittest

from foundation_design import DesignInputError, DesignSettings, design_project


NODES = [
    {"node_id": "N1", "x_m": 0.0, "y_m": 0.0, "z_m": 0.0, "column_x_mm": 400, "column_y_mm": 400},
    {"node_id": "N2", "x_m": 5.0, "y_m": 0.0, "z_m": 0.0, "column_x_mm": 400, "column_y_mm": 400},
]

REACTIONS = [
    {"node_id": "N1", "combination": "S1", "limit_state": "Service", "p_kn": 600, "mx_knm": 20, "my_knm": 15},
    {"node_id": "N1", "combination": "U1", "limit_state": "Ultimate", "p_kn": 870, "mx_knm": 30, "my_knm": 22},
    {"node_id": "N2", "combination": "S1", "limit_state": "Service", "p_kn": 800, "mx_knm": 30, "my_knm": 25},
    {"node_id": "N2", "combination": "U1", "limit_state": "Ultimate", "p_kn": 1160, "mx_knm": 45, "my_knm": 38},
]

SETTINGS = DesignSettings(
    allowable_bearing_pressure_kpa=200.0,
    minimum_reinforcement_ratio=0.0018,
    concrete_strength_mpa=28.0,
    steel_yield_strength_mpa=420.0,
    cover_mm=75.0,
    preferred_bar_diameter_mm=16,
)


class FoundationDesignTests(unittest.TestCase):
    def test_designs_all_nodes(self):
        project = design_project(NODES, REACTIONS, SETTINGS)
        self.assertEqual(len(project.footings), 2)
        self.assertTrue(project.footing_types)
        for footing in project.footings:
            self.assertLessEqual(footing.bearing_utilization, 1.0 + 1e-7)
            self.assertGreaterEqual(footing.q_service_min_kpa, -1e-7)
            self.assertLessEqual(footing.punching_utilization, 1.0 + 1e-7)
            self.assertLessEqual(footing.one_way_shear_x_utilization, 1.0 + 1e-7)
            self.assertLessEqual(footing.one_way_shear_y_utilization, 1.0 + 1e-7)

    def test_minimum_reinforcement_is_met(self):
        project = design_project(NODES[:1], REACTIONS[:2], SETTINGS)
        footing = project.footings[0]
        minimum = SETTINGS.minimum_reinforcement_ratio * 1000 * footing.thickness_mm
        self.assertGreaterEqual(footing.steel_x_mm2_per_m + 1e-7, minimum)
        self.assertGreaterEqual(footing.steel_y_mm2_per_m + 1e-7, minimum)

    def test_missing_ultimate_row_fails(self):
        with self.assertRaises(DesignInputError):
            design_project(NODES[:1], REACTIONS[:1], SETTINGS)

    def test_unknown_reaction_node_fails(self):
        bad = [dict(REACTIONS[0], node_id="MISSING"), REACTIONS[1]]
        with self.assertRaises(DesignInputError):
            design_project(NODES[:1], bad, SETTINGS)

    def test_overlapping_footings_fail(self):
        close_nodes = [
            NODES[0],
            dict(NODES[1], x_m=1.0),
        ]
        with self.assertRaises(DesignInputError):
            design_project(close_nodes, REACTIONS, SETTINGS)

    def test_multiple_foundation_levels_fail(self):
        stepped_nodes = [
            NODES[0],
            dict(NODES[1], z_m=-0.5),
        ]
        with self.assertRaises(DesignInputError):
            design_project(stepped_nodes, REACTIONS, SETTINGS)


if __name__ == "__main__":
    unittest.main()

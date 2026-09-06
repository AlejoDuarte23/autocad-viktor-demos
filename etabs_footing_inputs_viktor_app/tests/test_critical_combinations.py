import unittest

from critical_combinations import CriticalCombinationError, select_critical_reactions


def reaction(node, case, fz, mx, my, x=0.0, y=0.0, z=0.0):
    return {
        "Story": "Base",
        "Label": node,
        "UniqueName": node,
        "OutputCase": case,
        "CaseType": "Combination",
        "StepType": "",
        "FX": 0.0,
        "FY": 0.0,
        "FZ": fz,
        "MX": mx,
        "MY": my,
        "MZ": 0.0,
        "X": x,
        "Y": y,
        "Z": z,
    }


ROWS = [
    reaction("1", "SVC-A", -500.0, 10.0, 20.0, x=1.5, y=2.5, z=-0.2),
    reaction("1", "SVC-B", -650.0, 8.0, 15.0, x=1.5, y=2.5, z=-0.2),
    reaction("1", "ULS-A", -850.0, 25.0, 30.0, x=1.5, y=2.5, z=-0.2),
    reaction("1", "ULS-B", -850.0, 35.0, 40.0, x=1.5, y=2.5, z=-0.2),
]


class CriticalCombinationTests(unittest.TestCase):
    def test_selects_maximum_compression_and_exposes_coordinates(self):
        selected = select_critical_reactions(ROWS, "SVC", "ULS")

        self.assertEqual([row["combination"] for row in selected], ["SVC-B", "ULS-B"])
        self.assertEqual(selected[0]["p_kn"], 650.0)
        self.assertEqual((selected[0]["x_m"], selected[0]["y_m"], selected[0]["z_m"]), (1.5, 2.5, -0.2))

    def test_supports_positive_compression_sign(self):
        rows = [
            reaction("1", "SVC-A", 500.0, 10.0, 20.0),
            reaction("1", "ULS-A", 800.0, 20.0, 30.0),
        ]
        selected = select_critical_reactions(
            rows, "SVC", "ULS", compression_is_negative=False
        )
        self.assertEqual([row["p_kn"] for row in selected], [500.0, 800.0])

    def test_rejects_overlapping_case_filters(self):
        with self.assertRaises(CriticalCombinationError):
            select_critical_reactions(ROWS, "SVC, ULS", "ULS")

    def test_requires_both_limit_states(self):
        with self.assertRaises(CriticalCombinationError):
            select_critical_reactions(ROWS[:2], "SVC", "ULS")


if __name__ == "__main__":
    unittest.main()

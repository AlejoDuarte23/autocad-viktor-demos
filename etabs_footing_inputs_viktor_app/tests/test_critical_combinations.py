import unittest

from critical_combinations import (
    SERVICE,
    ULTIMATE,
    CriticalCombinationError,
    compression_is_negative,
    infer_limit_state,
    select_critical_reactions,
)


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
    def test_selects_defined_combinations_and_exposes_coordinates(self):
        selected = select_critical_reactions(
            ROWS,
            {
                "SVC-A": (1.0,),
                "SVC-B": (1.0, 0.5),
                "ULS-A": (1.2, 1.5),
                "ULS-B": (1.35, 1.5),
            },
        )

        self.assertEqual([row["combination"] for row in selected], ["SVC-B", "ULS-B"])
        self.assertEqual(selected[0]["p_kn"], 650.0)
        self.assertEqual((selected[0]["x_m"], selected[0]["y_m"], selected[0]["z_m"]), (1.5, 2.5, -0.2))

    def test_detects_positive_compression_from_dead_load(self):
        rows = [
            reaction("1", "Dead", 400.0, 0.0, 0.0),
            reaction("1", "G+Q", 500.0, 10.0, 20.0),
            reaction("1", "1.2G + 1.5Q", 800.0, 20.0, 30.0),
        ]
        selected = select_critical_reactions(rows, {"G+Q": (1.0, 1.0), "1.2G + 1.5Q": (1.2, 1.5)})
        self.assertEqual([row["p_kn"] for row in selected], [500.0, 800.0])
        self.assertFalse(compression_is_negative(rows))

    def test_infers_limit_state_from_combination_factors(self):
        self.assertEqual(infer_limit_state((1.0, 0.3)), SERVICE)
        self.assertEqual(infer_limit_state((1.2, 1.5)), ULTIMATE)

    def test_requires_both_limit_states(self):
        with self.assertRaises(CriticalCombinationError):
            select_critical_reactions(ROWS[:2], {"SVC-A": (1.0,), "SVC-B": (1.0,)})

    def test_ignores_individual_load_cases(self):
        rows = ROWS + [reaction("1", "Dead", -9999.0, 0.0, 0.0)]
        selected = select_critical_reactions(
            rows,
            {"SVC-A": (1.0,), "SVC-B": (1.0,), "ULS-A": (1.2,), "ULS-B": (1.5,)},
        )
        self.assertNotIn("Dead", [row["combination"] for row in selected])


if __name__ == "__main__":
    unittest.main()

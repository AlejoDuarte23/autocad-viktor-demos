from __future__ import annotations

import copy
import inspect
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from ._viktor_stub import install
except ImportError:  # pragma: no cover
    from _viktor_stub import install

vkt = install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402
from etabs_reader import ETABSImportResult  # noqa: E402


def make_params() -> SimpleNamespace:
    return SimpleNamespace(
        combination_filter="ULS*",
        story_filter="*",
        beam_filter="*",
        column_filter="*",
        result_group_name="ALL",
        compression_is_negative=True,
        column_vertical_ratio=0.75,
        maximum_members=250,
        maximum_beam_rows_per_combination=21,
        import_summary="sample",
        beam_members=copy.deepcopy(app.DEFAULT_BEAM_MEMBERS),
        beam_forces=copy.deepcopy(app.DEFAULT_BEAM_FORCES),
        column_members=copy.deepcopy(app.DEFAULT_COLUMN_MEMBERS),
        column_forces=copy.deepcopy(app.DEFAULT_COLUMN_FORCES),
        concrete_strength=28.0,
        steel_yield_strength=420.0,
        steel_modulus=200000.0,
        concrete_cover=40.0,
        preferred_beam_bar=20,
        preferred_column_bar=20,
        preferred_stirrup=10,
        minimum_beam_bars=2,
        shear_phi=0.75,
        development_length_factor=40.0,
        minimum_column_ratio=0.01,
        maximum_column_ratio=0.06,
        column_biaxial_exponent=1.0,
        effective_length_factor=1.0,
        assume_etabs_pdelta=True,
        design_torsion=True,
        slenderness_warning_limit=22.0,
        selected_column="C1-ETABS",
        autocad_units_per_metre=1000.0,
        autocad_origin_x=0.0,
        autocad_origin_y=0.0,
        autocad_layer_prefix="VKT-RC",
        autocad_text_height=0.16,
        details_per_row=2,
        maximum_beams_to_draw=40,
        maximum_columns_to_draw=40,
        maximum_stirrup_symbols=100,
        draw_schedules=True,
        draw_border=True,
    )


class AppTests(unittest.TestCase):
    def test_parametrization_is_flat_and_has_required_controls(self) -> None:
        source = inspect.getsource(app.Parametrization)
        self.assertNotIn("vkt.Section", source)
        self.assertNotIn("vkt.Step", source)
        self.assertNotIn("vkt.Page", source)
        self.assertIsInstance(app.Parametrization.intro, vkt.Text)
        self.assertIsInstance(app.Parametrization.beam_members, vkt.Table)
        self.assertIsInstance(app.Parametrization.column_members, vkt.Table)
        self.assertIsInstance(app.Parametrization.read_etabs, vkt.SetParamsButton)
        self.assertIsInstance(app.Parametrization.calculate_and_draw, vkt.ActionButton)

    def test_table_views_have_consistent_rows_and_headers(self) -> None:
        controller = app.Controller()
        params = make_params()

        beam_result = controller.beam_design_summary(params)
        column_result = controller.column_design_summary(params)

        self.assertEqual(len(beam_result.data), 1)
        self.assertEqual(len(column_result.data), 1)
        self.assertEqual(len(beam_result.data[0]), len(beam_result.column_headers))
        self.assertEqual(len(column_result.data[0]), len(column_result.column_headers))
        self.assertFalse(beam_result.show_index)
        self.assertFalse(column_result.show_index)

    def test_interaction_view_contains_two_diagrams(self) -> None:
        result = app.Controller().column_interaction_diagrams(make_params())
        self.assertEqual(len(result.figure["data"]), 8)
        self.assertEqual(len(result.figure["layout"]["annotations"]), 2)

    def test_etabs_set_params_action_populates_all_imported_tables(self) -> None:
        params = make_params()
        imported = ETABSImportResult(
            beam_members=tuple(copy.deepcopy(app.DEFAULT_BEAM_MEMBERS)),
            beam_forces=tuple(copy.deepcopy(app.DEFAULT_BEAM_FORCES)),
            column_members=tuple(copy.deepcopy(app.DEFAULT_COLUMN_MEMBERS)),
            column_forces=tuple(copy.deepcopy(app.DEFAULT_COLUMN_FORCES)),
            selected_combinations=("ULS-1", "ULS-2"),
            notes=("test note",),
        )

        @contextmanager
        def fake_attach(*_args, **_kwargs):
            yield object()

        with patch.object(app.vkt.etabs, "attach", fake_attach), patch.object(
            app, "read_attached_etabs_model", return_value=imported
        ):
            result = app.Controller().read_from_etabs(params)

        self.assertEqual(result.params["selected_column"], "C1-ETABS")
        self.assertEqual(len(result.params["beam_members"]), 1)
        self.assertEqual(len(result.params["beam_forces"]), 5)
        self.assertIn("Imported 1 beams", result.params["import_summary"])
        self.assertIn("ULS-2", result.params["import_summary"])

    def test_autocad_action_calculates_and_calls_drawing_function(self) -> None:
        params = make_params()
        fake_acad = object()
        calls = []

        @contextmanager
        def fake_attach(*_args, **_kwargs):
            yield fake_acad

        def fake_draw(acad, project, settings):
            calls.append((acad, project, settings))

        with patch.object(app.vkt.autocad, "attach", fake_attach), patch.object(
            app, "draw_beam_and_column_details", side_effect=fake_draw
        ):
            result = app.Controller().calculate_and_draw_in_autocad(params)

        self.assertIsNone(result)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], fake_acad)
        self.assertEqual(len(calls[0][1].beams), 1)
        self.assertEqual(len(calls[0][1].columns), 1)
        self.assertEqual(calls[0][2].layer_prefix, "VKT-RC")


if __name__ == "__main__":
    unittest.main()

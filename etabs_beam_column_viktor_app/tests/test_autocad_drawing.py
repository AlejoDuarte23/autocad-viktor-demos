from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

try:
    from ._viktor_stub import install
except ImportError:  # pragma: no cover
    from _viktor_stub import install

vkt = install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402
from autocad_common import DrawingSettings  # noqa: E402
from autocad_drawing import draw_beam_and_column_details  # noqa: E402
from models import DesignSettings  # noqa: E402
from project_design import design_project  # noqa: E402


class FakeEntity:
    def __init__(self, entity_type: str, args: tuple) -> None:
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "properties", {})

    def __setattr__(self, name, value):
        if name in {"entity_type", "args", "properties"}:
            object.__setattr__(self, name, value)
        else:
            self.properties[name] = value


class FakeModelSpace:
    def __init__(self) -> None:
        self.entities: list[FakeEntity] = []

    def _add(self, entity_type: str, *args):
        entity = FakeEntity(entity_type, args)
        self.entities.append(entity)
        return entity

    def AddLine(self, *args):
        return self._add("Line", *args)

    def AddLightWeightPolyline(self, *args):
        return self._add("LWPolyline", *args)

    def AddCircle(self, *args):
        return self._add("Circle", *args)

    def AddText(self, *args):
        return self._add("Text", *args)


class FakeLayer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.Color = None


class FakeLayers:
    def __init__(self) -> None:
        self.items: dict[str, FakeLayer] = {}

    def Add(self, name: str):
        if name in self.items:
            raise vkt.errors.ExecutionError("already exists")
        layer = FakeLayer(name)
        self.items[name] = layer
        return layer

    def Item(self, name: str):
        return self.items[name]


class FakeDocument:
    def __init__(self) -> None:
        self.ModelSpace = FakeModelSpace()
        self.Layers = FakeLayers()
        self.regen_calls: list[int] = []

    def Regen(self, regen_type):
        self.regen_calls.append(regen_type)


class FakeAcad:
    def __init__(self) -> None:
        self.ActiveDocument = FakeDocument()


class AutoCADDrawingTests(unittest.TestCase):
    @staticmethod
    def _project():
        return design_project(
            copy.deepcopy(app.DEFAULT_BEAM_MEMBERS),
            copy.deepcopy(app.DEFAULT_BEAM_FORCES),
            copy.deepcopy(app.DEFAULT_COLUMN_MEMBERS),
            copy.deepcopy(app.DEFAULT_COLUMN_FORCES),
            DesignSettings(),
        )

    def test_draws_beam_column_sections_schedules_border_and_regenerates(self) -> None:
        acad = FakeAcad()
        settings = DrawingSettings(
            units_per_metre=1000.0,
            origin_x_m=0.0,
            origin_y_m=0.0,
            layer_prefix="TEST-RC",
            text_height_m=0.16,
            details_per_row=2,
            maximum_beams_to_draw=10,
            maximum_columns_to_draw=10,
            maximum_stirrup_symbols_per_member=25,
            draw_schedules=True,
            draw_border=True,
        )

        draw_beam_and_column_details(acad, self._project(), settings)

        entity_types = {entity.entity_type for entity in acad.ActiveDocument.ModelSpace.entities}
        self.assertTrue({"Line", "LWPolyline", "Circle", "Text"}.issubset(entity_types))
        self.assertGreater(len(acad.ActiveDocument.ModelSpace.entities), 100)
        self.assertEqual(len(acad.ActiveDocument.Layers.items), 8)
        self.assertEqual(len(acad.ActiveDocument.regen_calls), 1)

        texts = [
            str(entity.args[0])
            for entity in acad.ActiveDocument.ModelSpace.entities
            if entity.entity_type == "Text" and entity.args
        ]
        joined = "\n".join(texts)
        self.assertIn("BEAM DETAILS", joined)
        self.assertIn("COLUMN DETAILS", joined)
        self.assertIn("BEAM REINFORCEMENT SCHEDULE", joined)
        self.assertIn("COLUMN REINFORCEMENT SCHEDULE", joined)

        # A second run must reuse the prefixed layers instead of failing on duplicates.
        draw_beam_and_column_details(acad, self._project(), settings)
        self.assertEqual(len(acad.ActiveDocument.Layers.items), 8)
        self.assertEqual(len(acad.ActiveDocument.regen_calls), 2)


if __name__ == "__main__":
    unittest.main()

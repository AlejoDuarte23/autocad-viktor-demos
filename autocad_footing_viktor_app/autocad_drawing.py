from __future__ import annotations

from dataclasses import dataclass
from math import ceil, pi
from typing import Any, Iterable, Sequence

import viktor as vkt
from viktor.external.autocad import AcRegenType

from foundation_design import DesignProject, FootingDesign, FootingTypeSummary


LAYER_COLORS = {
    "GRID": 8,
    "FOOTING": 6,
    "COLUMN": 2,
    "REBAR": 1,
    "TEXT": 7,
    "DIM": 4,
}


@dataclass(frozen=True)
class DrawingSettings:
    units_per_metre: float
    grid_tolerance_m: float = 0.05
    layer_prefix: str = "VKT-FDN"
    text_height_m: float = 0.18


def _point(x_m: float, y_m: float, scale: float) -> list[float]:
    return [float(x_m * scale), float(y_m * scale), 0.0]


def _layer_name(settings: DrawingSettings, suffix: str) -> str:
    return f"{settings.layer_prefix}-{suffix}"


def _ensure_layer(layers: Any, name: str, color: int) -> Any:
    try:
        layer = layers.Add(name)
    except vkt.errors.ExecutionError:
        layer = layers.Item(name)
    layer.Color = color
    return layer


def _add_line(
    container: Any,
    start: tuple[float, float],
    end: tuple[float, float],
    layer: str,
    settings: DrawingSettings,
) -> Any:
    entity = container.AddLine(
        _point(start[0], start[1], settings.units_per_metre),
        _point(end[0], end[1], settings.units_per_metre),
    )
    entity.Layer = layer
    return entity


def _add_polyline(
    container: Any,
    points: Sequence[tuple[float, float]],
    layer: str,
    settings: DrawingSettings,
    *,
    closed: bool = True,
) -> Any:
    coordinates: list[float] = []
    for x_m, y_m in points:
        coordinates.extend([float(x_m * settings.units_per_metre), float(y_m * settings.units_per_metre)])
    entity = container.AddLightWeightPolyline(coordinates)
    entity.Closed = closed
    entity.Layer = layer
    return entity


def _add_rectangle(
    container: Any,
    center_x_m: float,
    center_y_m: float,
    length_x_m: float,
    length_y_m: float,
    layer: str,
    settings: DrawingSettings,
) -> Any:
    half_x = length_x_m / 2.0
    half_y = length_y_m / 2.0
    return _add_polyline(
        container,
        (
            (center_x_m - half_x, center_y_m - half_y),
            (center_x_m + half_x, center_y_m - half_y),
            (center_x_m + half_x, center_y_m + half_y),
            (center_x_m - half_x, center_y_m + half_y),
        ),
        layer,
        settings,
        closed=True,
    )


def _add_circle(
    container: Any,
    center_x_m: float,
    center_y_m: float,
    radius_m: float,
    layer: str,
    settings: DrawingSettings,
) -> Any:
    entity = container.AddCircle(
        _point(center_x_m, center_y_m, settings.units_per_metre),
        float(radius_m * settings.units_per_metre),
    )
    entity.Layer = layer
    return entity


def _text_left_offset(text: str, text_height_m: float) -> float:
    return 0.30 * len(text) * text_height_m


def _add_text(
    container: Any,
    text: str,
    x_m: float,
    y_m: float,
    layer: str,
    settings: DrawingSettings,
    *,
    height_m: float | None = None,
    rotation_rad: float = 0.0,
    center: bool = False,
) -> Any:
    actual_height = height_m if height_m is not None else settings.text_height_m
    insertion_x = x_m - _text_left_offset(text, actual_height) if center else x_m
    insertion_y = y_m - actual_height * 0.35 if center else y_m
    entity = container.AddText(
        text,
        _point(insertion_x, insertion_y, settings.units_per_metre),
        float(actual_height * settings.units_per_metre),
    )
    entity.Layer = layer
    if rotation_rad:
        entity.Rotation = float(rotation_rad)
    return entity


def _cluster_coordinates(values: Iterable[float], tolerance_m: float) -> list[float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return []
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        current_average = sum(clusters[-1]) / len(clusters[-1])
        if abs(value - current_average) <= tolerance_m:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _alphabetic_label(index: int) -> str:
    value = index + 1
    label = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _draw_horizontal_dimension_chain(
    container: Any,
    coordinates_m: Sequence[float],
    reference_y_m: float,
    dimension_y_m: float,
    layer: str,
    settings: DrawingSettings,
) -> None:
    if len(coordinates_m) < 2:
        return
    tick = 0.08
    _add_line(container, (coordinates_m[0], dimension_y_m), (coordinates_m[-1], dimension_y_m), layer, settings)
    for x_m in coordinates_m:
        _add_line(container, (x_m, reference_y_m), (x_m, dimension_y_m + tick), layer, settings)
        _add_line(container, (x_m - tick, dimension_y_m - tick), (x_m + tick, dimension_y_m + tick), layer, settings)
    for x1_m, x2_m in zip(coordinates_m, coordinates_m[1:]):
        text = f"{x2_m - x1_m:.2f}"
        _add_text(
            container,
            text,
            (x1_m + x2_m) / 2.0,
            dimension_y_m + 0.12,
            layer,
            settings,
            height_m=settings.text_height_m * 0.80,
            center=True,
        )


def _draw_vertical_dimension_chain(
    container: Any,
    coordinates_m: Sequence[float],
    reference_x_m: float,
    dimension_x_m: float,
    layer: str,
    settings: DrawingSettings,
) -> None:
    if len(coordinates_m) < 2:
        return
    ordered = sorted(coordinates_m)
    tick = 0.08
    _add_line(container, (dimension_x_m, ordered[0]), (dimension_x_m, ordered[-1]), layer, settings)
    for y_m in ordered:
        _add_line(container, (reference_x_m, y_m), (dimension_x_m + tick, y_m), layer, settings)
        _add_line(container, (dimension_x_m - tick, y_m - tick), (dimension_x_m + tick, y_m + tick), layer, settings)
    for y1_m, y2_m in zip(ordered, ordered[1:]):
        text = f"{y2_m - y1_m:.2f}"
        _add_text(
            container,
            text,
            dimension_x_m - 0.12,
            (y1_m + y2_m) / 2.0,
            layer,
            settings,
            height_m=settings.text_height_m * 0.80,
            rotation_rad=pi / 2.0,
            center=True,
        )


def _plan_extents(project: DesignProject) -> tuple[float, float, float, float]:
    x_min = min(footing.node.x_m - footing.length_x_m / 2.0 for footing in project.footings)
    x_max = max(footing.node.x_m + footing.length_x_m / 2.0 for footing in project.footings)
    y_min = min(footing.node.y_m - footing.length_y_m / 2.0 for footing in project.footings)
    y_max = max(footing.node.y_m + footing.length_y_m / 2.0 for footing in project.footings)
    return x_min, x_max, y_min, y_max


def _draw_grid_and_plan(
    model_space: Any,
    project: DesignProject,
    settings: DrawingSettings,
) -> tuple[float, float, float, float]:
    grid_layer = _layer_name(settings, "GRID")
    footing_layer = _layer_name(settings, "FOOTING")
    column_layer = _layer_name(settings, "COLUMN")
    text_layer = _layer_name(settings, "TEXT")
    dim_layer = _layer_name(settings, "DIM")

    x_min, x_max, y_min, y_max = _plan_extents(project)
    x_grids = _cluster_coordinates((node.x_m for node in project.nodes), settings.grid_tolerance_m)
    y_grids_ascending = _cluster_coordinates((node.y_m for node in project.nodes), settings.grid_tolerance_m)
    y_grids_descending = list(reversed(y_grids_ascending))

    line_margin = 0.45
    bubble_offset = 0.80
    bubble_radius = 0.22

    grid_bottom = y_min - line_margin
    grid_top = y_max + line_margin
    grid_left = x_min - line_margin
    grid_right = x_max + line_margin

    for index, x_m in enumerate(x_grids, start=1):
        _add_line(model_space, (x_m, grid_bottom), (x_m, grid_top), grid_layer, settings)
        _add_circle(model_space, x_m, grid_top + bubble_offset, bubble_radius, grid_layer, settings)
        _add_text(
            model_space,
            str(index),
            x_m,
            grid_top + bubble_offset,
            text_layer,
            settings,
            height_m=settings.text_height_m * 0.85,
            center=True,
        )

    for index, y_m in enumerate(y_grids_descending):
        _add_line(model_space, (grid_left, y_m), (grid_right, y_m), grid_layer, settings)
        _add_circle(model_space, grid_left - bubble_offset, y_m, bubble_radius, grid_layer, settings)
        _add_text(
            model_space,
            _alphabetic_label(index),
            grid_left - bubble_offset,
            y_m,
            text_layer,
            settings,
            height_m=settings.text_height_m * 0.85,
            center=True,
        )

    _draw_horizontal_dimension_chain(
        model_space,
        x_grids,
        grid_top,
        grid_top + bubble_offset + 0.55,
        dim_layer,
        settings,
    )
    _draw_vertical_dimension_chain(
        model_space,
        y_grids_ascending,
        grid_left,
        grid_left - bubble_offset - 0.55,
        dim_layer,
        settings,
    )

    for footing in project.footings:
        x_m = footing.node.x_m
        y_m = footing.node.y_m
        _add_rectangle(
            model_space,
            x_m,
            y_m,
            footing.length_x_m,
            footing.length_y_m,
            footing_layer,
            settings,
        )
        _add_rectangle(
            model_space,
            x_m,
            y_m,
            footing.node.column_x_m,
            footing.node.column_y_m,
            column_layer,
            settings,
        )
        cross = min(0.12, footing.node.column_x_m / 3.0, footing.node.column_y_m / 3.0)
        _add_line(model_space, (x_m - cross, y_m), (x_m + cross, y_m), column_layer, settings)
        _add_line(model_space, (x_m, y_m - cross), (x_m, y_m + cross), column_layer, settings)

        mark_text = f"{footing.footing_type} / {footing.node.node_id}"
        _add_text(
            model_space,
            mark_text,
            x_m,
            y_m + footing.length_y_m / 2.0 - 0.22,
            text_layer,
            settings,
            height_m=settings.text_height_m * 0.78,
            center=True,
        )

    _add_text(
        model_space,
        "FOUNDATION LAYOUT PLAN",
        (x_min + x_max) / 2.0,
        y_min - 1.20,
        text_layer,
        settings,
        height_m=settings.text_height_m * 1.45,
        center=True,
    )
    return x_min, x_max, y_min, y_max


def _bar_positions(clear_start_m: float, clear_end_m: float, spacing_mm: int) -> list[float]:
    clear_length_m = clear_end_m - clear_start_m
    if clear_length_m <= 0:
        return []
    requested_spacing_m = spacing_mm / 1000.0
    interval_count = max(1, int(ceil(clear_length_m / requested_spacing_m)))
    actual_spacing_m = clear_length_m / interval_count
    return [clear_start_m + index * actual_spacing_m for index in range(interval_count + 1)]


def _draw_single_type_detail(
    model_space: Any,
    summary: FootingTypeSummary,
    center_x_m: float,
    center_y_m: float,
    settings: DrawingSettings,
    cover_m: float,
) -> None:
    design = summary.representative
    footing_layer = _layer_name(settings, "FOOTING")
    column_layer = _layer_name(settings, "COLUMN")
    rebar_layer = _layer_name(settings, "REBAR")
    text_layer = _layer_name(settings, "TEXT")
    dim_layer = _layer_name(settings, "DIM")

    _add_rectangle(
        model_space,
        center_x_m,
        center_y_m,
        design.length_x_m,
        design.length_y_m,
        footing_layer,
        settings,
    )
    _add_rectangle(
        model_space,
        center_x_m,
        center_y_m,
        design.node.column_x_m,
        design.node.column_y_m,
        column_layer,
        settings,
    )

    x_start = center_x_m - design.length_x_m / 2.0 + cover_m
    x_end = center_x_m + design.length_x_m / 2.0 - cover_m
    y_start = center_y_m - design.length_y_m / 2.0 + cover_m
    y_end = center_y_m + design.length_y_m / 2.0 - cover_m

    for y_m in _bar_positions(y_start, y_end, design.spacing_x_mm):
        _add_line(model_space, (x_start, y_m), (x_end, y_m), rebar_layer, settings)
    for x_m in _bar_positions(x_start, x_end, design.spacing_y_mm):
        _add_line(model_space, (x_m, y_start), (x_m, y_end), rebar_layer, settings)

    horizontal_dim_y = center_y_m + design.length_y_m / 2.0 + 0.45
    _draw_horizontal_dimension_chain(
        model_space,
        (center_x_m - design.length_x_m / 2.0, center_x_m + design.length_x_m / 2.0),
        center_y_m + design.length_y_m / 2.0,
        horizontal_dim_y,
        dim_layer,
        settings,
    )
    vertical_dim_x = center_x_m + design.length_x_m / 2.0 + 0.45
    _draw_vertical_dimension_chain(
        model_space,
        (center_y_m - design.length_y_m / 2.0, center_y_m + design.length_y_m / 2.0),
        center_x_m + design.length_x_m / 2.0,
        vertical_dim_x,
        dim_layer,
        settings,
    )

    note_x = center_x_m - design.length_x_m / 2.0
    note_y = center_y_m - design.length_y_m / 2.0 - 0.50
    _add_text(
        model_space,
        f"{summary.mark} PLAN {design.length_x_m:.2f} x {design.length_y_m:.2f} m; h={design.thickness_mm} mm",
        center_x_m,
        note_y - 0.42,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.95,
        center=True,
    )
    _add_text(
        model_space,
        f"BOT. X: %%c{design.bar_x_mm} @ {design.spacing_x_mm} mm",
        note_x,
        note_y,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.82,
    )
    _add_text(
        model_space,
        f"BOT. Y: %%c{design.bar_y_mm} @ {design.spacing_y_mm} mm",
        note_x,
        note_y - 0.24,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.82,
    )
    _add_text(
        model_space,
        f"COLUMN {design.node.column_x_m:.2f} x {design.node.column_y_m:.2f} m | QTY {summary.quantity}",
        note_x,
        note_y - 0.68,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.75,
    )


def _draw_type_details(
    model_space: Any,
    project: DesignProject,
    settings: DrawingSettings,
    plan_extents: tuple[float, float, float, float],
) -> None:
    if not project.footing_types:
        return

    _, x_max, _, y_max = plan_extents
    maximum_x = max(summary.representative.length_x_m for summary in project.footing_types)
    maximum_y = max(summary.representative.length_y_m for summary in project.footing_types)
    cell_width = maximum_x + 4.0
    cell_height = maximum_y + 3.3
    details_start_x = x_max + 3.0 + maximum_x / 2.0
    details_start_y = y_max - maximum_y / 2.0
    number_of_columns = 2 if len(project.footing_types) > 1 else 1

    _add_text(
        model_space,
        "TYPICAL FOOTING REINFORCEMENT PLANS",
        details_start_x + (number_of_columns - 1) * cell_width / 2.0,
        y_max + 1.15,
        _layer_name(settings, "TEXT"),
        settings,
        height_m=settings.text_height_m * 1.20,
        center=True,
    )

    cover_m = project.settings.cover_mm / 1000.0
    for index, summary in enumerate(project.footing_types):
        column = index % number_of_columns
        row = index // number_of_columns
        center_x_m = details_start_x + column * cell_width
        center_y_m = details_start_y - row * cell_height
        _draw_single_type_detail(
            model_space,
            summary,
            center_x_m,
            center_y_m,
            settings,
            cover_m,
        )


def draw_foundation_plan(acad: Any, project: DesignProject, settings: DrawingSettings) -> None:
    """Draw the foundation plan and unique reinforcement plans in the open AutoCAD drawing."""
    if settings.units_per_metre <= 0:
        raise ValueError("AutoCAD units per metre must be greater than zero.")
    if settings.grid_tolerance_m < 0:
        raise ValueError("Grid tolerance cannot be negative.")

    document = acad.ActiveDocument
    model_space = document.ModelSpace
    layers = document.Layers

    for suffix, color in LAYER_COLORS.items():
        _ensure_layer(layers, _layer_name(settings, suffix), color)

    extents = _draw_grid_and_plan(model_space, project, settings)
    _draw_type_details(model_space, project, settings, extents)
    document.Regen(AcRegenType.acAllViewports)

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, pi
from typing import Any, Iterable, Sequence

import viktor as vkt


LAYER_COLORS = {
    "BORDER": 8,
    "OUTLINE": 7,
    "SUPPORT": 2,
    "REBAR": 1,
    "STIRRUP": 5,
    "TEXT": 4,
    "DIM": 3,
    "AUX": 9,
}


@dataclass(frozen=True)
class DrawingSettings:
    units_per_metre: float = 1000.0
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0
    layer_prefix: str = "VKT-RC"
    text_height_m: float = 0.16
    details_per_row: int = 2
    maximum_beams_to_draw: int = 40
    maximum_columns_to_draw: int = 40
    maximum_stirrup_symbols_per_member: int = 100
    draw_schedules: bool = True
    draw_border: bool = True

    def validate(self) -> None:
        if self.units_per_metre <= 0.0:
            raise ValueError("AutoCAD units per metre must be greater than zero.")
        if not self.layer_prefix.strip():
            raise ValueError("AutoCAD layer prefix cannot be blank.")
        if self.text_height_m <= 0.0:
            raise ValueError("AutoCAD text height must be greater than zero.")
        if self.details_per_row < 1 or self.details_per_row > 4:
            raise ValueError("Details per row must be between 1 and 4.")
        if self.maximum_beams_to_draw < 0 or self.maximum_columns_to_draw < 0:
            raise ValueError("Drawing member limits cannot be negative.")
        if self.maximum_stirrup_symbols_per_member < 10:
            raise ValueError("The stirrup-symbol limit must be at least 10 per member.")


def clean_prefix(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-" for character in value.strip())
    return cleaned or "VKT-RC"


def layer_name(settings: DrawingSettings, suffix: str) -> str:
    return f"{clean_prefix(settings.layer_prefix)}-{suffix}"


def point(x_m: float, y_m: float, settings: DrawingSettings) -> list[float]:
    return [float(x_m * settings.units_per_metre), float(y_m * settings.units_per_metre), 0.0]


def ensure_layer(layers: Any, name: str, color: int) -> Any:
    try:
        layer = layers.Add(name)
    except vkt.errors.ExecutionError:
        layer = layers.Item(name)
    layer.Color = int(color)
    return layer


def ensure_standard_layers(layers: Any, settings: DrawingSettings) -> None:
    for suffix, color in LAYER_COLORS.items():
        ensure_layer(layers, layer_name(settings, suffix), color)


def add_line(
    container: Any,
    start: tuple[float, float],
    end: tuple[float, float],
    layer: str,
    settings: DrawingSettings,
) -> Any:
    entity = container.AddLine(point(start[0], start[1], settings), point(end[0], end[1], settings))
    entity.Layer = layer
    return entity


def add_polyline(
    container: Any,
    points: Sequence[tuple[float, float]],
    layer: str,
    settings: DrawingSettings,
    *,
    closed: bool = False,
) -> Any:
    if len(points) < 2:
        raise ValueError("A polyline requires at least two points.")
    coordinates: list[float] = []
    for x_m, y_m in points:
        coordinates.extend([float(x_m * settings.units_per_metre), float(y_m * settings.units_per_metre)])
    entity = container.AddLightWeightPolyline(coordinates)
    entity.Layer = layer
    if closed:
        entity.Closed = True
    return entity


def add_rectangle(
    container: Any,
    x_min_m: float,
    y_min_m: float,
    x_max_m: float,
    y_max_m: float,
    layer: str,
    settings: DrawingSettings,
) -> Any:
    return add_polyline(
        container,
        (
            (x_min_m, y_min_m),
            (x_max_m, y_min_m),
            (x_max_m, y_max_m),
            (x_min_m, y_max_m),
        ),
        layer,
        settings,
        closed=True,
    )


def add_centered_rectangle(
    container: Any,
    center_x_m: float,
    center_y_m: float,
    width_m: float,
    height_m: float,
    layer: str,
    settings: DrawingSettings,
) -> Any:
    return add_rectangle(
        container,
        center_x_m - width_m / 2.0,
        center_y_m - height_m / 2.0,
        center_x_m + width_m / 2.0,
        center_y_m + height_m / 2.0,
        layer,
        settings,
    )


def add_circle(
    container: Any,
    center_x_m: float,
    center_y_m: float,
    radius_m: float,
    layer: str,
    settings: DrawingSettings,
) -> Any:
    entity = container.AddCircle(point(center_x_m, center_y_m, settings), float(radius_m * settings.units_per_metre))
    entity.Layer = layer
    return entity


def _estimated_text_width(text: str, height_m: float) -> float:
    return 0.31 * len(text) * height_m


def cad_text(text: object) -> str:
    return str(text).replace("Ø", "%%c").replace("ρ", "rho ").replace("ε", "eps ").replace("φ", "phi ")


def add_text(
    container: Any,
    text: object,
    x_m: float,
    y_m: float,
    layer: str,
    settings: DrawingSettings,
    *,
    height_m: float | None = None,
    rotation_rad: float = 0.0,
    center: bool = False,
) -> Any:
    content = cad_text(text)
    actual_height = settings.text_height_m if height_m is None else float(height_m)
    insertion_x = x_m - _estimated_text_width(content, actual_height) / 2.0 if center else x_m
    insertion_y = y_m - 0.35 * actual_height if center else y_m
    entity = container.AddText(
        content,
        point(insertion_x, insertion_y, settings),
        float(actual_height * settings.units_per_metre),
    )
    entity.Layer = layer
    if rotation_rad:
        entity.Rotation = float(rotation_rad)
    return entity


def add_text_lines(
    container: Any,
    lines: Iterable[object],
    x_m: float,
    y_m: float,
    layer: str,
    settings: DrawingSettings,
    *,
    height_m: float | None = None,
    line_spacing: float = 1.45,
) -> float:
    actual_height = settings.text_height_m if height_m is None else float(height_m)
    current_y = y_m
    for line in lines:
        add_text(container, line, x_m, current_y, layer, settings, height_m=actual_height)
        current_y -= actual_height * line_spacing
    return current_y


def add_horizontal_dimension(
    container: Any,
    x1_m: float,
    x2_m: float,
    object_y_m: float,
    dimension_y_m: float,
    layer: str,
    settings: DrawingSettings,
    *,
    text: str | None = None,
) -> None:
    if x2_m < x1_m:
        x1_m, x2_m = x2_m, x1_m
    tick = max(0.045, settings.text_height_m * 0.42)
    add_line(container, (x1_m, object_y_m), (x1_m, dimension_y_m + tick), layer, settings)
    add_line(container, (x2_m, object_y_m), (x2_m, dimension_y_m + tick), layer, settings)
    add_line(container, (x1_m, dimension_y_m), (x2_m, dimension_y_m), layer, settings)
    add_line(container, (x1_m - tick, dimension_y_m - tick), (x1_m + tick, dimension_y_m + tick), layer, settings)
    add_line(container, (x2_m - tick, dimension_y_m - tick), (x2_m + tick, dimension_y_m + tick), layer, settings)
    dimension_text = text if text is not None else f"{x2_m - x1_m:.2f} m"
    add_text(
        container,
        dimension_text,
        (x1_m + x2_m) / 2.0,
        dimension_y_m + 0.08,
        layer,
        settings,
        height_m=settings.text_height_m * 0.78,
        center=True,
    )


def add_vertical_dimension(
    container: Any,
    y1_m: float,
    y2_m: float,
    object_x_m: float,
    dimension_x_m: float,
    layer: str,
    settings: DrawingSettings,
    *,
    text: str | None = None,
) -> None:
    if y2_m < y1_m:
        y1_m, y2_m = y2_m, y1_m
    tick = max(0.045, settings.text_height_m * 0.42)
    add_line(container, (object_x_m, y1_m), (dimension_x_m + tick, y1_m), layer, settings)
    add_line(container, (object_x_m, y2_m), (dimension_x_m + tick, y2_m), layer, settings)
    add_line(container, (dimension_x_m, y1_m), (dimension_x_m, y2_m), layer, settings)
    add_line(container, (dimension_x_m - tick, y1_m - tick), (dimension_x_m + tick, y1_m + tick), layer, settings)
    add_line(container, (dimension_x_m - tick, y2_m - tick), (dimension_x_m + tick, y2_m + tick), layer, settings)
    dimension_text = text if text is not None else f"{y2_m - y1_m:.2f} m"
    add_text(
        container,
        dimension_text,
        dimension_x_m - 0.08,
        (y1_m + y2_m) / 2.0,
        layer,
        settings,
        height_m=settings.text_height_m * 0.78,
        rotation_rad=pi / 2.0,
        center=True,
    )


def evenly_spaced_positions(start_m: float, end_m: float, spacing_mm: int) -> list[float]:
    if end_m <= start_m:
        return []
    spacing_m = max(float(spacing_mm) / 1000.0, 1e-6)
    intervals = max(1, int(ceil((end_m - start_m) / spacing_m)))
    actual = (end_m - start_m) / intervals
    return [start_m + index * actual for index in range(intervals + 1)]


def limited_positions(
    start_m: float,
    end_m: float,
    spacing_mm: int,
    maximum_count: int,
) -> tuple[list[float], bool]:
    positions = evenly_spaced_positions(start_m, end_m, spacing_mm)
    if len(positions) <= maximum_count:
        return positions, False
    if maximum_count <= 2:
        return [positions[0], positions[-1]], True
    indexes = {
        round(index * (len(positions) - 1) / (maximum_count - 1))
        for index in range(maximum_count)
    }
    return [positions[index] for index in sorted(indexes)], True


def draw_table(
    container: Any,
    x_m: float,
    y_top_m: float,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    column_widths_m: Sequence[float],
    settings: DrawingSettings,
    *,
    title: str,
    row_height_m: float = 0.34,
) -> tuple[float, float, float, float]:
    if len(headers) != len(column_widths_m):
        raise ValueError("The number of headers must match the number of table column widths.")
    width = sum(column_widths_m)
    title_height = 0.42
    total_rows = 1 + len(rows)
    bottom = y_top_m - title_height - row_height_m * total_rows
    border_layer = layer_name(settings, "BORDER")
    text_layer = layer_name(settings, "TEXT")
    add_rectangle(container, x_m, bottom, x_m + width, y_top_m - title_height, border_layer, settings)
    add_text(
        container,
        title,
        x_m + width / 2.0,
        y_top_m,
        text_layer,
        settings,
        height_m=settings.text_height_m * 1.05,
        center=True,
    )

    current_x = x_m
    for column_width in column_widths_m[:-1]:
        current_x += column_width
        add_line(
            container,
            (current_x, bottom),
            (current_x, y_top_m - title_height),
            border_layer,
            settings,
        )
    for index in range(1, total_rows):
        y_value = y_top_m - title_height - index * row_height_m
        add_line(container, (x_m, y_value), (x_m + width, y_value), border_layer, settings)

    table_rows = [headers, *rows]
    for row_index, row in enumerate(table_rows):
        center_y = y_top_m - title_height - (row_index + 0.5) * row_height_m
        current_x = x_m
        for column_index, width_m in enumerate(column_widths_m):
            value = row[column_index] if column_index < len(row) else ""
            add_text(
                container,
                value,
                current_x + width_m / 2.0,
                center_y,
                text_layer,
                settings,
                height_m=settings.text_height_m * (0.72 if row_index else 0.76),
                center=True,
            )
            current_x += width_m
    return x_m, bottom, x_m + width, y_top_m

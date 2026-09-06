from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from foundation_design import DesignProject


@dataclass(frozen=True)
class DrawingRunSummary:
    document_name: str
    entities_created: int
    layers_ready: tuple[str, ...]
    layers_created: tuple[str, ...]
    x_grid_count: int
    y_grid_count: int


def build_drawing_log(project: DesignProject, run: DrawingRunSummary) -> str:
    """Create a human-readable record of a successful AutoCAD drawing run."""
    created_layers = set(run.layers_created)
    lines = [
        "AutoCAD foundation drawing creation log",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Drawing: {run.document_name}",
        f"Model-space entities created: {run.entities_created}",
        "",
        "Layers prepared",
    ]

    for layer_name in run.layers_ready:
        status = "created" if layer_name in created_layers else "already existed"
        lines.append(f"- {layer_name} ({status})")

    lines.extend(
        [
            "",
            "Foundation layout",
            f"- X gridlines drawn: {run.x_grid_count}",
            f"- Y gridlines drawn: {run.y_grid_count}",
            f"- Footing outlines drawn: {len(project.footings)}",
            f"- Column outlines drawn: {len(project.footings)}",
            f"- Unique reinforcement plans drawn: {len(project.footing_types)}",
            "",
            "Footings created",
        ]
    )

    for footing in project.footings:
        warnings = footing.warning or "None"
        lines.extend(
            [
                f"- {footing.node.node_id} ({footing.footing_type})",
                f"  Location: X={footing.node.x_m:.3f} m, Y={footing.node.y_m:.3f} m, Z={footing.node.z_m:.3f} m",
                f"  Footing: {footing.length_x_m:.2f} x {footing.length_y_m:.2f} m, h={footing.thickness_mm} mm",
                f"  Column: {footing.node.column_x_m:.3f} x {footing.node.column_y_m:.3f} m",
                f"  Bottom X reinforcement: diameter {footing.bar_x_mm} mm at {footing.spacing_x_mm} mm",
                f"  Bottom Y reinforcement: diameter {footing.bar_y_mm} mm at {footing.spacing_y_mm} mm",
                f"  Governing combinations: service={footing.service_governing_combination}, ultimate={footing.ultimate_governing_combination}",
                f"  Utilization: bearing={footing.bearing_utilization:.3f}, punching={footing.punching_utilization:.3f}, one-way X={footing.one_way_shear_x_utilization:.3f}, one-way Y={footing.one_way_shear_y_utilization:.3f}",
                f"  Warning: {warnings}",
            ]
        )

    lines.extend(["", "Footing types"])
    for summary in project.footing_types:
        lines.append(
            f"- {summary.mark}: quantity {summary.quantity}; nodes {', '.join(summary.node_ids)}"
        )

    lines.extend(
        [
            "",
            "The drawing remains open in AutoCAD and was not saved by the app.",
            "Review the created geometry, then save the DWG manually if it is correct.",
            "",
        ]
    )
    return "\n".join(lines)

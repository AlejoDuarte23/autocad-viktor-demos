from __future__ import annotations

from typing import Any, Iterable

from models import ColumnDemandCheck, ColumnDesign, InteractionPoint


def _mirrored_curve(
    points: Iterable[InteractionPoint],
    *,
    nominal: bool,
) -> tuple[list[float], list[float], list[str]]:
    ordered = list(points)
    if nominal:
        moments = [point.nominal_moment_knm for point in ordered]
        axials = [point.nominal_axial_kn for point in ordered]
        label = "Nominal"
    else:
        moments = [point.moment_knm for point in ordered]
        axials = [point.axial_kn for point in ordered]
        label = "Design"

    negative_x = [-value for value in reversed(moments)]
    negative_y = list(reversed(axials))
    x_values = negative_x + moments
    y_values = negative_y + axials
    hover = []
    for x_value, y_value in zip(x_values, y_values):
        hover.append(
            f"{label} capacity<br>P = {y_value:.1f} kN<br>M = {x_value:.1f} kN·m"
        )
    return x_values, y_values, hover


def _demand_trace(
    checks: tuple[ColumnDemandCheck, ...],
    axis: str,
    xaxis: str,
    yaxis: str,
    governing: ColumnDemandCheck,
) -> list[dict[str, Any]]:
    if axis == "M2":
        moments = [check.m2_knm for check in checks]
    else:
        moments = [check.m3_knm for check in checks]
    axials = [check.axial_kn for check in checks]
    hover = [
        (
            f"{check.combination} · {check.end}-end"
            f"<br>P = {check.axial_kn:.1f} kN"
            f"<br>{axis} = {(check.m2_knm if axis == 'M2' else check.m3_knm):.1f} kN·m"
            f"<br>Biaxial utilization = {check.biaxial_utilization:.3f}"
        )
        for check in checks
    ]
    traces: list[dict[str, Any]] = [
        {
            "type": "scatter",
            "mode": "markers",
            "name": f"{axis} demand",
            "x": moments,
            "y": axials,
            "text": hover,
            "hovertemplate": "%{text}<extra></extra>",
            "marker": {"size": 8, "symbol": "circle-open"},
            "xaxis": xaxis,
            "yaxis": yaxis,
            "legendgroup": axis,
        }
    ]

    governing_moment = governing.m2_knm if axis == "M2" else governing.m3_knm
    traces.append(
        {
            "type": "scatter",
            "mode": "markers+text",
            "name": f"{axis} governing",
            "x": [governing_moment],
            "y": [governing.axial_kn],
            "text": [f"{governing.combination} / {governing.end}"],
            "textposition": "top center",
            "hovertemplate": (
                f"{governing.combination} · {governing.end}-end"
                f"<br>P = {governing.axial_kn:.1f} kN"
                f"<br>{axis} = {governing_moment:.1f} kN·m"
                f"<br>Biaxial utilization = {governing.biaxial_utilization:.3f}"
                "<extra></extra>"
            ),
            "marker": {"size": 12, "symbol": "diamond"},
            "xaxis": xaxis,
            "yaxis": yaxis,
            "legendgroup": axis,
        }
    )
    return traces


def _capacity_traces(
    curve: tuple[InteractionPoint, ...],
    axis: str,
    xaxis: str,
    yaxis: str,
) -> list[dict[str, Any]]:
    design_x, design_y, design_hover = _mirrored_curve(curve, nominal=False)
    nominal_x, nominal_y, nominal_hover = _mirrored_curve(curve, nominal=True)
    return [
        {
            "type": "scatter",
            "mode": "lines",
            "name": f"{axis} nominal capacity",
            "x": nominal_x,
            "y": nominal_y,
            "text": nominal_hover,
            "hovertemplate": "%{text}<extra></extra>",
            "line": {"dash": "dot", "width": 1.5},
            "xaxis": xaxis,
            "yaxis": yaxis,
            "legendgroup": axis,
        },
        {
            "type": "scatter",
            "mode": "lines",
            "name": f"{axis} design capacity",
            "x": design_x,
            "y": design_y,
            "text": design_hover,
            "hovertemplate": "%{text}<extra></extra>",
            "line": {"width": 3},
            "xaxis": xaxis,
            "yaxis": yaxis,
            "legendgroup": axis,
        },
    ]


def column_interaction_figure(column: ColumnDesign) -> dict[str, Any]:
    """Return a Plotly dictionary containing P–M2 and P–M3 diagrams."""

    governing = max(column.demand_checks, key=lambda check: check.biaxial_utilization)
    traces: list[dict[str, Any]] = []
    traces.extend(_capacity_traces(column.interaction_m2, "M2", "x", "y"))
    traces.extend(_demand_trace(column.demand_checks, "M2", "x", "y", governing))
    traces.extend(_capacity_traces(column.interaction_m3, "M3", "x2", "y2"))
    traces.extend(_demand_trace(column.demand_checks, "M3", "x2", "y2", governing))

    member = column.member
    if member.shape == "Circular":
        section = f"Ø{member.diameter_mm:.0f} mm"
    else:
        section = f"{member.width_mm:.0f} × {member.depth_mm:.0f} mm"

    status_note = (
        f"Status: {column.status} · bars: {column.layout.description} "
        f"(ρg={column.layout.ratio:.4f}) · governing biaxial utilization: "
        f"{column.maximum_biaxial_utilization:.3f}"
    )
    return {
        "data": traces,
        "layout": {
            "title": {
                "text": (
                    f"Column {column.mark} / {member.label} — {member.story} — {section}"
                    f"<br><sup>{status_note}</sup>"
                ),
                "x": 0.5,
            },
            "showlegend": True,
            "legend": {"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.14},
            "hovermode": "closest",
            "margin": {"l": 80, "r": 40, "t": 100, "b": 90},
            "xaxis": {
                "domain": [0.0, 0.47],
                "title": {"text": "M2 [kN·m]"},
                "zeroline": True,
                "mirror": True,
                "showline": True,
            },
            "yaxis": {
                "domain": [0.0, 1.0],
                "title": {"text": "Axial force P [kN] (compression positive)"},
                "zeroline": True,
                "mirror": True,
                "showline": True,
            },
            "xaxis2": {
                "domain": [0.53, 1.0],
                "title": {"text": "M3 [kN·m]"},
                "zeroline": True,
                "mirror": True,
                "showline": True,
            },
            "yaxis2": {
                "domain": [0.0, 1.0],
                "matches": "y",
                "showticklabels": False,
                "zeroline": True,
                "mirror": True,
                "showline": True,
            },
            "annotations": [
                {
                    "text": "P–M2 interaction",
                    "x": 0.235,
                    "y": 1.04,
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                },
                {
                    "text": "P–M3 interaction",
                    "x": 0.765,
                    "y": 1.04,
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                },
            ],
        },
    }

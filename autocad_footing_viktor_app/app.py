from __future__ import annotations

import viktor as vkt

from autocad_drawing import DrawingSettings, draw_foundation_plan
from foundation_design import DesignInputError, DesignSettings, DesignProject, design_project


DEFAULT_NODES = [
    {"node_id": "N1", "x_m": 0.0, "y_m": 0.0, "z_m": 0.0, "column_x_mm": 400, "column_y_mm": 400},
    {"node_id": "N2", "x_m": 5.0, "y_m": 0.0, "z_m": 0.0, "column_x_mm": 400, "column_y_mm": 400},
    {"node_id": "N3", "x_m": 0.0, "y_m": 4.0, "z_m": 0.0, "column_x_mm": 450, "column_y_mm": 450},
    {"node_id": "N4", "x_m": 5.0, "y_m": 4.0, "z_m": 0.0, "column_x_mm": 450, "column_y_mm": 450},
]

DEFAULT_REACTIONS = [
    {"node_id": "N1", "combination": "SVC-1", "limit_state": "Service", "p_kn": 620, "mx_knm": 25, "my_knm": 18},
    {"node_id": "N1", "combination": "ULS-1", "limit_state": "Ultimate", "p_kn": 900, "mx_knm": 36, "my_knm": 28},
    {"node_id": "N2", "combination": "SVC-1", "limit_state": "Service", "p_kn": 710, "mx_knm": 35, "my_knm": 20},
    {"node_id": "N2", "combination": "ULS-1", "limit_state": "Ultimate", "p_kn": 1030, "mx_knm": 48, "my_knm": 32},
    {"node_id": "N3", "combination": "SVC-1", "limit_state": "Service", "p_kn": 820, "mx_knm": 30, "my_knm": 42},
    {"node_id": "N3", "combination": "ULS-1", "limit_state": "Ultimate", "p_kn": 1190, "mx_knm": 45, "my_knm": 61},
    {"node_id": "N4", "combination": "SVC-1", "limit_state": "Service", "p_kn": 930, "mx_knm": 46, "my_knm": 38},
    {"node_id": "N4", "combination": "ULS-1", "limit_state": "Ultimate", "p_kn": 1350, "mx_knm": 65, "my_knm": 54},
]


class Parametrization(vkt.Parametrization):
    intro = vkt.Text(
        "# Isolated Footing Designer → AutoCAD\n"
        "Enter support-center coordinates and matching reaction combinations. Service rows size each "
        "centered footing for allowable soil pressure and full contact; Ultimate rows size the preliminary "
        "thickness and bottom reinforcement. The summary view groups identical designs as F1, F2, and so on. "
        "Open the target drawing in AutoCAD before pressing the action button. The app draws in model space "
        "on `VKT-FDN-*` layers and does not save the DWG.\n\n"
        "**Engineering scope:** preliminary centered isolated footings only. A licensed engineer must confirm "
        "the governing design code, load combinations, geotechnical assumptions, sliding, overturning, "
        "settlement, development length, dowels, cover, edge conditions, and construction detailing."
    )

    nodes = vkt.Table(
        "Support nodes",
        default=DEFAULT_NODES,
        description="One row per ETABS support point. Coordinates are footing centers in metres.",
    )
    nodes.node_id = vkt.TextField("Node ID")
    nodes.x_m = vkt.NumberField("X", suffix="m")
    nodes.y_m = vkt.NumberField("Y", suffix="m")
    nodes.z_m = vkt.NumberField("Z", suffix="m")
    nodes.column_x_mm = vkt.NumberField("Column X", suffix="mm")
    nodes.column_y_mm = vkt.NumberField("Column Y", suffix="mm")

    reactions = vkt.Table(
        "Reaction combinations",
        default=DEFAULT_REACTIONS,
        description="Use positive P for compression. Keep Mx and My signs from the ETABS global axes.",
    )
    reactions.node_id = vkt.TextField("Node ID")
    reactions.combination = vkt.TextField("Combination")
    reactions.limit_state = vkt.OptionField("State", options=["Service", "Ultimate"])
    reactions.p_kn = vkt.NumberField("P", suffix="kN")
    reactions.mx_knm = vkt.NumberField("Mx", suffix="kN·m")
    reactions.my_knm = vkt.NumberField("My", suffix="kN·m")

    allowable_bearing_pressure = vkt.NumberField(
        "Allowable bearing pressure",
        default=200.0,
        suffix="kPa",
        min=1.0,
        flex=25,
    )
    minimum_reinforcement_ratio = vkt.NumberField(
        "Minimum reinforcement ratio",
        default=0.0018,
        min=0.0001,
        max=0.0199,
        step=0.0001,
        flex=25,
    )
    concrete_strength = vkt.NumberField(
        "Concrete strength f'c",
        default=28.0,
        suffix="MPa",
        min=10.0,
        flex=25,
    )
    steel_yield_strength = vkt.NumberField(
        "Steel yield strength fy",
        default=420.0,
        suffix="MPa",
        min=200.0,
        flex=25,
    )

    row_break_1 = vkt.LineBreak()

    concrete_cover = vkt.NumberField(
        "Bottom/side cover",
        default=75.0,
        suffix="mm",
        min=25.0,
        flex=25,
    )
    preferred_bar_diameter = vkt.OptionField(
        "Preferred bar diameter",
        options=[12, 16, 20, 25, 32],
        default=16,
        suffix="mm",
        flex=25,
    )
    self_weight_allowance = vkt.NumberField(
        "Footing/self-weight allowance",
        default=10.0,
        suffix="% of service P",
        min=0.0,
        max=50.0,
        flex=25,
    )
    autocad_units_per_metre = vkt.NumberField(
        "AutoCAD units per metre",
        default=1000.0,
        min=0.001,
        description="Use 1000 for a millimetre drawing or 1 for a metre drawing.",
        flex=25,
    )

    row_break_2 = vkt.LineBreak()

    grid_tolerance = vkt.NumberField(
        "Grid coordinate tolerance",
        default=0.05,
        suffix="m",
        min=0.0,
        description="Coordinates within this distance are assigned to the same inferred gridline.",
        flex=25,
    )
    calculate_and_draw = vkt.ActionButton(
        "Calculate and generate AutoCAD drawing",
        method="calculate_and_draw_in_autocad",
        longpoll=True,
        flex=75,
    )


class Controller(vkt.Controller):
    parametrization = Parametrization(width=52)

    @staticmethod
    def _settings(params) -> DesignSettings:
        return DesignSettings(
            allowable_bearing_pressure_kpa=float(params.allowable_bearing_pressure),
            minimum_reinforcement_ratio=float(params.minimum_reinforcement_ratio),
            concrete_strength_mpa=float(params.concrete_strength),
            steel_yield_strength_mpa=float(params.steel_yield_strength),
            cover_mm=float(params.concrete_cover),
            preferred_bar_diameter_mm=int(params.preferred_bar_diameter),
            self_weight_allowance_pct=float(params.self_weight_allowance),
        )

    @classmethod
    def _project(cls, params) -> DesignProject:
        try:
            return design_project(params.nodes, params.reactions, cls._settings(params))
        except DesignInputError as exc:
            raise vkt.UserError(str(exc)) from exc

    @vkt.TableView(
        "Footing design summary",
        duration_guess=1,
        description="One row per unique footing and reinforcement type.",
    )
    def footing_summary(self, params, **kwargs):
        project = self._project(params)
        rows = []
        for summary in project.footing_types:
            footing = summary.representative
            warnings = sorted(
                {
                    member.warning
                    for member in project.footings
                    if member.footing_type == summary.mark and member.warning
                }
            )
            rows.append(
                [
                    summary.mark,
                    summary.quantity,
                    ", ".join(summary.node_ids),
                    footing.length_x_m,
                    footing.length_y_m,
                    footing.thickness_mm,
                    f"Ø{footing.bar_x_mm} @ {footing.spacing_x_mm}",
                    f"Ø{footing.bar_y_mm} @ {footing.spacing_y_mm}",
                    round(summary.maximum_bearing_utilization, 3),
                    round(summary.maximum_punching_utilization, 3),
                    round(summary.maximum_one_way_shear_utilization, 3),
                    "; ".join(warnings) if warnings else "OK",
                ]
            )

        return vkt.TableResult(
            rows,
            column_headers=[
                "Type",
                "Qty",
                "Nodes",
                "Lx [m]",
                "Ly [m]",
                "h [mm]",
                "Bottom X",
                "Bottom Y",
                "Bearing util.",
                "Punching util.",
                "1-way shear util.",
                "Status / note",
            ],
            show_index=False,
            enable_column_autosizing=True,
        )

    def calculate_and_draw_in_autocad(self, params, **kwargs):
        project = self._project(params)
        drawing_settings = DrawingSettings(
            units_per_metre=float(params.autocad_units_per_metre),
            grid_tolerance_m=float(params.grid_tolerance),
        )

        try:
            with vkt.autocad.attach(timeout=180) as acad:
                draw_foundation_plan(acad, project, drawing_settings)
        except vkt.errors.WorkerSessionAttachError as err:
            if err.reason == "error_attach_no_instance":
                raise vkt.UserError(
                    "No AutoCAD instance was found on the personal worker. Open the target drawing in "
                    "AutoCAD on the machine running VIKTOR Desktop, then try again."
                ) from err
            if err.reason == "error_attach_refused":
                raise vkt.UserError(
                    "AutoCAD was found but refused the connection. Close any modal dialog, let AutoCAD "
                    "finish its current command, and try again."
                ) from err
            raise vkt.UserError(
                f"Could not attach to AutoCAD ({err.reason or 'unknown reason'})."
            ) from err
        except vkt.errors.ExecutionError as err:
            raise vkt.UserError(f"AutoCAD reported an error while drawing: {err}") from err
        except vkt.errors.WorkerSessionError as err:
            raise vkt.UserError(
                "The AutoCAD connection was lost while drawing. The open drawing may contain a partial result."
            ) from err
        except TimeoutError as err:
            raise vkt.UserError(
                "Drawing in AutoCAD timed out. Let AutoCAD finish its current work and try again."
            ) from err

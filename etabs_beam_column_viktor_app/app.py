from __future__ import annotations

from math import isfinite
from typing import Any

import viktor as vkt

from autocad_common import DrawingSettings
from autocad_drawing import draw_beam_and_column_details
from etabs_reader import ETABSImportSettings, ETABSReadError, read_attached_etabs_model
from interaction_diagrams import column_interaction_figure
from models import DesignInputError, DesignSettings, ProjectDesign
from project_design import design_project


DEFAULT_BEAM_MEMBERS = [
    {
        "member_id": "B1-ETABS",
        "label": "B1",
        "story": "Story 1",
        "section_name": "B300x600",
        "material_name": "C28",
        "point_i": "P1",
        "point_j": "P2",
        "i_x_m": 0.0,
        "i_y_m": 0.0,
        "i_z_m": 3.2,
        "j_x_m": 6.0,
        "j_y_m": 0.0,
        "j_z_m": 3.2,
        "width_mm": 300.0,
        "depth_mm": 600.0,
        "angle_deg": 0.0,
    }
]

DEFAULT_BEAM_FORCES = [
    {"member_id": "B1-ETABS", "combination": "ULS-1", "station_m": 0.0, "step_type": "", "step_num": 0.0, "p_kn": 0.0, "v2_kn": 145.0, "v3_kn": 0.0, "t_knm": 8.0, "m2_knm": 0.0, "m3_knm": -185.0},
    {"member_id": "B1-ETABS", "combination": "ULS-1", "station_m": 1.5, "step_type": "", "step_num": 0.0, "p_kn": 0.0, "v2_kn": 78.0, "v3_kn": 0.0, "t_knm": 5.0, "m2_knm": 0.0, "m3_knm": -70.0},
    {"member_id": "B1-ETABS", "combination": "ULS-1", "station_m": 3.0, "step_type": "", "step_num": 0.0, "p_kn": 0.0, "v2_kn": 28.0, "v3_kn": 0.0, "t_knm": 3.0, "m2_knm": 0.0, "m3_knm": 135.0},
    {"member_id": "B1-ETABS", "combination": "ULS-1", "station_m": 4.5, "step_type": "", "step_num": 0.0, "p_kn": 0.0, "v2_kn": -72.0, "v3_kn": 0.0, "t_knm": 5.0, "m2_knm": 0.0, "m3_knm": -62.0},
    {"member_id": "B1-ETABS", "combination": "ULS-1", "station_m": 6.0, "step_type": "", "step_num": 0.0, "p_kn": 0.0, "v2_kn": -138.0, "v3_kn": 0.0, "t_knm": 7.5, "m2_knm": 0.0, "m3_knm": -172.0},
]

DEFAULT_COLUMN_MEMBERS = [
    {
        "member_id": "C1-ETABS",
        "label": "C1",
        "story": "Story 1",
        "section_name": "C500x500",
        "material_name": "C28",
        "point_i": "P3",
        "point_j": "P4",
        "i_x_m": 0.0,
        "i_y_m": 0.0,
        "i_z_m": 0.0,
        "j_x_m": 0.0,
        "j_y_m": 0.0,
        "j_z_m": 3.2,
        "shape": "Rectangular",
        "width_mm": 500.0,
        "depth_mm": 500.0,
        "diameter_mm": 0.0,
        "angle_deg": 0.0,
    }
]

DEFAULT_COLUMN_FORCES = [
    {"member_id": "C1-ETABS", "combination": "ULS-1", "end": "I", "station_m": 0.0, "step_type": "", "step_num": 0.0, "p_kn": 1800.0, "v2_kn": 95.0, "v3_kn": 82.0, "t_knm": 4.0, "m2_knm": 140.0, "m3_knm": 120.0},
    {"member_id": "C1-ETABS", "combination": "ULS-1", "end": "J", "station_m": 3.2, "step_type": "", "step_num": 0.0, "p_kn": 1620.0, "v2_kn": 80.0, "v3_kn": 68.0, "t_knm": 3.0, "m2_knm": 118.0, "m3_knm": 104.0},
    {"member_id": "C1-ETABS", "combination": "ULS-2", "end": "I", "station_m": 0.0, "step_type": "", "step_num": 0.0, "p_kn": 1520.0, "v2_kn": 78.0, "v3_kn": 105.0, "t_knm": 5.0, "m2_knm": -105.0, "m3_knm": 152.0},
    {"member_id": "C1-ETABS", "combination": "ULS-2", "end": "J", "station_m": 3.2, "step_type": "", "step_num": 0.0, "p_kn": 1420.0, "v2_kn": 66.0, "v3_kn": 92.0, "t_knm": 4.0, "m2_knm": -92.0, "m3_knm": 138.0},
]


def column_options(params: Any, **kwargs: Any) -> list[str]:
    del kwargs
    options: list[str] = []
    rows = getattr(params, "column_members", None) or []
    for row in rows:
        member_id = row.get("member_id") if isinstance(row, dict) else getattr(row, "member_id", None)
        if member_id is not None and str(member_id).strip():
            options.append(str(member_id).strip())
    return list(dict.fromkeys(options))


class Parametrization(vkt.Parametrization):
    intro = vkt.Text(
        "# ETABS RC Beam and Column Designer → AutoCAD\n"
        "Attach to the analyzed ETABS model, import concrete frame geometry and selected response-combination "
        "forces, review the editable tables, and generate preliminary reinforced-concrete beam and column "
        "details in the AutoCAD drawing already open on the personal worker. The result views show beam and "
        "column design summaries and two column interaction diagrams: P–M2 and P–M3.\n\n"
        "**Data convention:** ETABS frame results remain in local axes. Beam flexure uses M3 and shear uses V2. "
        "Column P is converted to compression-positive when the corresponding import option is enabled. "
        "Use factored strength combinations in the ETABS combination filter.\n\n"
        "**Engineering scope:** this implementation performs transparent preliminary ACI-style member sizing. "
        "A licensed engineer must verify the governing code edition, load combinations, diaphragm and joint "
        "behavior, second-order effects, seismic detailing, torsion treatment, development and lap lengths, "
        "bar curtailment, fire/durability cover, constructability, and the final construction documents."
    )

    combination_filter = vkt.TextField(
        "ETABS response-combination filter",
        default="*",
        description="Comma-separated wildcard patterns. Example: ULS*,STR*. Only response combinations are read.",
        flex=25,
    )
    story_filter = vkt.TextField(
        "Story filter",
        default="*",
        description="Comma-separated wildcard patterns matched against ETABS story names.",
        flex=25,
    )
    beam_filter = vkt.TextField(
        "Beam label/object filter",
        default="*",
        description="Comma-separated wildcard patterns matched against the ETABS beam label or object name.",
        flex=25,
    )
    column_filter = vkt.TextField(
        "Column label/object filter",
        default="*",
        description="Comma-separated wildcard patterns matched against the ETABS column label or object name.",
        flex=25,
    )

    import_line_1 = vkt.LineBreak()

    result_group_name = vkt.TextField(
        "ETABS result group",
        default="ALL",
        description="The importer first requests this ETABS group and falls back to object-by-object results.",
        flex=25,
    )
    compression_is_negative = vkt.BooleanField(
        "ETABS P is negative in compression",
        default=True,
        description="Enabled: imported column P values are multiplied by -1 so compression is positive in the app.",
        flex=25,
    )
    column_vertical_ratio = vkt.NumberField(
        "Column vertical-component ratio",
        default=0.75,
        min=0.50,
        max=1.00,
        step=0.05,
        description="A frame is treated as a column when |ΔZ|/length is at least this value.",
        flex=25,
    )
    maximum_members = vkt.IntegerField(
        "Maximum ETABS members to import",
        default=250,
        min=1,
        max=2000,
        flex=25,
    )

    import_line_2 = vkt.LineBreak()

    maximum_beam_rows_per_combination = vkt.IntegerField(
        "Maximum beam stations per combination",
        default=21,
        min=5,
        max=101,
        description="Critical stations are retained when ETABS returns more result locations.",
        flex=25,
    )
    read_etabs = vkt.SetParamsButton(
        "Read analyzed model from attached ETABS",
        method="read_from_etabs",
        longpoll=True,
        flex=75,
    )

    import_summary = vkt.TextField(
        "Last ETABS import summary",
        default="Sample beam and column data are loaded. Press the ETABS button to replace them.",
        description="Written by the ETABS import action. It is informational and may be edited.",
        flex=100,
    )

    beam_members = vkt.Table(
        "Beam members",
        default=DEFAULT_BEAM_MEMBERS,
        description="One row per supported rectangular concrete beam. Coordinates are in metres; section dimensions are in millimetres.",
    )
    beam_members.member_id = vkt.TextField("ETABS object")
    beam_members.label = vkt.TextField("Beam label")
    beam_members.story = vkt.TextField("Story")
    beam_members.section_name = vkt.TextField("Section")
    beam_members.material_name = vkt.TextField("Material")
    beam_members.point_i = vkt.TextField("Point I")
    beam_members.point_j = vkt.TextField("Point J")
    beam_members.i_x_m = vkt.NumberField("I-X [m]")
    beam_members.i_y_m = vkt.NumberField("I-Y [m]")
    beam_members.i_z_m = vkt.NumberField("I-Z [m]")
    beam_members.j_x_m = vkt.NumberField("J-X [m]")
    beam_members.j_y_m = vkt.NumberField("J-Y [m]")
    beam_members.j_z_m = vkt.NumberField("J-Z [m]")
    beam_members.width_mm = vkt.NumberField("b [mm]")
    beam_members.depth_mm = vkt.NumberField("h [mm]")
    beam_members.angle_deg = vkt.NumberField("Angle [deg]")

    beam_forces = vkt.Table(
        "Beam frame-force results",
        default=DEFAULT_BEAM_FORCES,
        description="One row per retained station and strength combination. M3 and V2 govern the preliminary beam design.",
    )
    beam_forces.member_id = vkt.TextField("ETABS object")
    beam_forces.combination = vkt.TextField("Combination")
    beam_forces.station_m = vkt.NumberField("Station [m]")
    beam_forces.step_type = vkt.TextField("Step type")
    beam_forces.step_num = vkt.NumberField("Step")
    beam_forces.p_kn = vkt.NumberField("P [kN]")
    beam_forces.v2_kn = vkt.NumberField("V2 [kN]")
    beam_forces.v3_kn = vkt.NumberField("V3 [kN]")
    beam_forces.t_knm = vkt.NumberField("T [kN·m]")
    beam_forces.m2_knm = vkt.NumberField("M2 [kN·m]")
    beam_forces.m3_knm = vkt.NumberField("M3 [kN·m]")

    column_members = vkt.Table(
        "Column members",
        default=DEFAULT_COLUMN_MEMBERS,
        description="One row per supported rectangular or circular concrete column.",
    )
    column_members.member_id = vkt.TextField("ETABS object")
    column_members.label = vkt.TextField("Column label")
    column_members.story = vkt.TextField("Story")
    column_members.section_name = vkt.TextField("Section")
    column_members.material_name = vkt.TextField("Material")
    column_members.point_i = vkt.TextField("Point I")
    column_members.point_j = vkt.TextField("Point J")
    column_members.i_x_m = vkt.NumberField("I-X [m]")
    column_members.i_y_m = vkt.NumberField("I-Y [m]")
    column_members.i_z_m = vkt.NumberField("I-Z [m]")
    column_members.j_x_m = vkt.NumberField("J-X [m]")
    column_members.j_y_m = vkt.NumberField("J-Y [m]")
    column_members.j_z_m = vkt.NumberField("J-Z [m]")
    column_members.shape = vkt.OptionField("Shape", options=["Rectangular", "Circular"])
    column_members.width_mm = vkt.NumberField("b [mm]")
    column_members.depth_mm = vkt.NumberField("h [mm]")
    column_members.diameter_mm = vkt.NumberField("Diameter [mm]")
    column_members.angle_deg = vkt.NumberField("Angle [deg]")

    column_forces = vkt.Table(
        "Column frame-force results",
        default=DEFAULT_COLUMN_FORCES,
        description="Compression is positive. P, M2, and M3 from each row are checked together.",
    )
    column_forces.member_id = vkt.TextField("ETABS object")
    column_forces.combination = vkt.TextField("Combination")
    column_forces.end = vkt.OptionField("End", options=["I", "J", "Intermediate"])
    column_forces.station_m = vkt.NumberField("Station [m]")
    column_forces.step_type = vkt.TextField("Step type")
    column_forces.step_num = vkt.NumberField("Step")
    column_forces.p_kn = vkt.NumberField("P [kN]")
    column_forces.v2_kn = vkt.NumberField("V2 [kN]")
    column_forces.v3_kn = vkt.NumberField("V3 [kN]")
    column_forces.t_knm = vkt.NumberField("T [kN·m]")
    column_forces.m2_knm = vkt.NumberField("M2 [kN·m]")
    column_forces.m3_knm = vkt.NumberField("M3 [kN·m]")

    concrete_strength = vkt.NumberField("Concrete strength f'c", default=28.0, suffix="MPa", min=10.0, flex=25)
    steel_yield_strength = vkt.NumberField("Longitudinal steel fy", default=420.0, suffix="MPa", min=200.0, flex=25)
    steel_modulus = vkt.NumberField("Steel modulus Es", default=200000.0, suffix="MPa", min=100000.0, flex=25)
    concrete_cover = vkt.NumberField("Clear concrete cover", default=40.0, suffix="mm", min=20.0, flex=25)

    design_line_1 = vkt.LineBreak()

    preferred_beam_bar = vkt.OptionField("Preferred beam bar", options=[12, 16, 20, 25, 32], default=20, suffix="mm", flex=25)
    preferred_column_bar = vkt.OptionField("Preferred column bar", options=[16, 20, 25, 32], default=20, suffix="mm", flex=25)
    preferred_stirrup = vkt.OptionField("Preferred stirrup/tie", options=[8, 10, 12, 16], default=10, suffix="mm", flex=25)
    minimum_beam_bars = vkt.IntegerField("Minimum bars per beam face", default=2, min=2, max=8, flex=25)

    design_line_2 = vkt.LineBreak()

    shear_phi = vkt.NumberField(
        "Shear strength-reduction factor φ",
        default=0.75,
        min=0.50,
        max=1.00,
        step=0.05,
        flex=25,
    )
    development_length_factor = vkt.NumberField(
        "Detailing extension factor",
        default=40.0,
        min=10.0,
        max=100.0,
        step=1.0,
        description="Preliminary straight-bar extension expressed as a multiple of the bar diameter.",
        flex=25,
    )

    minimum_column_ratio = vkt.NumberField("Minimum column steel ratio", default=0.01, min=0.005, max=0.09, step=0.001, flex=25)
    maximum_column_ratio = vkt.NumberField("Maximum column steel ratio", default=0.06, min=0.006, max=0.10, step=0.001, flex=25)
    column_biaxial_exponent = vkt.NumberField("Biaxial interaction exponent", default=1.0, min=0.5, max=2.0, step=0.1, flex=25)
    effective_length_factor = vkt.NumberField("Column effective-length factor k", default=1.0, min=0.1, max=3.0, step=0.1, flex=25)

    design_line_3 = vkt.LineBreak()

    assume_etabs_pdelta = vkt.BooleanField("ETABS P-Delta included", default=True, flex=25)
    design_torsion = vkt.BooleanField("Include preliminary beam torsion design", default=True, flex=25)
    slenderness_warning_limit = vkt.NumberField("Column slenderness warning L/r", default=22.0, min=5.0, max=200.0, flex=25)
    selected_column = vkt.AutocompleteField(
        "Column shown in the interaction view",
        options=column_options,
        default="C1-ETABS",
        flex=25,
    )

    autocad_units_per_metre = vkt.NumberField(
        "AutoCAD units per metre",
        default=1000.0,
        min=0.001,
        description="Use 1000 for a millimetre drawing or 1 for a metre drawing.",
        flex=25,
    )
    autocad_origin_x = vkt.NumberField("Drawing origin X", default=0.0, suffix="m", flex=25)
    autocad_origin_y = vkt.NumberField("Drawing origin Y", default=0.0, suffix="m", flex=25)
    autocad_layer_prefix = vkt.TextField("AutoCAD layer prefix", default="VKT-RC", flex=25)

    drawing_line_1 = vkt.LineBreak()

    autocad_text_height = vkt.NumberField("Drawing text height", default=0.16, suffix="m", min=0.02, flex=25)
    details_per_row = vkt.IntegerField("Details per drawing row", default=2, min=1, max=4, flex=25)
    maximum_beams_to_draw = vkt.IntegerField("Maximum beams to draw", default=40, min=0, max=500, flex=25)
    maximum_columns_to_draw = vkt.IntegerField("Maximum columns to draw", default=40, min=0, max=500, flex=25)

    drawing_line_2 = vkt.LineBreak()

    maximum_stirrup_symbols = vkt.IntegerField("Maximum stirrup/tie symbols per member", default=100, min=10, max=500, flex=25)
    draw_schedules = vkt.BooleanField("Draw reinforcement schedules", default=True, flex=25)
    draw_border = vkt.BooleanField("Draw border and title block", default=True, flex=25)
    calculate_and_draw = vkt.ActionButton(
        "Calculate designs and generate AutoCAD drawings",
        method="calculate_and_draw_in_autocad",
        longpoll=True,
        flex=25,
    )


class Controller(vkt.Controller):
    parametrization = Parametrization(width=62)

    @staticmethod
    def _design_settings(params: Any) -> DesignSettings:
        return DesignSettings(
            concrete_strength_mpa=float(params.concrete_strength),
            steel_yield_strength_mpa=float(params.steel_yield_strength),
            steel_modulus_mpa=float(params.steel_modulus),
            concrete_cover_mm=float(params.concrete_cover),
            preferred_beam_bar_mm=int(params.preferred_beam_bar),
            preferred_column_bar_mm=int(params.preferred_column_bar),
            preferred_stirrup_mm=int(params.preferred_stirrup),
            minimum_beam_bars=int(params.minimum_beam_bars),
            shear_phi=float(params.shear_phi),
            development_length_factor=float(params.development_length_factor),
            minimum_column_ratio=float(params.minimum_column_ratio),
            maximum_column_ratio=float(params.maximum_column_ratio),
            column_biaxial_exponent=float(params.column_biaxial_exponent),
            assume_etabs_pdelta=bool(params.assume_etabs_pdelta),
            column_effective_length_factor=float(params.effective_length_factor),
            slenderness_warning_limit=float(params.slenderness_warning_limit),
            design_torsion=bool(params.design_torsion),
        )

    @classmethod
    def _project(cls, params: Any) -> ProjectDesign:
        try:
            return design_project(
                params.beam_members,
                params.beam_forces,
                params.column_members,
                params.column_forces,
                cls._design_settings(params),
            )
        except DesignInputError as exc:
            raise vkt.UserError(str(exc)) from exc

    @staticmethod
    def _ratio(value: float) -> float | None:
        return round(value, 3) if isfinite(value) else None

    def read_from_etabs(self, params: Any, **kwargs: Any) -> vkt.SetParamsResult:
        del kwargs
        import_settings = ETABSImportSettings(
            combination_filter=str(params.combination_filter),
            story_filter=str(params.story_filter),
            beam_filter=str(params.beam_filter),
            column_filter=str(params.column_filter),
            result_group_name=str(params.result_group_name),
            compression_is_negative=bool(params.compression_is_negative),
            column_vertical_ratio=float(params.column_vertical_ratio),
            maximum_members=int(params.maximum_members),
            maximum_beam_rows_per_combination=int(params.maximum_beam_rows_per_combination),
        )
        try:
            with vkt.etabs.attach(timeout=180) as sap:
                imported = read_attached_etabs_model(sap, import_settings)
        except vkt.errors.WorkerSessionAttachError as err:
            reason = err.reason or "unknown reason"
            if reason == "error_attach_no_instance":
                raise vkt.UserError(
                    "No ETABS instance was found on the personal worker. Open and analyze the target ETABS model, then try again."
                ) from err
            if reason == "error_attach_wrong_product":
                raise vkt.UserError(
                    "The running CSI instance is not ETABS. Open the model in ETABS on the machine running VIKTOR Desktop."
                ) from err
            if reason == "error_attach_refused":
                raise vkt.UserError(
                    "ETABS was found but refused the connection. Close modal dialogs, finish the current ETABS command, and try again."
                ) from err
            raise vkt.UserError(f"Could not attach to ETABS ({reason}).") from err
        except ETABSReadError as err:
            raise vkt.UserError(str(err)) from err
        except vkt.errors.ExecutionError as err:
            raise vkt.UserError(f"ETABS reported an error while reading the model: {err}") from err
        except vkt.errors.WorkerSessionError as err:
            raise vkt.UserError("The ETABS connection was lost while reading the model.") from err
        except TimeoutError as err:
            raise vkt.UserError("Reading ETABS timed out. Confirm that ETABS is responsive and try again.") from err

        selected_column = imported.column_members[0]["member_id"] if imported.column_members else None
        summary_parts = [
            f"Imported {len(imported.beam_members)} beams",
            f"{len(imported.beam_forces)} beam result rows",
            f"{len(imported.column_members)} columns",
            f"{len(imported.column_forces)} column result rows",
            f"combinations: {', '.join(imported.selected_combinations)}",
        ]
        if imported.notes:
            summary_parts.append("notes: " + "; ".join(imported.notes))
        return vkt.SetParamsResult(
            {
                "beam_members": list(imported.beam_members),
                "beam_forces": list(imported.beam_forces),
                "column_members": list(imported.column_members),
                "column_forces": list(imported.column_forces),
                "selected_column": selected_column,
                "import_summary": " | ".join(summary_parts),
            }
        )

    @vkt.TableView(
        "Beam design summary",
        duration_guess=3,
        description="Preliminary flexural, shear, torsion, and reinforcement results for every imported beam.",
    )
    def beam_design_summary(self, params: Any, **kwargs: Any) -> vkt.TableResult:
        del kwargs
        project = self._project(params)
        rows = []
        for beam in project.beams:
            rows.append(
                [
                    beam.mark,
                    beam.member.story,
                    beam.member.label,
                    beam.member.member_id,
                    f"{beam.member.width_mm:.0f} × {beam.member.depth_mm:.0f}",
                    round(beam.member.length_m, 3),
                    beam.top_left.description,
                    beam.top_mid.description,
                    beam.top_right.description,
                    beam.bottom_left.description,
                    beam.bottom_mid.description,
                    beam.bottom_right.description,
                    beam.stirrup_left.description,
                    beam.stirrup_mid.description,
                    beam.stirrup_right.description,
                    beam.governing_combination,
                    round(beam.governing_moment_knm, 2),
                    round(beam.governing_shear_kn, 2),
                    round(beam.governing_torsion_knm, 2),
                    self._ratio(beam.maximum_flexural_utilization),
                    self._ratio(beam.maximum_shear_utilization),
                    self._ratio(beam.maximum_torsion_utilization),
                    beam.status,
                    "; ".join(beam.warnings),
                ]
            )
        return vkt.TableResult(
            rows,
            column_headers=[
                "Mark",
                "Story",
                "Beam",
                "ETABS object",
                "Section [mm]",
                "Length [m]",
                "Top left",
                "Top mid",
                "Top right",
                "Bottom left",
                "Bottom mid",
                "Bottom right",
                "Stirrups left",
                "Stirrups mid",
                "Stirrups right",
                "Governing combo",
                "|Mu| [kN·m]",
                "|Vu| [kN]",
                "|Tu| [kN·m]",
                "Flex. util.",
                "Shear util.",
                "Torsion util.",
                "Status",
                "Warnings",
            ],
            show_index=False,
            enable_sorting_and_filtering=True,
            enable_column_autosizing=True,
        )

    @vkt.TableView(
        "Column design summary",
        duration_guess=5,
        description="Preliminary reinforcement, shear, slenderness, and uniaxial/biaxial interaction results for every column.",
    )
    def column_design_summary(self, params: Any, **kwargs: Any) -> vkt.TableResult:
        del kwargs
        project = self._project(params)
        rows = []
        for column in project.columns:
            member = column.member
            section = f"Ø{member.diameter_mm:.0f}" if member.shape == "Circular" else f"{member.width_mm:.0f} × {member.depth_mm:.0f}"
            governing_check = max(column.demand_checks, key=lambda check: check.biaxial_utilization)
            rows.append(
                [
                    column.mark,
                    member.story,
                    member.label,
                    member.member_id,
                    member.shape,
                    section,
                    round(member.length_m, 3),
                    column.layout.description,
                    round(column.layout.ratio, 4),
                    f"Ø{column.tie_diameter_mm} @ {column.tie_spacing_end_mm}",
                    f"Ø{column.tie_diameter_mm} @ {column.tie_spacing_mid_mm}",
                    round(column.confinement_length_mm, 0),
                    f"{column.tie_legs_per_direction} legs/axis",
                    round(column.governing_shear_kn, 2),
                    round(column.shear_capacity_kn, 2),
                    self._ratio(column.maximum_shear_utilization),
                    column.governing_combination,
                    column.governing_end,
                    round(governing_check.axial_kn, 2),
                    round(governing_check.m2_knm, 2),
                    round(governing_check.m3_knm, 2),
                    round(column.slenderness_m2, 2),
                    round(column.slenderness_m3, 2),
                    self._ratio(column.maximum_axial_utilization),
                    self._ratio(column.maximum_m2_utilization),
                    self._ratio(column.maximum_m3_utilization),
                    self._ratio(column.maximum_biaxial_utilization),
                    column.status,
                    "; ".join(column.warnings),
                ]
            )
        return vkt.TableResult(
            rows,
            column_headers=[
                "Mark",
                "Story",
                "Column",
                "ETABS object",
                "Shape",
                "Section [mm]",
                "Height [m]",
                "Longitudinal bars",
                "ρg",
                "End-zone ties [mm]",
                "Mid-height ties [mm]",
                "Confinement length [mm]",
                "Tie legs",
                "|Vu|max [kN]",
                "φVn [kN]",
                "Shear util.",
                "Governing combo",
                "End",
                "Pu [kN]",
                "M2u [kN·m]",
                "M3u [kN·m]",
                "L/r axis 2",
                "L/r axis 3",
                "Axial util.",
                "P–M2 util.",
                "P–M3 util.",
                "Biaxial util.",
                "Status",
                "Warnings",
            ],
            show_index=False,
            enable_sorting_and_filtering=True,
            enable_column_autosizing=True,
        )

    @vkt.PlotlyView(
        "Column P–M2 and P–M3 interaction diagrams",
        duration_guess=5,
        description="Design and nominal interaction envelopes with all imported demand points for the selected column.",
    )
    def column_interaction_diagrams(self, params: Any, **kwargs: Any) -> vkt.PlotlyResult:
        del kwargs
        project = self._project(params)
        try:
            column = project.column_by_id(params.selected_column)
        except DesignInputError as exc:
            raise vkt.UserError(str(exc)) from exc
        return vkt.PlotlyResult(column_interaction_figure(column))

    def calculate_and_draw_in_autocad(self, params: Any, **kwargs: Any) -> None:
        del kwargs
        project = self._project(params)
        drawing_settings = DrawingSettings(
            units_per_metre=float(params.autocad_units_per_metre),
            origin_x_m=float(params.autocad_origin_x),
            origin_y_m=float(params.autocad_origin_y),
            layer_prefix=str(params.autocad_layer_prefix),
            text_height_m=float(params.autocad_text_height),
            details_per_row=int(params.details_per_row),
            maximum_beams_to_draw=int(params.maximum_beams_to_draw),
            maximum_columns_to_draw=int(params.maximum_columns_to_draw),
            maximum_stirrup_symbols_per_member=int(params.maximum_stirrup_symbols),
            draw_schedules=bool(params.draw_schedules),
            draw_border=bool(params.draw_border),
        )
        try:
            with vkt.autocad.attach(timeout=180) as acad:
                draw_beam_and_column_details(acad, project, drawing_settings)
        except vkt.errors.WorkerSessionAttachError as err:
            reason = err.reason or "unknown reason"
            if reason == "error_attach_no_instance":
                raise vkt.UserError(
                    "No AutoCAD instance was found on the personal worker. Open the target drawing in AutoCAD, then try again."
                ) from err
            if reason == "error_attach_refused":
                raise vkt.UserError(
                    "AutoCAD was found but refused the connection. Close modal dialogs, finish the current command, and try again."
                ) from err
            raise vkt.UserError(f"Could not attach to AutoCAD ({reason}).") from err
        except vkt.errors.ExecutionError as err:
            raise vkt.UserError(f"AutoCAD reported an error while drawing: {err}") from err
        except vkt.errors.WorkerSessionError as err:
            raise vkt.UserError(
                "The AutoCAD connection was lost while drawing. The open drawing may contain a partial result."
            ) from err
        except TimeoutError as err:
            raise vkt.UserError("Drawing in AutoCAD timed out. Wait until AutoCAD is idle and try again.") from err
        except ValueError as err:
            raise vkt.UserError(str(err)) from err

from __future__ import annotations

import logging

import viktor as vkt
from viktor.errors import ExecutionError, WorkerSessionAttachError, WorkerSessionError

from critical_combinations import CriticalCombinationError, select_critical_reactions
from etabs_extraction import extract_reactions_kn_m


logger = logging.getLogger("viktor")


class Parametrization(vkt.Parametrization):
    inputs = vkt.Page(
        "ETABS footing inputs",
        views=["critical_combinations", "support_coordinates"],
    )
    inputs.intro = vkt.Text(
        "# ETABS → footing inputs\n"
        "Open an analyzed ETABS model on the personal worker. The app reads joint reactions and support "
        "coordinates, then selects the maximum-compression service and ultimate row for each support. "
        "Both tables can be downloaded as CSV from the table view."
    )
    inputs.service_case_filters = vkt.TextField(
        "Service combination filters",
        default="SVC, SERVICE",
        description="Comma-separated, case-insensitive text fragments matched against ETABS output-case names.",
        flex=50,
    )
    inputs.ultimate_case_filters = vkt.TextField(
        "Ultimate combination filters",
        default="ULS, ULTIMATE, STRENGTH",
        description="Comma-separated, case-insensitive text fragments matched against ETABS output-case names.",
        flex=50,
    )
    inputs.compression_sign = vkt.OptionField(
        "Compression sign in ETABS FZ",
        options=["Negative FZ", "Positive FZ"],
        default="Negative FZ",
        description="The selected compression reaction is exported as positive P for the footing app.",
        flex=50,
    )
    inputs.column_x_mm = vkt.NumberField(
        "Default column X",
        default=400.0,
        suffix="mm",
        min=1.0,
        description="Applied to every support in the support-node output table.",
        flex=25,
    )
    inputs.column_y_mm = vkt.NumberField(
        "Default column Y",
        default=400.0,
        suffix="mm",
        min=1.0,
        description="Applied to every support in the support-node output table.",
        flex=25,
    )


class Controller(vkt.Controller):
    parametrization = Parametrization(width=50)

    @staticmethod
    def _fetch_reactions() -> dict:
        try:
            with vkt.etabs.attach(timeout=120) as sap:
                logger.info("Attached to the open ETABS model")
                return extract_reactions_kn_m(sap)
        except WorkerSessionAttachError as err:
            reason = getattr(err, "reason", "unknown")
            if reason == "error_attach_no_instance":
                raise vkt.UserError(
                    "No ETABS instance was found on the personal worker. Open the analyzed model in "
                    "ETABS, then try again."
                ) from err
            if reason == "error_attach_refused":
                raise vkt.UserError(
                    "ETABS refused the connection. Close modal dialogs, let ETABS finish its current "
                    "operation, and try again."
                ) from err
            raise vkt.UserError(f"Could not attach to ETABS ({reason}).") from err
        except ExecutionError as err:
            raise vkt.UserError(f"ETABS reported an error while reading results: {err}") from err
        except WorkerSessionError as err:
            raise vkt.UserError(
                "The ETABS connection was lost while reading results. Reopen the model and try again."
            ) from err
        except TimeoutError as err:
            raise vkt.UserError(
                "Reading ETABS results timed out. Let ETABS finish its current work and try again."
            ) from err

    @classmethod
    def _critical_rows(cls, params) -> list[dict]:
        data = cls._fetch_reactions()
        try:
            return select_critical_reactions(
                data["rows"],
                params.inputs.service_case_filters,
                params.inputs.ultimate_case_filters,
                compression_is_negative=params.inputs.compression_sign == "Negative FZ",
            )
        except CriticalCombinationError as exc:
            raise vkt.UserError(str(exc)) from exc

    @vkt.TableView(
        "Critical combinations",
        duration_guess=30,
        update_label="Read from ETABS",
        description="One maximum-compression service and ultimate combination per support, with coordinates.",
    )
    def critical_combinations(self, params, **kwargs):
        critical = self._critical_rows(params)
        rows = [
            [
                row["node_id"],
                row["story"],
                row["label"],
                round(row["x_m"], 4),
                round(row["y_m"], 4),
                round(row["z_m"], 4),
                row["combination"],
                row["limit_state"],
                round(row["p_kn"], 4),
                round(row["mx_knm"], 4),
                round(row["my_knm"], 4),
                row["case_type"],
                row["step_type"],
            ]
            for row in critical
        ]
        return vkt.TableResult(
            rows,
            column_headers=[
                "Node ID",
                "Story",
                "ETABS label",
                "X [m]",
                "Y [m]",
                "Z [m]",
                "Combination",
                "Limit state",
                "P [kN]",
                "Mx [kN·m]",
                "My [kN·m]",
                "Case type",
                "Step type",
            ],
            enable_sorting_and_filtering=True,
        )

    @vkt.TableView(
        "Support nodes",
        duration_guess=30,
        update_label="Read from ETABS",
        description="Columns match the support-node input table in the AutoCAD footing app.",
    )
    def support_coordinates(self, params, **kwargs):
        critical = self._critical_rows(params)
        supports = {}
        for row in critical:
            supports[row["node_id"]] = row
        rows = [
            [
                node_id,
                round(row["x_m"], 4),
                round(row["y_m"], 4),
                round(row["z_m"], 4),
                float(params.inputs.column_x_mm),
                float(params.inputs.column_y_mm),
            ]
            for node_id, row in sorted(supports.items())
        ]
        return vkt.TableResult(
            rows,
            column_headers=["Node ID", "X [m]", "Y [m]", "Z [m]", "Column X [mm]", "Column Y [mm]"],
            enable_sorting_and_filtering=True,
        )

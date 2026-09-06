# VIKTOR AutoCAD Footing Designer

This proof-of-concept app accepts support-node coordinates and service/ultimate reaction combinations, creates preliminary centered isolated-footing designs, shows a grouped VIKTOR TableView, and draws a foundation layout plus unique reinforcement plans into the AutoCAD drawing already open on the user's personal worker.

## Files

- `app.py`: flat VIKTOR parametrization, summary TableView, and AutoCAD action.
- `foundation_design.py`: input validation, footing sizing, preliminary depth/reinforcement checks, and type grouping.
- `autocad_drawing.py`: AutoCAD ActiveX drawing functions using `vkt.autocad.attach()`.
- `tests/test_foundation_design.py`: pure-Python tests for the calculation layer.

## Run

1. Install VIKTOR CLI and create/register the app in the usual way.
2. Run `viktor-cli start` from this folder.
3. In VIKTOR Desktop, add and start a personal AutoCAD worker.
4. Open the target DWG in AutoCAD.
5. Replace the sample tables, review the summary, and press **Calculate and generate AutoCAD drawing**.
6. Download and review the creation log returned by the app.
7. Save the DWG from AutoCAD after reviewing the result.

## Input contract

- `nodes`: one row per support with `node_id`, `x_m`, `y_m`, `z_m`, `column_x_mm`, and `column_y_mm`.
- `reactions`: one row per node and load combination with `limit_state`, `p_kn`, `mx_knm`, and `my_knm`. Keep all force components from the same combination in the same row.
- Positive `P` means compression. The future ETABS reader should normalize the ETABS sign convention before filling this contract.

## Drawing conventions

- ETABS/support coordinates are entered in metres.
- Set **AutoCAD units per metre** to `1000` for a millimetre drawing or `1` for a metre drawing.
- Geometry is appended to model space on layers beginning with `VKT-FDN-`.
- The current version creates one plan for one foundation elevation and rejects overlapping isolated footings.
- The app does not save or return a DWG.
- Use AutoCAD Undo before repeating a run, or remove the `VKT-FDN-*` geometry/layers manually.

## Engineering limits

The calculation module is a preliminary implementation for centered isolated footings. It uses linear corner soil pressures, a service-pressure/full-contact sizing check, conservative ultimate pressure for cantilever flexure and one-way shear, and an ACI-style punching-shear expression for an interior centered column. It does not replace project-specific design under the governing code and geotechnical report.

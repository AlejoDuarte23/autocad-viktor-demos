# ETABS RC Beam and Column Designer → AutoCAD

This is a separate VIKTOR application for reinforced-concrete beams and columns. It does not contain footing, foundation, or slab-foundation design logic.

The app attaches to the ETABS instance already open on the engineer's personal worker, reads concrete frame geometry and selected response-combination forces, performs preliminary beam and column design, shows design tables and two column interaction diagrams, and then draws reinforcement details in the AutoCAD drawing already open on the same worker machine.

## Included files

| File | Responsibility |
| --- | --- |
| `app.py` | Flat VIKTOR parametrization, ETABS import button, views, and AutoCAD action |
| `etabs_reader.py` | Direct CSI OAPI extraction through `vkt.etabs.attach()` |
| `project_design.py` | Input parsing, validation, and project-level calculation |
| `beam_design.py` | Beam flexure, shear, torsion, bar selection, and stirrup zones |
| `column_design.py` | Column layouts, strain-compatibility interaction curves, biaxial check, shear, ties, and slenderness reporting |
| `interaction_diagrams.py` | Combined Plotly P–M2 and P–M3 figure |
| `autocad_common.py` | AutoCAD layers, primitives, dimensions, text, and tables |
| `autocad_drawing.py` | Beam elevations, beam sections, column elevations, column sections, schedules, notes, border, and title block |
| `tests/` | Calculation and fake ETABS/AutoCAD integration tests |

## VIKTOR interface

The input side is intentionally flat. It uses a top `vkt.Text`, ordinary fields, editable `vkt.Table` inputs, one `vkt.SetParamsButton`, and one `vkt.ActionButton`. It does not use `vkt.Section`, `vkt.Step`, `vkt.Page`, or parametrization tabs.

The main workflow is:

1. Open and analyze the intended ETABS model.
2. Keep one ETABS instance open on the machine running VIKTOR Desktop.
3. Set the response-combination, story, and member filters.
4. Press **Read analyzed model from attached ETABS**.
5. Review the imported beam, column, and force tables.
6. Review **Beam design summary**, **Column design summary**, and **Column P–M2 and P–M3 interaction diagrams**.
7. Open the destination drawing in AutoCAD on the same personal-worker machine.
8. Set the AutoCAD units, origin, layer prefix, and drawing limits.
9. Press **Calculate designs and generate AutoCAD drawings**.
10. Review and save the drawing from AutoCAD.

The views calculate from the editable tables each time they are refreshed. The AutoCAD action recalculates from those same tables before drawing, so the view and drawing data use the same calculation path.

## Requirements and configuration

The project requires:

- VIKTOR SDK 14.35.0 or newer within major version 14
- A VIKTOR personal ETABS worker configured as `etabsconnect`
- A VIKTOR personal AutoCAD worker configured as `autocad`
- ETABS and AutoCAD installed, licensed, open, and responsive on the worker machine
- A logged-in interactive Windows desktop session

`requirements.txt`:

```text
viktor>=14.35.0,<15
```

`viktor.config.toml`:

```toml
app_type = "simple"
python_version = "3.12"
registered_name = "etabs-rc-beam-column-designer"

worker_integrations = [
    "etabsconnect",
    "autocad",
]
```

Change `registered_name` when your registered VIKTOR app has a different slug. From the app directory, install and start the app with the current VIKTOR CLI commands used by your development environment.

## ETABS import contract

### Units

The reader temporarily requests `kN_m_C` so coordinates are read in metres, forces in kilonewtons, and moments in kilonewton-metres. The previous display-unit setting is restored after the import when ETABS accepts the restore call.

### Members

The importer reads all frame objects in one `FrameObj.GetAllFrames` call and obtains ETABS labels and stories with `FrameObj.GetLabelNameList`. A frame is classified as a column when:

```text
abs(ΔZ) / frame_length >= column_vertical_ratio
```

The default ratio is `0.75`. Other selected concrete frames are treated as beams.

Supported section shapes:

- Beams: rectangular concrete sections
- Columns: rectangular and circular concrete sections

Unsupported frame sections, non-concrete materials, zero-length objects, circular beams, and objects outside the filters are skipped and reported in the import summary.

### Results

The app reads ETABS response combinations matching the wildcard filter. Use factored strength combinations for this preliminary design routine.

The imported force components remain in ETABS frame local axes:

- Beam flexure: `M3`
- Beam shear: `V2`
- Beam torsion: `T`
- Column interaction: simultaneous `P`, `M2`, and `M3`
- Column shear: `V2` and `V3`

ETABS commonly reports compression as negative frame axial force. With **ETABS P is negative in compression** enabled, column `P` is multiplied by `-1` during import so compression is positive in the app. Beam `P` is retained as reported because this version does not use beam axial force in the beam flexural design.

The app first requests frame forces by ETABS group. When that request is unavailable, it falls back to object-by-object result calls. Beam result stations are reduced to a bounded set while retaining member ends and critical moment, shear, and torsion locations. Column rows retain both member ends and an additional governing row when it occurs between the ends.

The ETABS output case/combination selection is cleared after import. This prevents the app from leaving its strength-combination selection active, but it also means the engineer must reselect ETABS output combinations before using ETABS result displays that depend on the prior selection.

## Beam design implemented

The beam routine provides preliminary ACI-style calculations for:

- minimum longitudinal reinforcement
- singly reinforced rectangular flexural strength
- strain-based flexural strength-reduction factor
- top reinforcement in left, middle, and right regions
- bottom reinforcement in left, middle, and right regions
- one- or two-layer bar placement checks
- concrete shear strength
- minimum and required two-leg stirrup reinforcement
- left support, middle, and right support stirrup zones
- preliminary torsion threshold and closed-stirrup demand
- preliminary longitudinal torsion reinforcement
- flexural, shear, and torsion utilization ratios
- drawing notes and warnings for congestion or unresolved checks

Available longitudinal diameters are 12, 16, 20, 25, and 32 mm. Available stirrup diameters are 8, 10, 12, and 16 mm. Available spacings are 300, 250, 225, 200, 175, 150, 125, 100, and 75 mm.

The drawing uses a user-defined straight-bar extension factor expressed as a multiple of bar diameter. This is a drafting assumption, not a complete development-length calculation.

## Column design implemented

The column routine provides preliminary calculations for:

- rectangular perimeter bar layouts
- circular equally spaced bar layouts
- minimum and maximum gross longitudinal-steel ratios
- strain-compatible nominal and reduced P–M2 interaction envelopes
- strain-compatible nominal and reduced P–M3 interaction envelopes
- demand points for every imported combination and member end
- uniaxial P–M2 and P–M3 utilization
- an approximate biaxial moment interaction at the demand axial load
- axial compression and tension range checks
- preliminary V2 and V3 shear checks
- closed-tie selection and ordinary maximum spacing limits
- end confinement-zone spacing
- member slenderness reporting about both section axes
- warnings for second-order assumptions, congestion, crossties, and imported column torsion

The two diagrams are visual uniaxial sections of the capacity. The column table also reports the combined numerical biaxial utilization. The current routine does not create a three-dimensional P–M2–M3 surface.

## Result views

### Beam design summary

The table reports member identity, section, length, six longitudinal reinforcement regions, three stirrup regions, governing combination and demands, utilization ratios, status, and warnings.

### Column design summary

The table reports member identity, section, selected bars, gross steel ratio, end and middle tie spacing, confinement length, tie legs, shear demand and capacity, governing axial and biaxial demand, slenderness, utilization ratios, status, and warnings.

### Column interaction diagrams

The selected-column field controls one Plotly view containing:

- nominal P–M2 envelope
- reduced design P–M2 envelope
- P–M2 demand points
- nominal P–M3 envelope
- reduced design P–M3 envelope
- P–M3 demand points
- governing demand marker and combination label

## AutoCAD output

The action uses `vkt.autocad.attach()` and draws into the model space of the drawing currently open in AutoCAD. It creates or reuses these prefixed layers:

```text
VKT-RC-BORDER
VKT-RC-OUTLINE
VKT-RC-SUPPORT
VKT-RC-REBAR
VKT-RC-STIRRUP
VKT-RC-TEXT
VKT-RC-DIM
VKT-RC-AUX
```

The prefix is editable. The generated content includes:

- beam longitudinal reinforcement elevations
- left, middle, and right reinforcement notes
- support and span bar lines
- stirrup symbols and spacing zones
- beam support and midspan cross-sections
- column reinforcement elevations
- confinement and middle tie zones
- column cross-sections with longitudinal bars
- beam and column reinforcement schedules
- general notes
- optional border and title block

The app does not save or overwrite the open DWG. Closing the VIKTOR AutoCAD session only detaches; the geometry remains in the drawing. Repeated runs append another drawing set. Use a new origin for a second set, AutoCAD Undo immediately after an unwanted run, or delete the app-owned layers/entities.

## Important engineering limits

This project is a calculation and drafting starter, not a construction-document approval system. The following items require project-specific engineering work before issue:

- governing design-code edition and local amendments
- all strength, service, accidental, and seismic combinations
- beam axial-flexure interaction where axial force is material
- flanged beam action
- deep-beam behavior
- serviceability and deflection
- crack control
- complete shear-torsion interaction limits
- exact development, hook, cutoff, splice, and lap requirements
- beam-column joint design
- strong-column/weak-beam checks
- special moment-frame detailing
- column moment magnification when not already represented by the ETABS analysis
- column crossties and overlapping hoops for multi-face bar layouts
- column torsion
- fire, exposure, durability, and corrosion cover
- openings, embedded items, construction joints, and bar conflicts
- drafting standards, dimensions, bar marks, schedules, and title-block requirements

A licensed structural engineer must review the ETABS model, imported signs and local axes, calculations, reinforcement, and final AutoCAD drawing.

## Testing

Run from the project directory:

```bash
python -m unittest discover -s tests -v
```

The included tests cover calculation validation, beam and column output, non-square interaction-axis behavior, failure reporting, Plotly output, fake ETABS result extraction, fake AutoCAD entity creation, repeated-layer handling, and VIKTOR controller result shapes. The fake integration tests do not replace a live test with the intended ETABS version, AutoCAD version, personal workers, model, and drawing standard.

## References

- VIKTOR ETABS and SAP2000 integration: https://docs.viktor.ai/docs/create-apps/software-integrations/etabs-and-sap2000/
- VIKTOR AutoCAD integration: https://docs.viktor.ai/docs/create-apps/software-integrations/autocad/
- VIKTOR views API: https://docs.viktor.ai/sdk/api/views/
- CSI ETABS Open API help installed with the target ETABS release

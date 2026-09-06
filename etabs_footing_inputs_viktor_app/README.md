# VIKTOR ETABS Footing Inputs

This app attaches to the ETABS instance already open on a personal VIKTOR worker. It reads the Joint Reactions and Point Object Connectivity database tables, exposes support coordinates, and selects one critical service and one critical ultimate reaction per support for the AutoCAD footing app.

## Selection rule

- Response combinations are loaded directly from ETABS; individual load cases are ignored.
- A combination is classified as Ultimate when any absolute load factor is greater than 1.0. Otherwise it is classified as Service.
- The row with the greatest compressive `FZ` is selected for each support and limit state.
- If two rows have the same compression, the larger `sqrt(MX² + MY²)` governs.
- ETABS display units are temporarily changed to kN, m, C for extraction and restored afterward.
- The compression sign is detected from a gravity/dead-load case when available, then compression is exported as positive `P`. `MX` and `MY` retain their ETABS signs.

## Views

- **Critical combinations** includes node ID, ETABS label, story, X/Y/Z coordinates, governing combination, limit state, P, Mx, and My.
- **Support nodes** matches the support-node input columns of the AutoCAD footing app and applies the user-entered default column dimensions.

Both VIKTOR table views provide CSV download.

## Run

1. Install VIKTOR CLI and register the app using `etabs-footing-inputs`.
2. Run `viktor-cli start` from this folder.
3. Start a personal ETABS worker in VIKTOR Desktop.
4. Open an ETABS model and run its analysis.
5. Open either table view and press **Read from ETABS**.

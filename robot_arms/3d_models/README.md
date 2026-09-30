# Mira SG90 Robot Arm — 3D Models

3D-printable parts for the Mira robot arm, designed around SG90 micro servos.

## Files

| File / Folder | Description |
|---|---|
| `sg90_robot_editable.3dm` | Lightweight Rhino 8 hybrid model: one named block per printable part, welded STL bodies, and exact CAD circles/axes/center points for assembly alignment |
| `sg90_robot_editable_report.json` | Per-part validation details, source triangle counts, block origins, and detected cylindrical-feature counts |
| `sg90_robot.step` | Full assembly STEP file (for CAD editing in Fusion 360, FreeCAD, etc.) |
| `stl/` | Individual STL files for 3D printing |
| `print_files/` | Ready-to-print slicer project files (Bambu Lab, etc.) |

> **Note:** The original Rhino source file (`sg90_robot.3dm`, ~197 MB) is excluded from the repo due to size. Contact the project maintainers if you need it.

## Editable Rhino Model

`sg90_robot_editable.3dm` is arranged on a labeled grid rather than at the
original scattered coordinates. Each printable part is a block whose insertion
point is placed at its first detected cylindrical feature center (or at its
bounding-box center when no cylindrical feature was found).

Layer colors in the editable model:

- Gray: faithful printable mesh body
- Magenta: closed outer profile on the minimum extrusion face
- Orange: exact circular rings fitted to cylindrical features
- Cyan: cylinder/hole axes
- Yellow: cylinder/hole centers
- Green: block insertion points

Move and rotate the named block instances to build the assembly. Keep center
object snaps enabled and use the CAD reference layer to align holes and shafts.

For constant-section parts, use the magenta curve with `ExtrudeCrv` and the
extrusion distance stored in the curve's user text. The current profile set
covers the arm brackets, shared gripper/housing brackets, shared gripper bars,
gripper gears, horn base, and robot base cover. Use the orange circles for the
subsequent hole cuts.

## Print Files (Ready to Print)

The `print_files/` folder contains pre-configured slicer projects:

| File | Slicer | Description |
|---|---|---|
| `mira_arm_2x_bambulam_mini.3mf` | Bambu Studio | Full arm print, 2 copies, configured for Bambu Lab A1 Mini |

Open the `.3mf` file directly in [Bambu Studio](https://bambulab.com/en/download/studio) — all print settings, plate layout, and supports are included.

## STL Parts

The `stl/` folder contains all printable parts for the arm assembly, including:

- **Base** — `sg90-robot-base.stl`, `sg90-robot-base-cover.stl`, `sg90-horn-base.stl`
- **Arm brackets** — `sg90-bracket-left/right.stl`, `sg90-housing-bracket-left/right.stl`
- **Arm housings** — `sg90-housing-left/right.stl`
- **Bucket & rail** — `sg90-bucket-and-rail.stl`
- **Gripper** — multiple gripper parts (`sg90-gripper-*.stl`)

## Printing Tips

- Recommended material: **PLA** or **PETG**
- Layer height: **0.2 mm** for structural parts, **0.12 mm** for gears
- Infill: **20–30%** for most parts, **50%+** for gears and load-bearing brackets

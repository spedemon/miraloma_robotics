# Mira SG90 Robot Arm — 3D Models

3D-printable parts for the Mira robot arm, designed around SG90 micro servos.

## Files

| File / Folder | Description |
|---|---|
| `sg90_robot.step` | Full assembly STEP file (for CAD editing in Fusion 360, FreeCAD, etc.) |
| `stl/` | Individual STL files for 3D printing |
| `print_files/` | Ready-to-print slicer project files (Bambu Lab, etc.) |

> **Note:** The original Rhino source file (`sg90_robot.3dm`, ~197 MB) is excluded from the repo due to size. Contact the project maintainers if you need it.

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

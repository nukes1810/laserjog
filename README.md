# LightCut

A laser design app for GRBL and FluidNC controllers (diode or CO2). It runs on Windows, Linux, and macOS.

## Download

Get the latest builds from the **Releases** page:

- `LightCut-Setup.exe`: Windows installer.
- `LightCut-linux-x86_64.tar.gz`: Linux bundle. Extract it, then run `./LightCut/LightCut`.
- `LightCut-macos-arm64.dmg`: macOS app for Apple Silicon Macs. Open the DMG and drag LightCut to Applications.

### macOS first launch

The app isn't signed by Apple yet, so macOS blocks it the first time. Right-click LightCut in Applications, choose **Open**, then click **Open** again. If it still refuses, run `xattr -cr /Applications/LightCut.app` in Terminal once.

## Linux system packages

The Linux bundle includes Qt, but it still needs a few system libraries for the display layer.

- **Debian / Ubuntu:**
  `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libgl1 libegl1 libfontconfig1 libdbus-1-3`
- **Arch:**
  `sudo pacman -S --needed xcb-util-cursor xcb-util-keysyms xcb-util-image xcb-util-renderutil xcb-util-wm libxkbcommon-x11 mesa libglvnd fontconfig dbus`

## Run from source

    pip install -r requirements.txt
    python run_lightcut.py

## Features

**Design**
- Select, move, rectangle, ellipse, line, and text tools
- Import SVG (vector) and PNG, JPG, or BMP images (raster)
- Undo and redo, duplicate, arrow-key nudge, flip horizontal and vertical
- Save and open project files (`.lcproj`)

**Photo engraving**
- Dithering: Atkinson (default, clean skin tones), Floyd-Steinberg, Jarvis, Halftone (for large shapes), and Threshold
- Auto levels, brightness, contrast, gamma, and sharpening
- Negative mode (burns the light areas)
- Line spacing and width, with a preview of what will burn

**Materials and calibration**
- Material presets (birch plywood, MDF, cardboard, acrylic, leather, anodized aluminum, glass, slate)
- Each layer has a material and an operation (Cut or Engrave). The app recommends power, speed, and passes for your laser's output power.
- Calibration burns a 5 x 5 test grid of power and speed. Pick the best square and save it. Your saved settings then replace the estimates for that laser and material.
- Profiles are stored in `~/.lightcut/profiles.json`.

**Camera and AI**
- Scan the bed with a camera. The app finds the sheet, corrects the perspective, and places it as a reference photo.
- AI trace turns a photo into cut paths. It separates the subject from the background with GrabCut.

**Machine**
- Read the firmware version and settings from the controller: max S value, bed travel, and version.
- Frame (laser-off trace of the design's bounding box), Send, and Stop (feed hold and soft reset)
- Export G-code
- Z adjustment axis, and roller on the U axis (Y is locked when the roller is on)

Stock GRBL 1.1 has no U axis. Use firmware that supports one, such as grblHAL or FluidNC.

## Icons

Icons come from [Lucide](https://lucide.dev), licensed under ISC (see `LICENSE-lucide.txt`).

## Building

Pushing to GitHub runs `.github/workflows/build.yml`, which builds the Windows installer, the Linux bundle, and the macOS DMG. Publishing a GitHub Release attaches all three files to it.

## Notes on the estimates

The built-in material values are starting points for a 10 W laser, scaled by output power. Results depend on the laser, lens focus, air assist, and the material batch. Run a calibration before a real job.

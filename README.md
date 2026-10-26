# LightCut

A LightBurn-style laser design app for GRBL lasers (diode or CO2). Available as a desktop app (Windows and Linux) and as a browser app.

## Download

Get the latest builds from the **Releases** page (or the Actions run artifacts):

- `LightCut-Setup.exe`: Windows installer.
- `LightCut-linux-x86_64.tar.gz`: Linux bundle. Extract it, then run `./LightCut/LightCut`.
- `LightCut-macos-arm64.dmg`: macOS app for Apple Silicon Macs. Open the DMG and drag LightCut to Applications.

### macOS first launch

The app isn't signed by Apple yet, so macOS blocks it the first time. Right-click LightCut in Applications, choose **Open**, then click **Open** again. If it still refuses, run `xattr -cr /Applications/LightCut.app` in Terminal once.

## Linux system packages

The Linux bundle includes Qt, but it still needs a few system libraries for the X11 and Wayland display layer.

- **Debian / Ubuntu:**
  `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libgl1 libegl1 libfontconfig1 libdbus-1-3`
- **Arch:**
  `sudo pacman -S --needed xcb-util-cursor xcb-util-keysyms xcb-util-image xcb-util-renderutil xcb-util-wm libxkbcommon-x11 mesa libglvnd fontconfig dbus`

## Run from source

    pip install -r requirements.txt
    python run_lightcut.py

## Browser version

Open `web/index.html` in Chrome or Edge. Laser connection uses the Web Serial API, which needs Chrome or Edge on a desktop computer.

## Features

- Select, move, rectangle, ellipse, line, and text tools
- Import SVG (vector) and PNG/JPG/BMP images (raster)
- Image engraving with Dither or Threshold, Negative (burn light areas), line spacing, and width
- Undo and redo, duplicate, arrow-key nudge, flip horizontal and vertical
- Layers with Line (vector cut) or Fill (hatch) mode, power, speed, passes, Z offset
- Save and open project files (`.lcproj`)
- G-code export and streaming over serial with Stop (feed hold and soft reset)
- Frame: laser-off trace of the design's bounding box

## Machine options

- **Z adjustment axis:** when enabled, each layer moves to its Z offset before cutting.
- **Roller on U axis:** when enabled, the Y axis is locked and the design's vertical position is sent to U as degrees (roller diameter sets the scale). When disabled, U is never commanded.

Stock GRBL 1.1 has no U axis. Use firmware that supports one (for example grblHAL or FluidNC).

## Building

Pushing to GitHub runs `.github/workflows/build.yml`, which builds the Windows installer and the Linux bundle. Creating a GitHub Release attaches both files to it.

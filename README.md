# OBS Controls

Pause and resume OBS keyboard shortcuts while editing scene or source names. Use Command + the backtick/tilde key on Mac or Ctrl + the backtick/tilde key on Windows or the **OBS Controls** dock. The dock shows the current state.

While paused, the reminder appears after a movement key (W/A/S/D or Q/E) is held for about 0.4 seconds or pressed three times within about 0.9 seconds. Shift+C and Shift+F trigger it immediately. A cooldown prevents a stream of reminders. Single movement keystrokes are ignored by the reminder so you can type names.

## Camera compatibility

The auto-tracking toggle and its default VISCA commands were tested with a FoMaKo PTZ camera. Other camera models may require different commands, an address, or a port. The manual-control toast uses the last tracking state confirmed through OBS. Its key trigger has not been verified end to end. The Windows setup has not been tested in OBS.

## Setup

1. Keep this folder in a permanent location. Install Python 3. On Windows, include Tcl/Tk and add Python to PATH. On macOS, install the Xcode Command Line Tools for the toast build.
2. Run **Setup-Mac.command** or **Setup-Windows.cmd**. The Mac setup builds the toast. Both open the script folder and print the OBS setup steps.
3. In **OBS → Tools → Scripts**, add **obs-hotkey-toggle.lua**. If upgrading, remove the older copy before loading this one.
4. Under **Docks → Custom Browser Docks**, add **OBS Controls** with the URL `http://127.0.0.1:46642/`. The dock is served only on this computer while the Lua script runs.

OBS must already have the camera, scene, and transition shortcuts assigned. The pause uses OBS's keyboard polling control. Depending on OBS version and focused widget, shortcuts injected directly by OBS can still fire. Confirm behavior with your scene collection before relying on it during a production.

## Included files

- **obs-hotkey-toggle.lua** provides the toggle, reminder detection, and dock connection.
- **hotkey-dock.py** and **hotkey-toast.py** provide the local dock and Windows toast.
- **tracking-toast.swift** builds the macOS toast.
- **fomako-tracking.lua** is the optional FoMaKo tracking script. Configure your camera in Tools → Scripts. Use Command+1 on Mac or Control+1 on Windows to toggle tracking. The first press after loading requests On, then each press alternates based on the last camera confirmation. If tracking was changed outside OBS, use the explicit On or Off button to sync the script.
- **obs-hotkeys.html** and **obs-hotkeys-dock-url.txt** are the shortcut reference for the original TLMC setup.

The Windows path has not been tested in a running OBS installation. The separate OBS-MCP installation is an upstream project and isn't required for this package.

When OBS has confirmed tracking is on, pressing WASD or Q/E shows a reminder to toggle tracking off before using manual camera controls.

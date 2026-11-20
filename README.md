# OBS Control Toolkit

One folder for OBS shortcut controls, FoMaKo tracking, and Video Rundown. The rundown includes a media library, Cue and On Air previews, playlist controls, playback history, CSV reports, and SQLite snapshots.

## Setup

1. Extract the **OBS-Controls** folder to a permanent location. Install Python 3.10 or newer. On Windows, include Tcl/Tk and add Python to PATH. The optional macOS toast uses the Xcode Command Line Tools.
2. Run **Setup-Mac.command** or **Setup-Windows.cmd**. The same launcher starts Video Rundown on subsequent runs. Keep its window open while using the rundown docks.
3. In **OBS → Tools → Scripts**, add `outputs/obs-hotkey-toggle.lua`. To use camera tracking, also add `outputs/fomako-tracking.lua` and enter your camera's IP address. If upgrading, remove the old script entries before loading the copies from this folder.
4. In **OBS → Tools → WebSocket Server Settings**, enable the password-protected server for Video Rundown. The launcher reads the existing local OBS settings.
5. In **Docks → Custom Browser Docks**, add the docks you want:

| Dock | URL |
| --- | --- |
| OBS Controls | `http://127.0.0.1:46642/` |
| Video Rundown | `http://127.0.0.1:46643/` |
| Rundown Preview | `http://127.0.0.1:46643/preview` |
| Production Clock | `http://127.0.0.1:46643/clock` |

6. In Video Rundown, click **Set up scene** if shown. Import videos into **File Library**, then add them to **Playlist**.

See the [Video Rundown guide](video-rundown/README.md) for the playlist, Cue, Program playback, and backups. The bundled [hotkey guide](outputs/obs-hotkeys.html) reflects the original TLMC bindings.

## Shortcuts and camera compatibility

- **Command + backtick** on Mac or **Ctrl + backtick** on Windows pauses or resumes OBS shortcuts. You can also use the OBS Controls dock.
- **Command + 1** on Mac or **Ctrl + 1** on Windows toggles tracking. The first press after loading requests On. After that it uses the last camera-confirmed state.
- Tracking and its default VISCA commands were tested with a **FoMaKo PTZ camera**. Other cameras may require different commands, an address, or a port. The movement-key tracking reminder has not been verified end to end. Windows setup has not been tested in OBS.

## Moving an existing rundown

Stop the old rundown launcher before starting the combined one. To keep your existing library, playlist, history, and reports, copy the old rundown's `video-cache` and `backups` folders into `video-rundown/` before launching. Keep their names. The included ZIP contains setup and source files. Sample media and existing backups are kept separately.

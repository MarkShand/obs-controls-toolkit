# OBS Control Toolkit

OBS shortcut controls, FoMaKo camera tracking, and a Video Rundown with a media library, Cue and On Air previews, playback history, CSV reports, and JSON backups.

## Set up once

1. Install **OBS Studio 31 or newer**. Open OBS once to create its settings, then quit OBS.
2. Extract the toolkit to a folder you plan to keep, such as Documents. Double-click the setup file for your computer.

   | Computer | Setup file |
   | --- | --- |
   | Windows | `Setup-Windows.cmd` |
   | Mac | `Setup-Mac.command` |

3. Follow the prompts. On Windows, Setup uses an existing Python 3.10 or newer with Tcl/Tk when available. Otherwise it downloads and installs 64-bit Python with Tcl/Tk for your Windows user. On Mac, install Python 3.10 or newer before running Setup. Enter your FoMaKo camera's IPv4 address if you use tracking. Press Enter to skip it or keep your existing camera settings.
4. When Setup finishes, open OBS. Choose **Docks → Video Rundown** and click **Set up scene** once per scene collection you use. If the dock offers **Use existing scene**, confirm only if the existing scene and player are your rundown pair. Import clips into **File Library**, then add them to **Playlist**.

Setup adds **OBS Controls**, **Video Rundown**, **Rundown Preview**, and **Production Clock** to the Docks menu. It adds toolkit script registrations to existing scene collections and preserves other scripts and dock entries. An enabled OBS WebSocket keeps its current port, password, and authentication settings. If WebSocket already exists and is disabled, Setup asks before enabling it with password protection. The dock services start when OBS loads the toolkit script and stop when it unloads. You can close Setup after installation.

Internet access is needed on the first run to download Python packages. If Finder will not open the Mac launcher, open Terminal in the extracted toolkit folder and run `bash ./Setup-Mac.command`. Mac notification popups use the optional Xcode Command Line Tools. Install those tools and rerun Setup if you want the popups.

## Using the toolkit

- **Windows Ctrl + backtick** or **Mac Command + backtick** pauses or resumes shortcuts. The **OBS Controls** dock also has a toggle.
- **Windows Ctrl + 1** or **Mac Command + 1** toggles FoMaKo tracking when configured. The first press after loading requests On. Subsequent presses use the last camera-confirmed state.
- To change a camera's IP, port, or VISCA commands, open **Tools → Scripts** and select **fomako-tracking.lua**. The default commands are for FoMaKo cameras. Other models may use different commands.
- The [Video Rundown guide](video-rundown/README.md) explains Cue, Program playback, and backups. The [hotkey guide](outputs/obs-hotkeys.html) shows the original TLMC bindings.

## Updating or moving the toolkit

Quit OBS and stop any old Video Rundown launcher before upgrading. To keep an existing library, playlist, history, and reports, preserve or copy the `video-rundown/video-cache` and `video-rundown/backups` folders into the updated toolkit before opening OBS. Run Setup again after updating the toolkit or creating a new scene collection. Before moving the toolkit, run Uninstall from its original folder, then run Setup at the new location. Setup reuses existing dock URLs and updates toolkit script settings only for its own script paths.

Setup stores backups of any changed OBS settings under `toolkit-setup-backups` in the OBS configuration folder. If a dock reports a connection error after startup, wait a moment and refresh it. If the error persists, open `tracking-runtime/toolkit.log` in the toolkit folder and check the OBS script log under **Tools → Scripts**. For a custom OBS configuration folder, pass `--obs-config` with its path to Setup. Use `--active-only` to register scripts only in the last active scene collection. In unattended setup, pass `--enable-websocket` to enable an existing disabled WebSocket configuration with password protection.

## Uninstall

Quit OBS completely. From the folder used for Setup, run **Uninstall-Windows.cmd** on Windows or **Uninstall-Mac.command** on macOS. From PowerShell or Terminal, preview the changes first if you wish.

- Windows PowerShell — `.\Uninstall-Windows.cmd --dry-run`
- macOS Terminal — `bash ./Uninstall-Mac.command --dry-run`

Uninstall removes the toolkit's script registrations and the docks identified by its installation record or earlier setup backups. It backs up the settings files it edits under `toolkit-setup-backups`. OBS scenes, media sources, profiles, other docks and scripts, and WebSocket settings stay in place. The toolkit folder, playlist, library, and media stay on disk.

If a dock from an older or manual install remains, use **Docks → Custom Browser Docks** to remove that entry. If you want to remove the **Video Rundown** scene or **Rundown Player** source, do so in OBS after checking where they are used. Uninstall uses an existing Python installation and runs without downloading dependencies.

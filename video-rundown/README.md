# OBS Video Rundown

A commercial-style video playlist for OBS Studio. Drop clips into a numbered rundown, cue them in a second dock, and play them through the native OBS **Rundown Player** Media Source. The playback clock shows elapsed, duration, and remaining time as `MM:SS.mmm`. Its display interpolates between OBS readings.

## Setup

1. Install Python 3.10 or newer. In OBS, enable the password-protected WebSocket server under **Tools → WebSocket Server Settings**.
2. Run **Setup-Mac.command** or **Setup-Windows.cmd** from the main toolkit folder and leave its window open. The launcher installs the Python dependency in a local virtual environment. The app reads the OBS WebSocket settings on the same computer. Set `OBS_PORT` and `OBS_PASSWORD` before starting if you use a custom OBS config directory.
3. In **Docks → Custom Browser Docks**, add **Video Rundown** at `http://127.0.0.1:46643/` and **Rundown Preview** at `http://127.0.0.1:46643/preview`.
4. Click **Set up scene** in Video Rundown. This creates a **Video Rundown** scene and fits its **Rundown Player** source to the canvas. Move the scene to **Program** when ready to air a clip.

## Running a break

- The File Library, categories, Removed Videos, remaining Playlist, and Auto-advance and Auto-cut settings are saved locally. Playback history is saved after each logged clip and survives OBS, rundown app, and computer restarts. Use **Played on** to filter History by local date. CSV and SQLite exports are saved separately and survive a computer restart.

- Open a clip’s **⋯** menu and choose **Add to Category**. Type a new name or select an existing one. The **Categories** tab groups clips for preview and playlist use. **Remove from Category** removes only that grouping.

- In **File Library**, **Remove** moves a clip to **Removed Videos** once it is out of the Playlist. In **Removed Videos**, use **Rename**, **Restore**, or **Move to Trash**. Move to Trash sends the OBS-managed copy to macOS Trash or the Windows Recycle Bin. The original file you imported stays in its original location.

- Drop one or more files into Video Rundown or use **Add files**. The dock copies them to a local cache on this computer. The originals stay where they are. Clips are limited to 4 GB each, and the queue persists across restarts.
- Click a row to select it and start its muted Cue preview. In **File Library**, click **Rename** to set a title for that file. Existing and future playlist entries use the library title. The **Cue** tab lets you play, scrub, and unmute a local preview independently of Program. The **On Air** tab shows a silent, periodically refreshed image from the OBS Media Source. Scrub the On Air timeline to seek the Program clip while it is playing or paused.
- Click **Play selected** or **Play next**. Use **Pause**, **Resume**, or **Stop** from the dock. Turn on **Auto-advance** to start playback when Video Rundown goes to Program and continue through the pending clips. It starts with the re-cued clip or the first unplayed entry. If the rundown is already on Program, use **Play next** or take it off Program and back on. Playback stops if you take the rundown scene off Program. Auto-advance starts off each time you launch the app.
- Drag the ☰ handle to reorder clips. With the handle focused, Up and Down also move the clip. The clip on Program has a red ON AIR accent and is locked against removal and reordering. The accent follows playback when Auto-advance starts the next clip. Removing a row also deletes its cached copy. Use the OBS mixer to set the player's Program audio level.

The dock accepts the video extensions listed for [OBS Media Source](https://obsproject.com/kb/media-sources): MP4, TS, MOV, FLV, MKV, AVI, GIF, and WebM. Playback depends on the codec inside each file. Cue preview uses the browser's decoder, so OBS may play a clip that Cue cannot preview. The On Air view uses frames from OBS itself.

The dock server listens on this computer only. The cache and virtual environment are excluded from Git. Keep this folder together when adding it to the toolkit.

## Playlist, library, and history

- Import files into **File Library**. Drag a library row onto the **Playlist** tab to add it. **+ Playlist** adds it to the end. An in-dock toast confirms each addition from File Library. The same file can appear more than once, and removing a playlist entry leaves the library copy available.
- The Playlist shows estimated airtimes in local AM/PM time. While idle the estimates roll forward with the clock. During playback the projected times are anchored to the current clip. Pausing lets the remaining estimates slide forward until you resume. When a duration is unavailable, later airtimes wait for OBS or the preview decoder to determine it.
- Right-click a playlist clip and select **Insert Stop & Re-cue below**. When the clip above the marker finishes, the marker is consumed and Auto-advance holds. The next video is cued. **Play next** or a new transition to Program with Auto-advance on resumes playback. Completed videos leave the playlist, remain in File Library, and are recorded in History.
- **History** records actual start and end times for playback seen on Program. **Export CSV** includes timestamps with local UTC offsets and the playback result.

## Return to OBS Preview after playback

Enable OBS Studio Mode and select the return scene in OBS Preview. Set **Auto-cut to Preview** to **Off**, **After current clip**, or **After all clips**. After current clip takes priority over Auto-advance. After all clips waits for the last pending clip, and Auto-advance can play those entries without manual intervention. With Auto-cut off, **Cut to Preview** is available after playback. Stopping a clip does not trigger a cut.

## Exports and backups

In **History**, use **Save CSV**. The file is written directly to the local `backups` folder, so OBS does not have to handle a browser download. In **Backups**, copy the displayed folder path to open it in Finder or Explorer. **Create SQLite backup** saves a timestamped snapshot with tables for the playlist, library, history, and rundown options. Keep the media cache separately if you need the video files. The dock creates backups and reports their location. Use **Restore** beside a SQLite snapshot, or **Restore from file** to import one from another computer. Restore replaces the current rundown data and saves a safety snapshot when existing data is present. For the fastest transfer, copy the source installation’s cached video files into the destination’s `video-cache` folder. If files are missing, use **Search Missing Files** to select a folder containing the original videos, or **Locate** to reconnect individual clips.

## Production Clock

Add **Production Clock** as a Custom Browser Dock at `http://127.0.0.1:46643/clock`. It shows your computer’s local time as `HH:MM:SS.mmm AM/PM` and the date. Expand **Colors** to change the digits and background. The display refreshes with the dock and uses the system clock.

# OBS Video Rundown

A commercial-style video playlist for OBS Studio. Drop clips into a numbered rundown, cue them in a second dock, and play them through the native OBS **Rundown Player** Media Source. The playback clock shows elapsed, duration, and remaining time as `MM:SS.mmm`. Its display interpolates between OBS readings.

## Setup

1. Follow the [toolkit setup](../README.md#set-up-once) with OBS closed.
2. Open OBS and choose **Video Rundown** or **Rundown Preview** from the **Docks** menu.
3. Click **Set up scene** when prompted. This creates a **Video Rundown** scene and fits its **Rundown Player** source to the canvas. If the dock offers **Use existing scene**, confirm only if those are your existing rundown scene and player. Their layout is preserved. Move the scene to **Program** when ready to air a clip.

## Running a break

- The File Library, favorite folders, Removed Videos, remaining Playlist, and Auto-advance and Auto-cut settings are saved locally. Playback history is saved after each logged clip and survives OBS, rundown app, and computer restarts. Use **Played on** to filter History by local date. CSV exports and JSON backups are saved separately and survive a computer restart.

- In **File Library**, **Remove** moves a clip to **Removed Videos** once it is out of the Playlist. In **Removed Videos**, each clip shows its file path. Search by filename or path, restore clips individually, or use **Select all** and **Restore selected** for a batch. **Forget library entry** clears the record. The file stays on its drive.

- To link an existing video collection, open **File Library → Link folder**. The system folder picker opens directly. Dropping a folder onto the dock also opens the picker so you can select the folder from disk.
- The scan includes nested folders. The files stay on their original drive, and linking has no per-file upload limit. Linking the same folder again refreshes its entries by path.
- The scan opens and decodes an initial frame from each candidate video. Files with known but unsupported video extensions, corrupt files, and files without a decodable video stream are labeled **Unsupported** and cannot be cued or played. Keep the source drive connected. Use **Backups → Locate** to reconnect a linked file that was moved.
- Use **Link file** to select an original, such as a video in Downloads. Dropping a file on the dock opens the system file picker because the dock does not receive its absolute source path.
- Click a row to select it and start its muted Cue preview. The **Cue** tab lets you play, scrub, and unmute a local preview independently of Program. In **On Air**, **Low FPS** shows silent OBS source snapshots. **Smooth + audio** plays the current clip in the browser and follows OBS’s playhead. Click **Unmute On Air** to hear the clip audio. This plays the clip audio and picture before OBS applies its mix or filters. If the browser cannot decode a clip, the preview falls back to snapshots. Scrub the local On Air timeline to seek the Program clip while it is playing or paused.
- Click **Play selected** or **Play next**. Use **Pause**, **Resume**, or **Stop** from the dock. Turn on **Auto-advance** to start playback when Video Rundown goes to Program and continue through the pending clips. It starts with the re-cued clip or the first unplayed entry. If the rundown is already on Program, use **Play next**. Auto-advance starts off each time you launch the app.
- In the Playback card, **When Rundown returns** controls what happens to a clip interrupted by a cut. **Restart clip** starts it from the beginning. **Continue where it left off** resumes the paused clip. With Auto-advance off, press **Play next** when the rundown returns to Program. With Auto-advance on, returning to Program starts the clip automatically. After restarting OBS, press Play to begin a new session. If updating an existing installation, close OBS and run Setup once to clear the last media path saved by an older version of Rundown Player.
- Drag the ☰ handle to reorder clips. With the handle focused, Up and Down also move the clip. The clip on Program has a red ON AIR accent and is locked against removal and reordering. The accent follows playback when Auto-advance starts the next clip. Removing a row leaves its File Library entry available. Use the OBS mixer to set the player's Program audio level.

The dock accepts the video extensions listed for [OBS Media Source](https://obsproject.com/kb/media-sources): MP4, TS, MOV, FLV, MKV, AVI, GIF, and WebM. Playback depends on the codec inside each file. Cue preview uses the browser's decoder, so OBS may play a clip that Cue cannot preview. The On Air view uses frames from OBS itself.

The OBS control docks listen on this computer only. The cache and virtual environment are excluded from Git. Keep this folder together when adding it to the toolkit.

## LAN monitor

1. On the OBS computer, open **Rundown Preview → LAN monitor**.
2. Select **Enable monitor** to use the suggested address. If you have more than one network adapter, choose the address on the same network as the other computer. You can also enter an address manually.
3. Open the displayed address in a browser on the other computer. Use `rundown` as the username and enter the four-character **Access code** shown in the dock as the password. The monitor uses TCP port `46644`.

**Cue** follows the local Rundown Preview dock’s selected clip, playback position, play/pause, and seeks. Leave that dock open in **Cue** to share its playback. **On Air** offers **Low FPS** snapshots and **Smooth + audio**. Smooth playback uses the original clip over the LAN and starts muted. Playback can differ slightly because of network and browser buffering, and the remote browser must support the clip’s codec. Use **Fullscreen** for either view. Both views are read-only.

The monitor is off by default. Use it on a trusted private network. Its HTTP connection does not encrypt credentials or video. After five incorrect codes from the same device, the monitor limits further attempts for up to one minute. If a firewall blocks it, allow inbound TCP `46644` on the private network for the local subnet. Leave router port forwarding off. **Disable monitor** closes the listener and retires the access code. Enabling it again generates a new code. If the OBS computer’s IP changes, select the new address and enable the monitor again.

## Folder Explorer

Open **Folders** to browse a linked drive. **File Library** shows the full list of linked videos and any older cached clips. Use the arrows beside the dock tabs to scroll when the dock is narrow. If you linked folders before Folder Explorer was added, it reconstructs a browsable folder tree from saved clip paths. Choose **Use this folder** on a saved root to enable scanning and folder renaming. This registers the root without re-importing clips. If the suggested root differs from the collection you want to manage, use **Link folder** to select the exact root.

Choose a root and open a subfolder to see its direct clips. At the root, **Unlink folder** clears the folder and its library links while keeping clips still covered by another linked root. Files stay on disk, and clips in the Playlist must be removed from it before unlinking. **Link folder** scans the collection again, and **Use this folder** scans a saved folder. Removed Videos contains clips removed individually. The dock remembers this location when you refresh the page. The same preview, playlist, copy-path, and clip menu actions work in the folder view. **Refresh folder** scans the current folder and its descendants for new or changed videos. It reuses verification for unchanged files and keeps missing clips in the library. The dock also checks starred folders and the currently browsed linked folder for new folders and videos in the background. It reconnects confidently identified linked files after external moves or renames. Use **Review changes** to review likely matches together. Reconnecting a clip updates the saved link and combines any duplicate library entry while preserving playlist entries.

**Rename folder on drive** renames the selected subfolder in place. The toolkit updates saved clip paths and favorites while keeping playlist entries. It rejects an occupied destination and prevents renaming a folder containing the current Program clip or another linked root. Apps outside Video Rundown may still use the old path.

Click the **Add to Favorites** star on a folder row or next to the current breadcrumb. If a parent folder is already starred, the dock asks before adding the subfolder separately. Expand a favorite to see its clips and nested subfolders in place. Chevrons indicate folders and breadcrumb levels. Search by folder name, path, or clip name. The star button asks for confirmation before removing a favorite. Starred folders are also available as destinations in the move dialog.

Use **⋯ → Move to…** to move the video to a favorite, a linked root, or a folder you pick. Same-drive moves are usually immediate. Between drives, the progress bar tracks the copy to the destination. Video Rundown records the new path before removing the original. **Rename file** changes the filename on disk while keeping its extension. Both actions retain the clip’s playlist entries and refuse to overwrite an existing file or change the current Program clip. If Windows blocks the move because an app has the video open, the dock reports it. macOS can allow a file to be renamed while another app has it open. Close any editor or player using the file before moving it. macOS move and rename operations require a volume that supports exclusive renaming to protect existing files. A clip uploaded as a cached copy is organized from that copy.

## Playlist, library, and history

- Import files into **File Library**. Use **Sort by** to order the File Library by name, modification date, duration, or path. The metadata shows the path to the linked original or cached copy. Use **⋯ → Copy path** to copy the full path. Drag a library row onto the **Playlist** tab to add it. **+ Playlist** adds it to the end. An in-dock toast confirms each addition from File Library. The same file can appear more than once, and removing a playlist entry leaves the library copy available.
- The Playlist shows estimated airtimes in local AM/PM time. While idle the estimates roll forward with the clock. During playback the projected times are anchored to the current clip. Pausing lets the remaining estimates slide forward until you resume. When a duration is unavailable, later airtimes wait for OBS or the preview decoder to determine it.
- Right-click a playlist clip and select **Insert Stop & Re-cue below**. When the clip above the marker finishes, the marker is consumed and Auto-advance holds. The next video is cued. **Play next** or a new transition to Program with Auto-advance on resumes playback. Completed videos leave the playlist, remain in File Library, and are recorded in History.
- **History** records actual start and end times for playback seen on Program. **Export CSV** includes timestamps with local UTC offsets and the playback result.

## Return to OBS Preview after playback

Enable OBS Studio Mode and select the return scene in OBS Preview. Set **Auto-cut to Preview** to **Off**, **After current clip**, or **After all clips**. After current clip takes priority over Auto-advance. After all clips waits for the last pending clip, and Auto-advance can play those entries without manual intervention. **Cut to Preview** can take the rundown off air during playback or after a clip finishes. Stopping a clip does not trigger a cut.

## Exports and backups

In **History**, use **Save CSV**. The file is written directly to the local `backups` folder, so OBS does not have to handle a browser download. In **Backups**, copy the displayed folder path to open it in Finder or Explorer. **Create JSON backup** saves a readable snapshot of the playlist, library, favorites, history, and options. JSON backups include original paths and Folder Explorer roots for linked media. Keep those files accessible at the saved paths and keep the video cache separately for uploaded clips. A backup with linked media requires the original operating system’s path format. Link the videos again when moving them between Windows and macOS. Use **Restore** beside a snapshot or **Restore from file**. Existing SQLite backups can still be restored. Restore replaces the current rundown data and saves a JSON safety snapshot when existing data is present. For older cached clips with missing files, use **Search Missing Files** or **Locate** to link the original. For missing linked clips, **Locate** updates the saved path.

## Production Clock

Choose **Docks → Production Clock**. It shows your computer's local time as `HH:MM:SS.mmm AM/PM` and the date. Expand **Colors** to change the digits and background. The display refreshes with the dock and uses the system clock.

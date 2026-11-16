"""Local OBS video rundown. Install obsws-python before launching."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
import base64
import csv
import errno
from ipaddress import IPv4Address, IPv4Network
import shutil
import io
from datetime import datetime
import mimetypes
import re
import hmac
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import stat
from contextlib import closing, suppress
from collections import Counter, OrderedDict, defaultdict
import math
import threading
import time
import uuid

import obsws_python

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("OBS_TOOLKIT_RUNDOWN_DATA") or ROOT).resolve()
CACHE = DATA / "video-cache"
BACKUPS = DATA / "backups"
HOST = "127.0.0.1:46643"
ORIGIN = "http://" + HOST
SCENE = "Video Rundown"
SOURCE = "Rundown Player"
RUNDOWN_OWNER = "obs_controls_toolkit_rundown"
FORMATS = {".mp4", ".ts", ".mov", ".flv", ".mkv", ".avi", ".gif", ".webm"}
DEMUXERS = {".mp4": "mov", ".mov": "mov", ".ts": "mpegts", ".flv": "flv",
            ".mkv": "matroska", ".webm": "matroska", ".avi": "avi", ".gif": "gif"}
OTHER_VIDEO_FORMATS = {".3gp", ".asf", ".divx", ".dv", ".f4v", ".m2t", ".m2ts", ".m4v",
                       ".mpeg", ".mpg", ".mts", ".mxf", ".ogv", ".rm", ".rmvb", ".vob", ".wmv"}
METADATA_VERSION = 3
FOLDER_PICKER = threading.Lock()
PICKED_BACKUP = {}
BACKUP_EXTENSIONS = {".json", ".sqlite", ".sqlite3", ".db"}
FOLDER_OPERATION = threading.Lock()
TOKEN = secrets.token_hex(32)
LOCK = threading.RLock()
QUEUE = []
LIBRARY = {}
HISTORY = []
HISTORY_FILE = CACHE / "history.json"
LIBRARY_FILE = CACHE / "library.json"
QUEUE_FILE = CACHE / "queue.json"
SETTINGS_FILE = CACHE / "settings.json"
CATEGORIES_FILE = CACHE / "categories.json"
FOLDERS_FILE = CACHE / "folders.json"
FOLDER_RENAME_FILE = CACHE / "folder-rename.json"
FILE_CHANGE_FILE = CACHE / "file-change.json"
FAVORITES_FILE = CACHE / "favorites.json"
LAN_MONITOR_FILE = CACHE / "lan-monitor.json"
LAN_MONITOR_PORT = 46644
LAN_NETWORKS = tuple(map(IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
LAN_CODE_CHARACTERS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
LAN_LOCK = threading.Lock()
lan_monitor = None
lan_monitor_error = ""
cue_clock = {}
preview_frame = None
CATEGORIES = []
FOLDERS = []
FAVORITES = []
FILE_OPERATION = {}
folder_generation = 0
RENAME_SUGGESTIONS = {}
WATCHED_FOLDERS = {}
FAVORITE_TREES = {}
state = dict(ready=False, program=False, current=None, auto=False, auto_cut="off", return_playback="restart",
             preview=None, return_ready=False, status="Idle", cursor=0, duration=0, error="", air_revision=0)
client = None
armed = False
started = 0.0
sampled_at = 0.0
held_path = None


def save_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def save_settings_files(updates):
    originals = {file: file.read_bytes() if file.exists() else None for file, _ in updates}
    saved = []
    try:
        for file, data in updates:
            save_json(file, data)
            saved.append(file)
    except OSError:
        for file in reversed(saved):
            original = originals[file]
            if original is None:
                file.unlink(missing_ok=True)
            else:
                temporary = file.with_suffix(".tmp")
                temporary.write_bytes(original)
                temporary.replace(file)
        raise


def register_categories(names):
    by_name = {name.casefold(): name for name in CATEGORIES}
    for name in names:
        by_name.setdefault(name.casefold(), name)
    updated = list(by_name.values())
    if updated != CATEGORIES:
        save_json(CATEGORIES_FILE, updated)
        CATEGORIES[:] = updated


def save_queue():
    save_json(QUEUE_FILE, [
        clip if clip.get("marker") else dict(clip, path=media_item(clip)["path"])
        for clip in QUEUE
    ])


def find_clip(clip_id):
    item = LIBRARY.get(clip_id)
    active_item = item if item and not item.get("removed") else None
    return next((clip for clip in QUEUE if clip["id"] == clip_id), active_item)


def cue(clip_id):
    state.update(cue=clip_id, cue_revision=state.get("cue_revision", 0) + 1)
    cue_clock.clear()


def clip_title(clip):
    media = media_item(clip)
    return media.get("title") or media["name"]


def restore_preferences_and_history():
    if SETTINGS_FILE.exists():
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if settings.get("auto_cut") in {"off", "clip", "rundown"}:
            state["auto_cut"] = settings["auto_cut"]
        if settings.get("return_playback") == "continue":
            state["return_playback"] = "continue"
    if HISTORY_FILE.exists():
        saved = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        HISTORY.extend(saved if isinstance(saved, list) else saved["entries"])


def log_playback(result):
    clip = find_clip(state["current"])
    if not clip or not state.get("air_started"):
        return
    entry = dict(name=clip_title(clip), started=state["air_started"],
                 ended=time.time(), result=result)
    save_json(HISTORY_FILE, [*HISTORY, entry])
    HISTORY.append(entry)
    state["air_started"] = None


def media_item(clip):
    return LIBRARY.get(clip.get("media_id", clip["id"]), clip)


def file_stamp(path):
    try:
        info = path.stat()
        return [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino] if stat.S_ISREG(info.st_mode) else None
    except OSError:
        return None


def media_status(item):
    if FILE_OPERATION.get("status") == "running" and FILE_OPERATION.get("clip") == item["id"]:
        return "organizing"
    stamp = file_stamp(Path(item["path"]))
    if stamp is None:
        return "missing"
    if item.get("metadata_version") != METADATA_VERSION or item.get("verified_file") != stamp:
        return "checking"
    return "unsupported" if item.get("unsupported") else "ready"


def require_playable(clip):
    item = media_item(clip)
    status = media_status(item)
    if status != "ready":
        raise ValueError({
            "missing": "This video is missing. Reconnect it in Backups.",
            "checking": "This video is awaiting verification.",
            "organizing": "Wait for the file operation to finish.",
            "unsupported": "Unsupported video. " + (item.get("unsupported") or ""),
        }[status])
    return item


def public_clip(clip):
    if clip.get("marker"):
        return dict(id=clip["id"], name="Stop & Re-cue", marker=True)
    item = media_item(clip)
    status = media_status(item)
    return dict(id=clip["id"], name=clip_title(clip), media_id=item["id"],
                duration_ms=item.get("duration_ms", 0), played=clip.get("played", False),
                missing=status == "missing", media_status=status,
                unsupported=item.get("unsupported") if status == "unsupported" else None,
                linked=bool(item.get("linked")))


def public_library_clip(item, *, show_path=False, roots=()):
    clip = dict(public_clip(item), original_name=item["name"], metadata={
                    "format": Path(item["name"]).suffix[1:].upper(),
                    **(item.get("metadata") or {}),
                })
    if show_path:
        clip["file_path"] = item["path"]
        if item.get("linked"):
            parent = Path(item["path"]).parent
            clip["folder_paths"] = {str(root): parent.relative_to(root).parts for root in roots
                                    if parent.is_relative_to(root)}
    return clip


def verify_video(item, stamp):
    import av

    path = Path(item["path"])
    metadata = {"format": path.suffix[1:].upper()}
    duration_ms = 0
    unsupported = None
    try:
        stat = path.stat()
        metadata.update(size_bytes=stat.st_size, modified_at=item.get("source_modified_at", stat.st_mtime),
                        cached_modified=not item.get("linked") and "source_modified_at" not in item)
        if (created_at := getattr(stat, "st_birthtime", None)) is not None:
            metadata["created_at"] = created_at
        demuxer = DEMUXERS.get(path.suffix.lower())
        if not demuxer:
            unsupported = "File extension is outside the supported formats."
        else:
            with path.open("rb") as source, av.open(source, format=demuxer, timeout=5,
                                                     options={"protocol_whitelist": ""}) as media:
                video = next(iter(media.streams.video), None)
                if video is None or next(media.decode(video), None) is None:
                    unsupported = "No decodable video stream was found."
                else:
                    metadata.update(width=video.width, height=video.height,
                                    codec=video.codec_context.name)
                    if video.average_rate:
                        metadata["fps"] = round(float(video.average_rate), 3)
                    if media.duration and media.duration > 0:
                        duration_ms = round(media.duration * 1000 / av.time_base)
    except (OSError, ValueError, OverflowError, av.error.FFmpegError):
        unsupported = "The video could not be opened or decoded."
    return dict(item, metadata=metadata, metadata_version=METADATA_VERSION,
                verified_file=stamp, unsupported=unsupported, duration_ms=duration_ms)


def scan_library_metadata():
    # Folder imports verify their own entries before committing them.
    while True:
        with LOCK:
            pending = [clip for clip in LIBRARY.values() if not clip.get("removed")]
        for item in pending:
            path = Path(item["path"])
            stamp = file_stamp(path)
            if stamp is None:
                continue
            if item.get("metadata_version") == METADATA_VERSION and item.get("verified_file") == stamp:
                continue
            verified = verify_video(item, stamp)
            with LOCK:
                if LIBRARY.get(item["id"]) is item and file_stamp(path) == stamp:
                    record = dict(item, **{key: verified[key] for key in
                                           ("metadata", "metadata_version", "verified_file",
                                            "unsupported", "duration_ms")})
                    updated = {**LIBRARY, item["id"]: record}
                    try:
                        save_json(LIBRARY_FILE, updated)
                    except OSError:
                        continue
                    LIBRARY[item["id"]] = record
        time.sleep(5)


def rename_stamp(item):
    stamp = item.get("verified_file")
    if isinstance(stamp, list) and len(stamp) == 4 and all(type(value) is int for value in stamp):
        return stamp
    return None


def definitely_missing(path):
    try:
        path.stat()
    except FileNotFoundError:
        return True
    except OSError:
        pass
    return False


def rename_signature(path, stamp):
    return path.suffix.lower(), stamp[0], stamp[1]


def same_file_identity(old_path, old_stamp, new_path, new_stamp):
    if not old_stamp[3] or old_stamp[3] != new_stamp[3]:
        return False
    if os.name == "nt":
        return old_path.drive == new_path.drive and old_stamp[2] == new_stamp[2]
    # POSIX inode numbers are unique only within a file system.
    try:
        return old_path.parent.stat().st_dev == new_path.stat().st_dev
    except OSError:
        return False


def find_external_renames(missing, observed=(), known=(), roots=()):
    missing = [item for item in missing if definitely_missing(Path(item["path"]))]
    wanted = {rename_signature(Path(item["path"]), rename_stamp(item)) for item in missing}
    if not wanted:
        return []
    paths = set(observed)
    for item in known:
        stamp = rename_stamp(item)
        path = Path(item["path"])
        if stamp and rename_signature(path, stamp) in wanted:
            paths.add(path)
    for parent in {Path(item["path"]).parent for item in missing}:
        try:
            _, files = directory_inventory(parent, {})
            paths.update(files)
        except OSError:
            continue
    candidates = defaultdict(list)
    for path in paths:
        stamp = file_stamp(path)
        if stamp and not path.is_symlink():
            signature = rename_signature(path, stamp)
            if signature in wanted:
                candidates[signature].append((path, stamp))

    proposed = []
    for item in missing:
        old_path = Path(item["path"])
        old_stamp = rename_stamp(item)
        shared_roots = [root for root in roots if old_path.is_relative_to(root)]
        options = [(path, stamp) for path, stamp in candidates[rename_signature(old_path, old_stamp)]
                   if path.parent == old_path.parent or any(path.is_relative_to(root) for root in shared_roots)]
        exact = [(path, stamp) for path, stamp in options
                 if same_file_identity(old_path, old_stamp, path, stamp)]
        # Size and timestamps alone may identify another copy.
        possible = exact or [(path, stamp) for path, stamp in options if stamp[2] == old_stamp[2]]
        if len(possible) == 1:
            path, stamp = possible[0]
            proposed.append((item, path, stamp, bool(exact)))

    targets = Counter(path for _, path, _, _ in proposed)
    return [(item, path, stamp, exact) for item, path, stamp, exact in proposed if targets[path] == 1]


def current_rename_records(item, path, stamp):
    old = LIBRARY.get(item["id"])
    if not old or old.get("removed") or old["path"] != item["path"] or rename_stamp(old) != rename_stamp(item):
        raise ValueError("The linked clip changed. Wait for the next file check.")
    if not definitely_missing(Path(old["path"])) or path.is_symlink() or file_stamp(path) != stamp:
        raise ValueError("The files changed. Wait for the next file check.")
    matches = [clip for clip in LIBRARY.values() if clip.get("linked") and Path(clip["path"]) == path]
    if len(matches) > 1 or (matches and matches[0].get("removed")):
        raise ValueError("The destination already has conflicting library entries.")
    return old, matches[0] if matches else None


def apply_external_rename(item, path, stamp, *, verified=None):
    old, duplicate = current_rename_records(item, path, stamp)
    duplicate_id = duplicate["id"] if duplicate else None
    current = find_clip(state["current"])
    if current and media_item(current)["id"] in {old["id"], duplicate_id}:
        raise ValueError("Stop the clip on Program before updating its link.")

    record = dict(old, path=str(path), name=path.name)
    if verified is not None:
        for key in ("metadata", "metadata_version", "duration_ms", "unsupported"):
            record[key] = verified[key]
    record["verified_file"] = stamp
    updated = {**LIBRARY, old["id"]: record}
    queue = QUEUE
    if duplicate:
        record["categories"] = list(dict.fromkeys([*old.get("categories", []), *duplicate.get("categories", [])]))
        record["title"] = old.get("title") or duplicate.get("title")
        del updated[duplicate_id]
        queue = [
            dict(row, media_id=old["id"], path=str(path))
            if not row.get("marker") and row.get("media_id", row["id"]) == duplicate_id else row
            for row in QUEUE
        ]
    # Save queue references while both original records still exist on disk.
    files = [(QUEUE_FILE, queue)] if queue != QUEUE else []
    files.append((LIBRARY_FILE, updated))
    save_settings_files(files)
    LIBRARY.clear()
    LIBRARY.update(updated)
    QUEUE[:] = queue
    selected = state.get("cue")
    if duplicate_id and selected == duplicate_id:
        cue(old["id"])
    elif selected and (clip := find_clip(selected)) and media_item(clip)["id"] == old["id"]:
        cue(selected)


def check_external_renames(missing, observed=(), known=(), roots=(), generation=None):
    if not FOLDER_OPERATION.acquire(blocking=False):
        return None
    try:
        candidates = find_external_renames(missing, observed, known, roots)
        with LOCK:
            if generation is not None and generation != folder_generation:
                return None
            suggestions = {}
            for item, path, stamp, exact in candidates:
                try:
                    old, duplicate = current_rename_records(item, path, stamp)
                    distinct_titles = duplicate and old.get("title") and duplicate.get("title") and old["title"] != duplicate["title"]
                    if exact and not distinct_titles and old.get("metadata_version") == METADATA_VERSION:
                        apply_external_rename(item, path, stamp)
                    else:
                        suggestions[old["id"]] = (item, path, stamp)
                except (OSError, ValueError):
                    continue
            RENAME_SUGGESTIONS.clear()
            RENAME_SUGGESTIONS.update(suggestions)
        return {path for _, path, _, _ in candidates}
    finally:
        FOLDER_OPERATION.release()


def confirm_external_rename(clip_id, destination):
    if not isinstance(clip_id, str) or not isinstance(destination, str):
        raise ValueError("Choose a suggested file rename.")
    with FOLDER_OPERATION:
        with LOCK:
            proposal = RENAME_SUGGESTIONS.get(clip_id)
            if not proposal or str(proposal[1]) != destination:
                raise ValueError("The suggested rename changed. Check the library again.")
            item, path, stamp = proposal
            _, duplicate = current_rename_records(item, path, stamp)
        verified = duplicate if duplicate and duplicate.get("verified_file") == stamp and (
            duplicate.get("metadata_version") == METADATA_VERSION
        ) and all(key in duplicate for key in ("metadata", "duration_ms", "unsupported")) else verify_video(dict(item, name=path.name, path=str(path)), stamp)
        with LOCK:
            if RENAME_SUGGESTIONS.get(clip_id) is not proposal:
                raise ValueError("The suggested rename changed. Check the library again.")
            apply_external_rename(item, path, stamp, verified=verified)
            RENAME_SUGGESTIONS.pop(clip_id, None)


def local_path(raw_path):
    if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
        raise ValueError("Choose an absolute file or folder path.")
    if raw_path.startswith(("//./", "//?/", "\\\\.", "\\\\?")):
        raise ValueError("Choose a regular file or folder.")
    return Path(raw_path)


def pick_paths(title, kind, *, multiple=False, initial_folder=None, extensions=None):
    if not FOLDER_PICKER.acquire(blocking=False):
        raise ValueError("A file or folder window is already open.")
    try:
        formats = sorted(extensions if extensions is not None else
                         BACKUP_EXTENSIONS if kind == "backup" else FORMATS | OTHER_VIDEO_FORMATS)
        if os.name == "nt":
            command = ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                       "-File", str(ROOT / "choose_media.ps1"), "-Label", title, "-Kind", kind]
            if multiple:
                command.append("-Multiple")
            if initial_folder:
                command.extend(["-InitialFolder", str(initial_folder)])
            if kind != "folder":
                command.extend(["-Pattern", ";".join("*" + extension for extension in formats)])
            flags = subprocess.CREATE_NO_WINDOW
        elif sys.platform == "darwin":
            script = """function run(args) {
    var app = Application.currentApplication();
    app.includeStandardAdditions = true;
    var multiple = args[2] === "true";
    var options = {withPrompt: args[0], multipleSelectionsAllowed: multiple};
    if (args[3]) options.defaultLocation = Path(args[3]);
    if (args[1] !== "folder") options.ofType = JSON.parse(args[4]);
    var selected = args[1] === "folder" ? app.chooseFolder(options) : app.chooseFile(options);
    return JSON.stringify((multiple ? selected : [selected]).map(function(item) { return String(item); }));
}"""
            command = ["osascript", "-l", "JavaScript", "-e", script, title, kind, str(multiple).lower(),
                       str(initial_folder) if initial_folder else "", json.dumps([ext[1:] for ext in formats])]
            flags = 0
        else:
            raise ValueError("The native media picker is available on Windows and macOS.")
        result = subprocess.run(command, capture_output=True, encoding="utf-8",
                                errors="replace", creationflags=flags, timeout=300)
        if result.returncode:
            if sys.platform == "darwin" and "(-128)" in result.stderr:
                return []
            raise ValueError("The native media picker could not open.")
        paths = json.loads(result.stdout)
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ValueError("The native media picker returned an invalid selection.")
        return paths
    except subprocess.TimeoutExpired as exc:
        raise ValueError("The media picker timed out. Open it again to retry.") from exc
    finally:
        FOLDER_PICKER.release()


def pick_path(title, kind, **options):
    return next(iter(pick_paths(title, kind, **options)), "")


def is_directory_link(path):
    return path.is_symlink() or (
        os.name == "nt" and getattr(path.lstat(), "st_reparse_tag", None) == stat.IO_REPARSE_TAG_MOUNT_POINT
    )


def saved_roots(values):
    if not isinstance(values, list):
        raise ValueError("Invalid linked folder list.")
    roots = []
    for value in values:
        root = local_path(value)
        if ".." in root.parts or root.is_relative_to(CACHE):
            raise ValueError("Invalid linked folder path.")
        if root not in roots:
            roots.append(root)
    return [str(root) for root in roots]


def folder_part(value):
    if not isinstance(value, str) or value in {"", ".", ".."} or any(char in value for char in "/\x00"):
        raise ValueError("Choose a folder inside the linked root.")
    if os.name == "nt":
        if hasattr(os.path, "isreserved"):
            reserved = os.path.isreserved(value)
        else:
            reserved = PureWindowsPath(value).is_reserved()
        if reserved or any(char in value for char in '<>:"\\|?*') or value.endswith((" ", ".")):
            raise ValueError("Enter a valid Windows folder name.")
    return value


def explorer_roots():
    registered = [Path(value) for value in FOLDERS]
    candidates = {}
    for item in LIBRARY.values():
        if not item.get("linked") or item.get("removed"):
            continue
        parent = Path(item["path"]).parent
        if not parent.is_absolute() or ".." in parent.parts or any(parent.is_relative_to(root) for root in registered):
            continue
        names = {name.casefold() for name in item.get("categories", [])}
        candidate = parent
        # Legacy imports assigned the names of each subfolder along the saved path.
        while candidate.parent != Path(candidate.anchor) and candidate.name.casefold() in names:
            candidate = candidate.parent
        candidates.setdefault(candidate, None)
    inferred = []
    for candidate in sorted(candidates, key=lambda path: len(path.parts)):
        if not any(candidate.is_relative_to(root) and root != Path(root.anchor) for root in inferred):
            inferred.append(candidate)
    roots = [*registered, *inferred]
    for value in FAVORITES:
        favorite = Path(value)
        if not any(favorite.is_relative_to(root) for root in roots):
            roots.append(favorite)
    return roots


def reconnect_picked_video(item, source):
    stamp = file_stamp(source)
    if stamp is None or source.is_relative_to(CACHE) or source.suffix.lower() not in FORMATS:
        raise ValueError("Choose an available video outside the rundown cache.")
    replacement = dict(item, path=str(source), name=source.name, linked=True)
    replacement.pop("cache_name", None)
    replacement.pop("source_modified_at", None)
    record = verify_video(replacement, stamp)
    if record["unsupported"]:
        raise ValueError(record["unsupported"])
    with LOCK:
        if LIBRARY.get(item["id"]) is not item or media_status(item) != "missing" or file_stamp(source) != stamp:
            raise ValueError("The clip or selected video changed. Try again.")
        save_json(LIBRARY_FILE, {**LIBRARY, item["id"]: record})
        LIBRARY[item["id"]] = record


def search_missing_folder(value):
    root = local_path(value).resolve()
    with LOCK:
        missing = [item for item in LIBRARY.values() if not item.get("linked") and media_status(item) == "missing"]
    names = {item["name"].casefold() for item in missing}
    matches = {}
    if names:
        for current, dirs, files in os.walk(root):
            parent = Path(current)
            dirs[:] = [name for name in dirs if not is_directory_link(parent / name) and parent / name != CACHE]
            for name in files:
                key = name.casefold()
                if key in names and not (parent / name).is_symlink():
                    matches[key] = None if key in matches else parent / name
    count = failures = 0
    for item in missing:
        source = matches.get(item["name"].casefold())
        if source:
            try:
                reconnect_picked_video(item, source)
                count += 1
            except (OSError, ValueError):
                failures += 1
    return {"count": count, "failures": failures}


def import_backup_payload(payload):
    if not 0 < len(payload) <= 64 * 1024**2:
        raise ValueError("Select a rundown backup up to 64 MB.")
    legacy = payload.startswith(b"SQLite format 3\x00")
    extension = ".sqlite" if legacy else ".json"
    BACKUPS.mkdir(exist_ok=True)
    temporary = BACKUPS / ("restore-" + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(payload)
        with LOCK:
            restore_backup(temporary, legacy=legacy)
            temporary.replace(BACKUPS / ("rundown-imported-" + uuid.uuid4().hex[:12] + extension))
    finally:
        temporary.unlink(missing_ok=True)


def pick_backup():
    path = pick_path("Choose a rundown backup", "backup")
    if not path:
        return {"cancelled": True}
    source = local_path(path).resolve()
    stamp = file_stamp(source)
    if not stamp or not 0 < stamp[0] <= 64 * 1024**2 or source.suffix.lower() not in BACKUP_EXTENSIONS:
        raise ValueError("Select a rundown backup up to 64 MB.")
    selection = uuid.uuid4().hex
    with LOCK:
        PICKED_BACKUP.clear()
        PICKED_BACKUP.update(id=selection, path=source, stamp=stamp)
    return {"id": selection, "name": source.name}


def restore_picked_backup(selection):
    with LOCK:
        if not selection or selection != PICKED_BACKUP.get("id"):
            raise ValueError("Select the backup file again.")
        source, stamp = PICKED_BACKUP["path"], PICKED_BACKUP["stamp"]
        PICKED_BACKUP.clear()
    if file_stamp(source) != stamp:
        raise ValueError("The selected backup changed. Select it again.")
    with source.open("rb") as stream:
        payload = stream.read(64 * 1024**2 + 1)
    if len(payload) != stamp[0] or file_stamp(source) != stamp:
        raise ValueError("The selected backup changed. Select it again.")
    import_backup_payload(payload)


def favorite_entries(roots):
    entries = []
    for value in FAVORITES:
        path = Path(value)
        root = next(root for root in roots if path.is_relative_to(root))
        entries.append(dict(path=value, name=path.name or value, root=str(root), parts=path.relative_to(root).parts,
                            folders=FAVORITE_TREES.get(value, [])))
    return entries


def set_favorite(data):
    with LOCK:
        if data.get("starred") is True:
            root, parts = data.get("root"), data.get("parts")
            if not isinstance(root, str) or not isinstance(parts, list) or Path(root) not in explorer_roots():
                raise ValueError("Choose a folder in Folders.")
            parts = [folder_part(part) for part in parts]
            if root in FOLDERS:
                path = registered_folder(root, parts)
            else:
                saved_folder_listing(root, parts)
                path = Path(root).joinpath(*parts)
            if any(path == Path(value) for value in FAVORITES):
                return {}
            parent = max((Path(value) for value in FAVORITES
                          if path != Path(value) and path.is_relative_to(value)),
                         key=lambda folder: len(folder.parts), default=None)
            if parent is not None and data.get("confirmed_parent") != str(parent):
                return {"parent": {"path": str(parent), "name": parent.name or str(parent)}}
            updated = saved_roots([*FAVORITES, str(path)])
        else:
            path = local_path(data.get("path"))
            updated = [value for value in FAVORITES if Path(value) != path]
        if updated != FAVORITES:
            save_json(FAVORITES_FILE, updated)
            FAVORITES[:] = updated
    return {}


def saved_folder_listing(root, parts):
    folder = Path(root).joinpath(*parts)
    children = set()
    available = not parts
    for item in LIBRARY.values():
        if not item.get("linked") or item.get("removed"):
            continue
        parent = Path(item["path"]).parent
        if parent.is_relative_to(folder):
            available = True
            relative = parent.relative_to(folder).parts
            if relative:
                children.add(relative[0])
    if not available:
        raise ValueError("This folder has no saved library paths.")
    return {"parts": parts, "children": sorted(children, key=str.casefold), "saved_only": True}


def restored_clip(item):
    record = dict(item, removed=False)
    record.pop("unlinked_folder", None)
    return record


def migrate_unlinked_records(library, folders):
    roots = [Path(folder) for folder in folders]
    for clip_id, item in list(library.items()):
        if not item.get("unlinked_folder"):
            continue
        if any(Path(item["path"]).is_relative_to(root) for root in roots):
            library[clip_id] = restored_clip(item)
        else:
            del library[clip_id]


def restore_removed_clips(ids):
    if not isinstance(ids, list) or not ids or any(
        not isinstance(clip_id, str) or not re.fullmatch(r"[a-f0-9]{32}", clip_id) for clip_id in ids
    ):
        raise ValueError("Select removed clips to restore.")
    with LOCK:
        updates = {clip_id: restored_clip(LIBRARY[clip_id]) for clip_id in set(ids)
                   if clip_id in LIBRARY and LIBRARY[clip_id].get("removed")}
        if FILE_OPERATION.get("status") == "running" and FILE_OPERATION.get("clip") in updates:
            raise ValueError("Wait for the file operation to finish before restoring these clips.")
        if updates:
            save_json(LIBRARY_FILE, {**LIBRARY, **updates})
            LIBRARY.update(updates)
    return len(updates)


def register_saved_folder(root):
    with LOCK:
        if not isinstance(root, str) or Path(root) not in explorer_roots():
            raise ValueError("Choose a folder shown in Folder Explorer.")
    return import_folder(root)


def unlink_folder(root):
    global folder_generation
    if not isinstance(root, str):
        raise ValueError("Choose a folder to unlink.")
    folder = local_path(root)
    with FOLDER_OPERATION, LOCK:
        if folder not in explorer_roots():
            raise ValueError("This folder is no longer linked.")
        remaining = [path for path in FOLDERS if Path(path) != folder]
        retained_roots = [Path(path) for path in remaining]
        if not any(folder.is_relative_to(parent) for parent in retained_roots) and any(
            folder != Path(path) and folder.is_relative_to(path) for path in FAVORITES
        ):
            raise ValueError("Unstar the parent folder in Favorites before unlinking this folder.")

        def is_detached(path):
            return path.is_relative_to(folder) and not any(path.is_relative_to(parent) for parent in retained_roots)

        clips = {clip_id for clip_id, item in LIBRARY.items()
                 if item.get("linked") and not item.get("removed") and is_detached(Path(item["path"]))}
        if any(not row.get("marker") and row.get("media_id", row["id"]) in clips for row in QUEUE):
            raise ValueError("Remove this folder’s clips from the Playlist before unlinking it.")
        if FILE_OPERATION.get("status") == "running" and FILE_OPERATION.get("clip") in clips:
            raise ValueError("Wait for the file operation to finish before unlinking this folder.")

        favorites = [path for path in FAVORITES if not is_detached(Path(path))]
        updated = {clip_id: item for clip_id, item in LIBRARY.items() if clip_id not in clips}
        changes = [(file, value) for file, value, previous in (
            (FOLDERS_FILE, remaining, FOLDERS),
            (FAVORITES_FILE, favorites, FAVORITES),
            (LIBRARY_FILE, updated, LIBRARY),
        ) if value != previous]
        save_settings_files(changes)
        unstarred = len(FAVORITES) - len(favorites)
        FOLDERS[:] = remaining
        FAVORITES[:] = favorites
        for clip_id in clips:
            del LIBRARY[clip_id]
        folder_generation += 1
        for path in list(WATCHED_FOLDERS):
            if is_detached(path):
                del WATCHED_FOLDERS[path]
        for path in list(FAVORITE_TREES):
            if path not in FAVORITES:
                del FAVORITE_TREES[path]
        for clip_id, (_, target, _) in list(RENAME_SUGGESTIONS.items()):
            if clip_id in clips or is_detached(target):
                del RENAME_SUGGESTIONS[clip_id]
        if state.get("cue") in clips:
            cue(None)
        return {"removed": len(clips), "unstarred": unstarred}


def registered_folder(root, parts):
    if not isinstance(root, str) or root not in FOLDERS or not isinstance(parts, list):
        raise ValueError("Select a linked folder.")
    folder = Path(root)
    try:
        if not folder.is_dir() or folder.resolve() != folder:
            raise ValueError("The linked folder is unavailable. Check its drive and saved path.")
        for part in parts:
            folder /= folder_part(part)
            if folder.is_relative_to(CACHE) or is_directory_link(folder) or not folder.is_dir():
                raise ValueError("This subfolder is unavailable.")
    except OSError as exc:
        raise ValueError("The folder is unavailable or could not be accessed.") from exc
    return folder


def browse_folder(root, parts):
    if not isinstance(root, str) or not isinstance(parts, list):
        raise ValueError("Select a linked folder.")
    parts = [folder_part(part) for part in parts]
    with LOCK:
        if root not in FOLDERS:
            if Path(root) not in explorer_roots():
                raise ValueError("Select a linked folder.")
            return saved_folder_listing(root, parts)
        generation = folder_generation
    try:
        folder = registered_folder(root, parts)
        names = [child.name for child in folder.iterdir()
                 if child != CACHE and child.is_dir() and not is_directory_link(child)]
    except (OSError, ValueError):
        with LOCK:
            listing = saved_folder_listing(root, parts)
        listing["warning"] = "The drive folder is unavailable. Showing saved library paths."
        return listing
    with LOCK:
        if generation == folder_generation and root in FOLDERS:
            WATCHED_FOLDERS[folder] = time.monotonic()
    return {"parts": folder.relative_to(root).parts, "children": sorted(names, key=str.casefold)}


def directory_inventory(folder, cache, *, force=False):
    if folder.is_relative_to(CACHE) or is_directory_link(folder):
        return (), ()
    stat = folder.stat()
    stamp = (stat.st_mtime_ns, stat.st_ino)
    previous = cache.get(folder)
    moment = time.monotonic()
    if not force and previous and previous[0] == stamp and moment - previous[3] < 5:
        return previous[1], previous[2]
    children, files = [], []
    with os.scandir(folder) as entries:
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False) and not is_directory_link(path) and path != CACHE:
                    children.append(path)
                elif path.suffix.lower() in FORMATS | OTHER_VIDEO_FORMATS and entry.is_file(follow_symlinks=False):
                    files.append(path)
            except OSError:
                continue
    cache[folder] = (stamp, tuple(children), tuple(files), moment)
    return cache[folder][1], cache[folder][2]


def discover_watched_folders(favorites, watched, cache):
    trees, observed, visited = {}, set(), set()
    for root in favorites:
        pending = [root]
        branches = []
        while pending:
            folder = pending.pop()
            try:
                children, files = directory_inventory(folder, cache, force=folder == root)
            except OSError:
                continue
            visited.add(folder)
            if folder != root:
                branches.append(folder.relative_to(root).parts)
            pending.extend(children)
            observed.update(files)
        if root in visited:
            trees[str(root)] = sorted(branches, key=lambda parts: tuple(part.casefold() for part in parts))
    for folder in watched:
        if folder in visited:
            continue
        try:
            children, files = directory_inventory(folder, cache, force=True)
            visited.add(folder)
            observed.update(files)
            # Look in immediate subfolders for a file moved out of the open folder.
            for child in children:
                if child not in visited:
                    try:
                        _, files = directory_inventory(child, cache)
                        visited.add(child)
                        observed.update(files)
                    except OSError:
                        continue
        except OSError:
            continue
    for folder in cache.keys() - visited:
        del cache[folder]
    return trees, observed


def add_watched_clips(paths, pending, generation):
    if not FOLDER_OPERATION.acquire(blocking=False):
        return
    try:
        with LOCK:
            if generation != folder_generation:
                return
            known = {Path(item["path"]) for item in LIBRARY.values() if item.get("linked")}
        candidates = paths - known
        ready = {}
        next_pending = {}
        for path in sorted(candidates):
            stamp = file_stamp(path)
            if not stamp or path.is_symlink():
                continue
            if pending.get(path) != stamp or len(ready) >= 6:
                # Wait for stable copies and bound each automatic verification batch.
                next_pending[path] = stamp
                continue
            clip_id = uuid.uuid4().hex
            ready[clip_id] = verify_video(dict(id=clip_id, name=path.name, path=str(path), linked=True), stamp)
        with LOCK:
            if generation != folder_generation:
                return
            unchanged = {key: item for key, item in ready.items()
                         if file_stamp(Path(item["path"])) == item["verified_file"]}
            if unchanged:
                save_json(LIBRARY_FILE, {**LIBRARY, **unchanged})
                LIBRARY.update(unchanged)
        pending.clear()
        pending.update(next_pending)
    finally:
        FOLDER_OPERATION.release()


def watch_folder_changes():
    cache, pending = {}, {}
    while True:
        try:
            with LOCK:
                generation = folder_generation
                favorites = [Path(path) for path in FAVORITES]
                cutoff = time.monotonic() - 15
                for path in list(WATCHED_FOLDERS):
                    if WATCHED_FOLDERS[path] < cutoff:
                        del WATCHED_FOLDERS[path]
                watched = list(WATCHED_FOLDERS)
                known = [item for item in LIBRARY.values() if item.get("linked")]
                roots = {Path(root) for root in FOLDERS} | set(favorites)
            trees, observed = discover_watched_folders(favorites, watched, cache)
            with LOCK:
                if generation != folder_generation:
                    continue
                FAVORITE_TREES.clear()
                FAVORITE_TREES.update(trees)
            missing = [item for item in known if not item.get("removed") and rename_stamp(item)
                       and file_stamp(Path(item["path"])) is None]
            held = check_external_renames(missing, observed, known, roots, generation)
            if held is not None:
                add_watched_clips(observed - held, pending, generation)
        except (OSError, ValueError):
            pass
        finally:
            time.sleep(2)


def import_folder(root, *, parts=None):
    with FOLDER_OPERATION:
        return scan_linked_folder(root, parts)


def scan_linked_folder(root, parts):
    if parts is None:
        folder = local_path(root).resolve()
        if not folder.is_dir() or folder.is_relative_to(CACHE):
            raise ValueError("Choose a video folder outside the rundown cache.")
    else:
        folder = registered_folder(root, parts)
    with LOCK:
        if not recover_folder_rename():
            raise ValueError("Reconnect the drive to finish recovering the previous folder rename.")
        generation = folder_generation
        if parts is None:
            root = next((item for item in FOLDERS if Path(item) == folder), str(folder))
        elif root not in FOLDERS:
            raise ValueError("The linked folders changed. Open Folder Explorer again.")
        known = {os.path.normcase(item["path"]): item for item in LIBRARY.values() if item.get("linked")}

    discovered = []

    def scan_error(exc):
        raise ValueError(f"Could not read folder: {exc.filename}") from exc

    for current, dirs, names in os.walk(folder, onerror=scan_error):
        parent = Path(current)
        dirs[:] = sorted(name for name in dirs if not is_directory_link(parent / name) and parent / name != CACHE)
        for name in sorted(names):
            path = parent / name
            if path.suffix.lower() not in FORMATS | OTHER_VIDEO_FORMATS or path.is_symlink():
                continue
            key = os.path.normcase(str(path))
            stamp = file_stamp(path)
            if stamp is None:
                continue
            previous = known.get(key)
            if previous and previous.get("metadata_version") == METADATA_VERSION and previous.get("verified_file") == stamp:
                record = previous
            else:
                item = dict(id=uuid.uuid4().hex, name=name, path=str(path), linked=True)
                record = verify_video(item, stamp)
            discovered.append((key, record))

    with LOCK:
        if generation != folder_generation:
            raise ValueError("The library was restored during the scan. Refresh the folder again.")
        paths = {os.path.normcase(item["path"]): item for item in LIBRARY.values() if item.get("linked")}
        updated = LIBRARY.copy()
        registered = saved_roots([*FOLDERS, root])
        new_count = 0
        for key, item in discovered:
            existing = paths.get(key)
            if existing is None and key in known:
                continue
            if existing and (known.get(key) is item or existing.get("verified_file") == item.get("verified_file")):
                record = dict(existing)
            else:
                record = {**(existing or {}), **item}
            if existing:
                record["id"] = existing["id"]
                if record.get("unlinked_folder"):
                    record = restored_clip(record)
            else:
                new_count += 1
            updated[record["id"]] = record

        changes = [(file, value) for file, value, old in (
            (FOLDERS_FILE, registered, FOLDERS), (LIBRARY_FILE, updated, LIBRARY),
        ) if value != old]
        save_settings_files(changes)
        LIBRARY.update(updated)
        FOLDERS[:] = registered
    return dict(root=root, total=len(discovered), added=new_count,
                unsupported=sum(bool(item.get("unsupported")) for _, item in discovered))


def rename_no_replace(old, new):
    if os.name == "nt":
        old.rename(new)
    elif sys.platform == "darwin":
        import ctypes
        rename = ctypes.CDLL(None, use_errno=True).renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        rename_excl = 0x00000004
        if rename(os.fsencode(old), os.fsencode(new), rename_excl):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(new))
    else:
        raise ValueError("Folder renaming is available on Windows and macOS.")


def renamed_paths(old, new):
    return {clip_id: dict(item, path=str(new / Path(item["path"]).relative_to(old)))
            for clip_id, item in LIBRARY.items()
            if item.get("linked") and Path(item["path"]).is_relative_to(old)}


def folder_identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino]


def save_folder_rename(old, new, updates):
    updated = {**LIBRARY, **updates}
    favorites = saved_roots([
        str(new / Path(value).relative_to(old)) if Path(value).is_relative_to(old) else value
        for value in FAVORITES
    ])
    changes = [(LIBRARY_FILE, updated)]
    if favorites != FAVORITES:
        changes.append((FAVORITES_FILE, favorites))
    save_settings_files(changes)
    LIBRARY.update(updates)
    FAVORITES[:] = favorites


def recover_folder_rename():
    if not FOLDER_RENAME_FILE.is_file():
        return True
    pending = json.loads(FOLDER_RENAME_FILE.read_bytes())
    new = local_path(pending["new"])
    old = local_path(pending["old"])
    # Check the actual directory entry spelling for case-only renames.
    try:
        entries = {entry.name: entry for entry in new.parent.iterdir()}
        if new.name in entries and folder_identity(entries[new.name]) == pending["identity"]:
            save_folder_rename(old, new, renamed_paths(old, new))
        FOLDER_RENAME_FILE.unlink()
    except OSError:
        return False
    return True


def rename_linked_folder(root, parts, name):
    with FOLDER_OPERATION, LOCK:
        if not recover_folder_rename() or not recover_file_change():
            raise ValueError("Reconnect the drive to finish recovering the previous file or folder operation.")
        old = registered_folder(root, parts)
        if not parts or ROOT.is_relative_to(old) or old.is_relative_to(ROOT) or any(
            Path(other).is_relative_to(old) for other in FOLDERS
        ):
            raise ValueError("Choose a subfolder that does not contain the toolkit or another linked root.")
        name = folder_part(name)
        if not name.strip() or any(ord(char) < 32 for char in name):
            raise ValueError("Enter a valid folder name.")
        if name == old.name:
            return {"parts": parts}
        new = old.with_name(name)
        # The OS also rejects an existing destination at the time of the rename.
        if name in {entry.name for entry in old.parent.iterdir()}:
            raise ValueError("A file or folder already uses that name.")
        updates = renamed_paths(old, new)
        if any(clip_id not in updates and item.get("linked") and Path(item["path"]).is_relative_to(new)
               for clip_id, item in LIBRARY.items()):
            raise ValueError("The destination still has linked clips in the library.")
        current = find_clip(state["current"])
        if current and media_item(current)["id"] in updates:
            raise ValueError("Stop the clip on Program before renaming its folder.")
        if os.name != "nt" and sys.platform != "darwin":
            raise ValueError("Folder renaming is available on Windows and macOS.")

        save_json(FOLDER_RENAME_FILE, dict(old=str(old), new=str(new), identity=folder_identity(old)))
        try:
            rename_no_replace(old, new)
        except OSError as exc:
            FOLDER_RENAME_FILE.unlink()
            raise ValueError("The folder could not be renamed. Check the name, folder permissions, and open files.") from exc
        try:
            save_folder_rename(old, new, updates)
        except OSError as exc:
            try:
                rename_no_replace(new, old)
            except OSError:
                LIBRARY.update(updates)
                raise ValueError("The folder moved, but saving its new path failed. Restart Video Rundown to recover the links.") from exc
            FOLDER_RENAME_FILE.unlink()
            raise ValueError("The path update could not be saved. The original folder name was restored.") from exc
        FOLDER_RENAME_FILE.unlink()
        cued = find_clip(state.get("cue"))
        if cued and media_item(cued)["id"] in updates:
            cue(cued["id"])
        return {"parts": [*parts[:-1], name]}


def check_file_unlocked(path):
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    handle = create(str(path), 0x10000, 0, None, 3, 0, None)  # DELETE, exclusive, OPEN_EXISTING
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    close(handle)


def update_file_path(item, target, linked, renamed, stamp):
    record = dict(item, path=str(target), name=target.name, linked=linked)
    if linked:
        record.pop("cache_name", None)
    else:
        record["cache_name"] = target.name
    if renamed:
        record.pop("title", None)
    current = file_stamp(target)
    if current and item.get("verified_file") == stamp and current[:2] == stamp[:2]:
        record["verified_file"] = current
        stat = target.stat()
        details = dict(item.get("metadata") or {})
        details.update(size_bytes=stat.st_size,
                       modified_at=item.get("source_modified_at", stat.st_mtime),
                       cached_modified=not linked and "source_modified_at" not in item)
        created_at = getattr(stat, "st_birthtime", None)
        if created_at is not None:
            details["created_at"] = created_at
        record["metadata"] = details
    else:
        record.pop("verified_file", None)
    return record


def recover_file_change():
    if not FILE_CHANGE_FILE.is_file():
        return True
    change = json.loads(FILE_CHANGE_FILE.read_bytes())
    item = LIBRARY.get(change["clip"])
    source, target = Path(change["source"]), Path(change["target"])
    try:
        if item and item["path"] == str(source):
            exact_name = any(entry.name == target.name for entry in target.parent.iterdir())
            if exact_name and folder_identity(target) == change["identity"]:
                record = update_file_path(item, target, change["linked"], change["renamed"], change["stamp"])
                save_json(LIBRARY_FILE, {**LIBRARY, item["id"]: record})
                LIBRARY[item["id"]] = record
            elif not source.is_file():
                return False
        if change.get("stage"):
            stage = Path(change["stage"])
            if stage.parent == target.parent and re.fullmatch(r"\.rundown-[a-f0-9]{32}\.part", stage.name):
                stage.unlink(missing_ok=True)
        FILE_CHANGE_FILE.unlink()
    except OSError:
        return False
    return True


def copy_for_move(source, stage, stamp):
    count = 0
    with source.open("rb") as original, stage.open("xb") as output:
        while block := original.read(1024**2):
            output.write(block)
            count += len(block)
            with LOCK:
                FILE_OPERATION["bytes"] = count
        output.flush()
        os.fsync(output.fileno())
    shutil.copystat(source, stage)
    if count != stamp[0] or file_stamp(source) != stamp:
        raise ValueError("The original changed during the move. The original file was kept.")


def perform_file_change(clip_id, request):
    with FOLDER_OPERATION:
        with LOCK:
            if not recover_file_change():
                raise ValueError("Reconnect the drive to recover the previous file operation.")
            item = LIBRARY.get(clip_id)
            if not item:
                raise ValueError("This clip is no longer in the library.")
            if not request.get("path") == item["path"]:
                raise ValueError("The clip path changed. Open its menu again.")
            source = Path(item["path"])
            if source.is_symlink() or not (stamp := file_stamp(source)):
                raise ValueError("This video file is missing or cannot be accessed.")
            renamed = request["kind"] == "rename"
            if renamed:
                name = folder_part(request.get("name"))
                if name != name.strip() or not name.strip() or any(ord(char) < 32 for char in name):
                    raise ValueError("Enter a valid file name.")
                if Path(name).suffix.lower() != source.suffix.lower():
                    raise ValueError("Keep the original file extension.")
                target = source.with_name(name)
                linked = bool(item.get("linked"))
            else:
                directory = local_path(request.get("destination")).resolve()
                if (not directory.is_dir() or directory.is_relative_to(CACHE)
                        or directory.is_relative_to(ROOT)):
                    raise ValueError("Choose a destination folder outside the toolkit.")
                target = directory / folder_part(item["name"] if not item.get("linked") else source.name)
                linked = True
            if str(source) == str(target):
                return "The file is already at this path."
            if (target != source and os.path.lexists(target)) or any(
                other_id != clip_id and Path(other["path"]) == target for other_id, other in LIBRARY.items()
            ):
                raise ValueError("A file or library entry already uses that destination.")
            if target == source and any(entry.name == target.name for entry in source.parent.iterdir()):
                raise ValueError("A file or folder already uses that name.")
            FILE_OPERATION["total"] = stamp[0]

        change = dict(clip=clip_id, source=str(source), target=str(target), linked=linked,
                      renamed=renamed, stamp=stamp, identity=folder_identity(source))
        stage = target.parent / (".rundown-" + uuid.uuid4().hex + ".part")
        copied = False
        check_file_unlocked(source)
        change["stage"] = str(stage)
        save_json(FILE_CHANGE_FILE, change)
        try:
            try:
                rename_no_replace(source, target)
            except OSError as error:
                if error.errno != errno.EXDEV and getattr(error, "winerror", None) != 17:
                    raise
                copy_for_move(source, stage, stamp)
                check_file_unlocked(source)
                change["identity"] = folder_identity(stage)
                save_json(FILE_CHANGE_FILE, change)
                rename_no_replace(stage, target)
                copied = True
        except (OSError, ValueError):
            FILE_CHANGE_FILE.unlink(missing_ok=True)
            raise
        finally:
            stage.unlink(missing_ok=True)

        target_stamp = file_stamp(target)
        if target_stamp is None or target_stamp[0] != stamp[0]:
            raise ValueError("The destination could not be verified. Check both folders before retrying.")
        with LOCK:
            item = LIBRARY[clip_id]
            record = update_file_path(item, target, linked, renamed, stamp)
            try:
                save_json(LIBRARY_FILE, {**LIBRARY, clip_id: record})
            except OSError as error:
                try:
                    undo_file_publish(source, target, target_stamp, copied)
                    FILE_CHANGE_FILE.unlink()
                except (OSError, ValueError):
                    raise ValueError("The file reached its destination, but its link could not be saved. Restart Video Rundown to recover it.") from error
                raise ValueError("The library could not be saved. The original file was kept.") from error
            LIBRARY[clip_id] = record

        if copied:
            try:
                check_file_unlocked(source)
                if file_stamp(source) != stamp or file_stamp(target) != target_stamp:
                    raise ValueError("The original or destination changed during the move.")
                source.unlink()
            except (OSError, ValueError) as error:
                with LOCK:
                    try:
                        save_json(LIBRARY_FILE, {**LIBRARY, clip_id: item})
                        LIBRARY[clip_id] = item
                        undo_file_publish(source, target, target_stamp, True)
                    except (OSError, ValueError):
                        FILE_CHANGE_FILE.unlink(missing_ok=True)
                        raise ValueError("The original could not be removed. Both files were kept; check the path shown in File Library.") from error
                FILE_CHANGE_FILE.unlink(missing_ok=True)
                raise ValueError("The original could not be removed. Close any app using it and try again.") from error

        FILE_CHANGE_FILE.unlink(missing_ok=True)
        with LOCK:
            RENAME_SUGGESTIONS.pop(clip_id, None)
            picked = find_clip(state.get("cue"))
            if picked and media_item(picked)["id"] == clip_id:
                cue(picked["id"])
        return "File renamed on drive." if renamed else "File moved."


def undo_file_publish(source, target, stamp, copied):
    if stamp is None or file_stamp(target) != stamp:
        raise ValueError("The destination changed.")
    if copied:
        target.unlink()
    else:
        rename_no_replace(target, source)


def run_file_operation(clip_id, request):
    try:
        message = perform_file_change(clip_id, request)
    except ValueError as error:
        with LOCK:
            FILE_OPERATION.update(status="failed", message=str(error))
    except OSError as error:
        with LOCK:
            if getattr(error, "winerror", None) in {32, 33} or error.errno == errno.EBUSY:
                message = "The video is open in another program. Close it and try again."
            elif error.errno == errno.ENOSPC:
                message = "The destination drive does not have enough free space."
            elif isinstance(error, FileExistsError):
                message = "A file or folder already uses that destination."
            else:
                message = "The file operation was blocked. Check file permissions and close apps using the video."
            FILE_OPERATION.update(status="failed", message=message)
    else:
        with LOCK:
            FILE_OPERATION.update(status="done", bytes=FILE_OPERATION["total"], message=message)


def start_file_operation(data):
    kind, clip_id = data.get("kind"), data.get("id")
    if kind not in ("move", "rename") or not isinstance(clip_id, str):
        raise ValueError("Choose a clip to organize.")
    with LOCK:
        if FILE_OPERATION.get("status") == "running":
            raise ValueError("Another file operation is already running.")
        item = LIBRARY.get(clip_id)
        current = find_clip(state["current"])
        if not item:
            raise ValueError("Choose a clip to organize.")
        if current and media_item(current)["id"] == clip_id:
            raise ValueError("Stop the clip on Program before moving or renaming it.")
        if data.get("path") != item["path"]:
            raise ValueError("The clip path changed. Open its menu again.")
        job = uuid.uuid4().hex
        FILE_OPERATION.clear()
        FILE_OPERATION.update(id=job, clip=clip_id, status="running", kind=kind, bytes=0, total=0, message="")
        threading.Thread(target=run_file_operation, args=(clip_id, data), daemon=True).start()
    return {"id": job}


def link_single_file(value):
    with FOLDER_OPERATION:
        path = local_path(value).resolve()
        if path.suffix.lower() not in FORMATS | OTHER_VIDEO_FORMATS or path.is_relative_to(CACHE):
            raise ValueError("Choose a video file outside the rundown cache.")
        stamp = file_stamp(path)
        if stamp is None:
            raise ValueError("The video file is unavailable.")
        with LOCK:
            generation = folder_generation
            existing = next((item for item in LIBRARY.values() if item.get("linked") and Path(item["path"]) == path), None)
            if existing:
                if existing.get("unlinked_folder"):
                    record = restored_clip(existing)
                    save_json(LIBRARY_FILE, {**LIBRARY, record["id"]: record})
                    LIBRARY[record["id"]] = record
                return {"id": existing["id"], "unsupported": existing.get("unsupported")}
        clip_id = uuid.uuid4().hex
        record = verify_video(dict(id=clip_id, name=path.name, path=str(path), linked=True), stamp)
        with LOCK:
            if generation != folder_generation or file_stamp(path) != stamp:
                raise ValueError("The library or video changed. Link the file again.")
            save_json(LIBRARY_FILE, {**LIBRARY, clip_id: record})
            LIBRARY[clip_id] = record
        return {"id": clip_id, "unsupported": record.get("unsupported")}


def cache_path(clip_id, item):
    suffix = Path(item["name"]).suffix.lower()
    cache_name = item.get("cache_name")
    if cache_name is None:
        return CACHE / (clip_id + suffix)
    if folder_part(cache_name) != cache_name or Path(cache_name).suffix.lower() != suffix:
        raise ValueError("Invalid cached video file name.")
    return CACHE / cache_name


def history_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Clip", "Started", "Ended", "Result"])
    for entry in HISTORY:
        name = entry["name"]
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        times = [datetime.fromtimestamp(entry[key]).astimezone().isoformat(timespec="milliseconds")
                 for key in ("started", "ended")]
        writer.writerow([name, *times, entry["result"]])
    return output.getvalue()


def create_backup(kind):
    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    name = f"rundown-{stamp}-{uuid.uuid4().hex[:6]}.{kind}"
    path = BACKUPS / name
    temporary = path.with_suffix(".tmp")
    try:
        if kind == "csv":
            temporary.write_text(history_csv(), encoding="utf-8-sig", newline="")
        else:
            snapshot = dict(
                version=1, created_at=datetime.now().astimezone().isoformat(),
                library={clip_id: {key: value for key, value in item.items()
                                   if key not in {"verified_file", "metadata_version", "unsupported"}
                                   and (key != "path" or item.get("linked"))}
                         for clip_id, item in LIBRARY.items()},
                playlist=[{"id": item["id"], "marker": True} if item.get("marker") else
                          {"id": item["id"], "media_id": item.get("media_id", item["id"])}
                          for item in QUEUE if not item.get("played")],
                categories=CATEGORIES, history=HISTORY, folders=FOLDERS, favorites=FAVORITES,
                settings={key: state.get(key) for key in ("auto", "auto_cut", "return_playback", "next_cue")},
            )
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"name": name, "path": str(path)}


def read_legacy_backup(path):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema = OFF")
            tables = {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            library_columns = {row[1] for row in db.execute("PRAGMA table_info(library)")}
            removed_column = "removed" if "removed" in library_columns else "0"
            library = {}
            for clip_id, name, title, duration, removed in db.execute(
                    f"SELECT id, name, title, duration_ms, {removed_column} FROM library"):
                if not re.fullmatch(r"[a-f0-9]{32}", clip_id) or Path(name).suffix.lower() not in FORMATS:
                    raise ValueError("Invalid media record.")
                clip_path = CACHE / (clip_id + Path(name).suffix.lower())
                library[clip_id] = dict(id=clip_id, name=name, title=title, duration_ms=duration or 0,
                                        removed=bool(removed), path=str(clip_path))
            if "library_details" in tables:
                for clip_id, metadata, modified in db.execute("SELECT id, metadata, source_modified_at FROM library_details"):
                    if clip_id in library:
                        library[clip_id]["metadata"] = json.loads(metadata)
                        if modified is not None:
                            library[clip_id]["source_modified_at"] = modified
            categories = [category_name(name) for name, in db.execute("SELECT name FROM categories")] if "categories" in tables else []
            if "clip_categories" in tables:
                for clip_id, name in db.execute("SELECT media_id, category FROM clip_categories"):
                    name = category_name(name)
                    if clip_id in library:
                        library[clip_id].setdefault("categories", []).append(name)
                        if name not in categories:
                            categories.append(name)
            queue = []
            for clip_id, media_id, title, marker, played in db.execute(
                    "SELECT id, media_id, title, marker, played FROM playlist ORDER BY position"):
                if not re.fullmatch(r"[a-f0-9]{32}", clip_id):
                    raise ValueError("Invalid playlist record.")
                if marker:
                    queue.append(dict(id=clip_id, marker=True))
                elif not played and media_id in library and not library[media_id]["removed"]:
                    queue.append(dict(library[media_id], id=clip_id, media_id=media_id, title=title, played=False))
            history = [dict(name=name, started=start, ended=end, result=result)
                       for name, start, end, result in db.execute("SELECT clip, started_epoch, ended_epoch, result FROM history ORDER BY rowid")]
            if any(not isinstance(row["name"], str) or not isinstance(row["result"], str)
                   or not all(math.isfinite(row[key]) and abs(row[key]) <= 253402300799 for key in ("started", "ended"))
                   for row in history):
                raise ValueError("Invalid playback history.")
            settings = {key: json.loads(value) for key, value in db.execute(
                "SELECT key, value FROM settings WHERE key IN ('auto','auto_cut','next_cue')")}
            settings["auto"] = settings.get("auto") is True
            if settings.get("auto_cut") not in {"off", "clip", "rundown"}:
                settings["auto_cut"] = "off"
            if not any(clip["id"] == settings.get("next_cue") and not clip.get("marker") for clip in queue):
                settings["next_cue"] = None
    except (sqlite3.Error, ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("This file is not a valid Video Rundown SQLite backup.") from exc

    return library, queue, categories, history, settings


def read_json_backup(path):
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
        if snapshot["version"] != 1:
            raise ValueError("Unrecognized backup version.")
        library = {}
        cache_paths = set()
        for clip_id, item in snapshot["library"].items():
            name = item["name"]
            if not re.fullmatch(r"[a-f0-9]{32}", clip_id) or not isinstance(name, str) or not name:
                raise ValueError("Invalid media record.")
            extension = Path(name).suffix.lower()
            linked = item.get("linked") is True
            if extension not in (FORMATS | OTHER_VIDEO_FORMATS if linked else FORMATS):
                raise ValueError("Invalid media extension.")
            media_path = local_path(item["path"]) if linked else cache_path(clip_id, item)
            if linked and (media_path.suffix.lower() != extension or media_path.is_relative_to(CACHE)):
                raise ValueError("Invalid linked media path.")
            if not linked:
                if media_path in cache_paths:
                    raise ValueError("Duplicate cached video path.")
                cache_paths.add(media_path)
            title = item.get("title")
            duration_ms = item.get("duration_ms")
            library[clip_id] = dict(id=clip_id, name=name, path=str(media_path), linked=linked,
                                    title=title if isinstance(title, str) else None,
                                    removed=item.get("removed") is True,
                                    categories=[backup_category(value) for value in item.get("categories", [])],
                                    duration_ms=duration_ms if type(duration_ms) is int and duration_ms >= 0 else 0)
            if linked and item.get("removed") is True and item.get("unlinked_folder") is True:
                library[clip_id]["unlinked_folder"] = True
            if not linked and item.get("cache_name") is not None:
                library[clip_id]["cache_name"] = media_path.name
            modified = item.get("source_modified_at")
            if type(modified) in {int, float} and math.isfinite(modified):
                library[clip_id]["source_modified_at"] = modified
        categories = list(dict.fromkeys(backup_category(name) for name in snapshot["categories"]))
        queue = []
        seen = set()
        for row in snapshot["playlist"]:
            clip_id = row["id"]
            if not re.fullmatch(r"[a-f0-9]{32}", clip_id) or clip_id in seen:
                raise ValueError("Invalid playlist record.")
            seen.add(clip_id)
            if row.get("marker") is True:
                queue.append(dict(id=clip_id, marker=True))
            else:
                item = library[row["media_id"]]
                if item["removed"]:
                    raise ValueError("Playlist references a removed clip.")
                queue.append(dict(item, id=clip_id, media_id=item["id"], played=False))
        history = []
        for row in snapshot["history"]:
            name, result, started, ended = (row[key] for key in ("name", "result", "started", "ended"))
            if not isinstance(name, str) or not isinstance(result, str) or not all(
                type(value) in {int, float} and math.isfinite(value) and abs(value) <= 253402300799
                for value in (started, ended)
            ):
                raise ValueError("Invalid playback history.")
            history.append(dict(name=name, result=result, started=started, ended=ended))
        raw_settings = snapshot["settings"]
        mode = raw_settings.get("auto_cut")
        next_cue = raw_settings.get("next_cue")
        settings = dict(auto=raw_settings.get("auto") is True,
                        auto_cut=mode if mode in {"off", "clip", "rundown"} else "off",
                        return_playback="continue" if raw_settings.get("return_playback") == "continue" else "restart",
                        next_cue=next_cue if any(row["id"] == next_cue and not row.get("marker") for row in queue) else None)
        return (library, queue, categories, history, settings, saved_roots(snapshot.get("folders", [])),
                saved_roots(snapshot.get("favorites", [])))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
        raise ValueError("This file is not a valid Video Rundown JSON backup.") from exc


def backup_category(name):
    # Folder names can be longer than manually entered categories.
    if not isinstance(name, str) or not name or len(name) > 255 or any(ord(char) < 32 for char in name):
        raise ValueError("Invalid category name.")
    return name


def restore_backup(path, *, legacy=False):
    global folder_generation, held_path
    if state["current"] or FILE_OPERATION.get("status") == "running":
        raise ValueError("Stop the rundown and wait for file operations before restoring a backup.")
    if not recover_folder_rename():
        raise ValueError("Reconnect the drive to finish recovering the previous folder rename.")
    if not recover_file_change():
        raise ValueError("Reconnect the drive to recover the last file operation before restoring.")
    library, queue, categories, history, settings, folders, favorites = (
        (*read_legacy_backup(path), [], []) if legacy else read_json_backup(path)
    )
    if state.get("interrupted"):
        if rundown_ready(obs()):
            release_rundown_media(obs())
        held_path = None
        state["interrupted"] = None
    settings.setdefault("return_playback", "restart")
    migrate_unlinked_records(library, folders)
    if LIBRARY or QUEUE or HISTORY or CATEGORIES or FOLDERS or FAVORITES:
        create_backup("json")
    updates = [(LIBRARY_FILE, library), (QUEUE_FILE, queue), (HISTORY_FILE, history),
               (CATEGORIES_FILE, categories), (SETTINGS_FILE, settings), (FOLDERS_FILE, folders),
               (FAVORITES_FILE, favorites)]
    save_settings_files(updates)
    LIBRARY.clear()
    LIBRARY.update(library)
    QUEUE[:] = queue
    HISTORY[:] = history
    CATEGORIES[:] = categories
    FOLDERS[:] = folders
    FAVORITES[:] = favorites
    folder_generation += 1
    RENAME_SUGGESTIONS.clear()
    WATCHED_FOLDERS.clear()
    FAVORITE_TREES.clear()
    state.update(settings, return_ready=False, handoff="")
    cue(None)


def list_backups():
    return [{"name": path.name, "size": path.stat().st_size} for path in
            sorted(BACKUPS.glob("rundown-*"), reverse=True)
            if path.is_file() and path.suffix in {".csv", ".sqlite", ".json"}]


def obs_settings():
    if config := os.getenv("OBS_TOOLKIT_CONFIG_DIR"):
        base = Path(config)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "obs-studio"
    else:
        base = Path.home() / "Library/Application Support/obs-studio"
    try:
        settings = json.loads((base / "plugin_config/obs-websocket/config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    port = int(os.getenv("OBS_PORT", settings.get("server_port", 4455)))
    password = os.getenv("OBS_PASSWORD", settings.get("server_password", "") if settings.get("auth_required") else "")
    return port, password


def obs():
    global client
    if client is None:
        port, password = obs_settings()
        client = obsws_python.ReqClient(host="127.0.0.1", port=port, password=password, timeout=3)
    return client


def rundown_input(c, items):
    if not any(item["sourceName"] == SOURCE for item in items):
        return None
    source = c.get_input_settings(SOURCE)
    return source.input_settings if source.input_kind == "ffmpeg_source" else None


def rundown_ready(c):
    source = rundown_input(c, c.get_scene_item_list(SCENE).scene_items)
    return source is not None and source.get(RUNDOWN_OWNER) is True


def source_is_shared(c, scenes):
    for scene in scenes:
        name = scene["sceneName"]
        if name != SCENE and any(item["sourceName"] == SOURCE for item in c.get_scene_item_list(name).scene_items):
            return True
    return any(item["sourceName"] == SOURCE for name in c.get_group_list().groups
               for item in c.get_group_scene_item_list(name).scene_items)


def setup(adopt_existing=False):
    c = obs()
    scenes = c.get_scene_list().scenes
    scene_exists = any(item["sceneName"] == SCENE for item in scenes)
    source_exists = any(item["inputName"] == SOURCE for item in c.get_input_list().inputs)
    if scene_exists or source_exists:
        items = c.get_scene_item_list(SCENE).scene_items if scene_exists else []
        source = rundown_input(c, items) if source_exists else None
        if source is not None and source.get(RUNDOWN_OWNER) is True:
            state["ready"] = True
            return
        if source is None or source_is_shared(c, scenes):
            raise ValueError(
                "An existing OBS scene or source uses a Video Rundown name. "
                "Rename the conflicting scene or source in OBS before setting up Video Rundown."
            )
        if not adopt_existing:
            raise ValueError("Confirm that Video Rundown can use the existing scene and source.")
        # Adopt the standalone pair used by earlier toolkit versions, keeping its layout.
        c.set_input_settings(SOURCE, {RUNDOWN_OWNER: True}, True)
    else:
        video = c.get_video_settings()
        c.create_scene(SCENE)
        item_id = None
        try:
            created = c.create_input(SCENE, SOURCE, "ffmpeg_source",
                                     {"is_local_file": True, RUNDOWN_OWNER: True}, True)
            item_id = created.scene_item_id
            c.set_scene_item_transform(SCENE, item_id, {
                "positionX": 0, "positionY": 0, "alignment": 5,
                "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 0,
                "boundsWidth": video.base_width, "boundsHeight": video.base_height,
            })
        except Exception:
            with suppress(Exception):
                items = c.get_scene_item_list(SCENE).scene_items
                if not items or (len(items) == 1 and items[0]["sceneItemId"] == item_id):
                    c.remove_scene(SCENE)
            raise
    state["ready"] = True


def release_rundown_media(c):
    c.trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP")
    c.set_input_settings(SOURCE, {"local_file": ""}, True)


def take_rundown_off_air(c, media):
    global armed, held_path
    clip = find_clip(state["current"])
    can_continue = clip and media.media_state in {"OBS_MEDIA_STATE_PLAYING", "OBS_MEDIA_STATE_PAUSED"}
    if can_continue:
        if media.media_state == "OBS_MEDIA_STATE_PLAYING":
            c.trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE")
            media = c.get_media_input_status(SOURCE)
        held_path = media_item(clip)["path"]
    else:
        release_rundown_media(c)
        held_path = None
    log_playback("Taken off air")
    armed = False
    state.update(current=None, status="Stopped", cursor=0, duration=0, schedule_anchor=None,
                 next_cue=clip["id"] if clip else None,
                 interrupted=dict(id=clip["id"], cursor=media.media_cursor or 0) if can_continue else None)


def play(clip):
    item = require_playable(clip)
    global armed, started, sampled_at, held_path
    c = obs()
    if c.get_current_program_scene().current_program_scene_name != SCENE:
        raise ValueError("Put Video Rundown on Program before playing a clip.")
    if not rundown_ready(c):
        state["ready"] = False
        raise ValueError("Set up the Video Rundown scene and its media source first.")
    interrupted = state.get("interrupted") or {}
    continuing = state["return_playback"] == "continue" and interrupted.get("id") == clip["id"]
    cursor, duration = 0, 0
    if continuing:
        media = c.get_media_input_status(SOURCE)
        if (held_path != item["path"] or media.media_state != "OBS_MEDIA_STATE_PAUSED"
                or abs((media.media_cursor or 0) - interrupted["cursor"]) > 1500):
            raise ValueError("The paused video is no longer available. Choose Restart clip to play it again.")
        cursor, duration = media.media_cursor or 0, media.media_duration or 0
        c.trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY")
    else:
        c.set_input_settings(SOURCE, {
            "is_local_file": True, "local_file": item["path"], "looping": False,
            "restart_on_activate": False, "close_when_inactive": False,
            "clear_on_media_end": True,
        }, True)
        c.trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")
    log_playback("Replaced")
    armed = False
    held_path = None
    started = sampled_at = time.monotonic()
    state.update(program=True, return_ready=False, handoff="", current=clip["id"], status="Loading",
                 cursor=cursor, duration=duration, air_started=None, schedule_anchor=None,
                 next_cue=None, interrupted=None, air_revision=state["air_revision"] + 1)
    clip["played"] = False
    save_queue()


def current_index():
    return next((i for i, clip in enumerate(QUEUE) if clip["id"] == state["current"]), -1)


def cut_to_preview():
    if not state["return_ready"] and not state["current"]:
        raise ValueError("There is no rundown playback to cut from.")
    c = obs()
    scenes = c.get_scene_list()
    preview = scenes.current_preview_scene_name
    if scenes.current_program_scene_name != SCENE:
        raise ValueError("Video Rundown is no longer on Program.")
    if not c.get_studio_mode_enabled().studio_mode_enabled or not preview or preview == SCENE:
        raise ValueError("Select a different OBS Preview scene in Studio Mode.")
    transitions = c.get_scene_transition_list()
    cut = next((item["transitionName"] for item in transitions.transitions
                if item["transitionKind"] == "cut_transition"), None)
    if not cut:
        raise ValueError("OBS has no Cut transition available.")
    override = c.get_scene_scene_transition_override(preview)
    prior_name = transitions.current_scene_transition_name
    change_override = override.transition_name not in (None, cut)
    triggered = False
    try:
        if change_override:
            c.set_scene_scene_transition_override(preview, cut, override.transition_duration)
        if prior_name != cut:
            c.set_current_scene_transition(cut)
        c.trigger_studio_mode_transition()
        triggered = True
    finally:
        try:
            if triggered:
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    time.sleep(.05)
                    if c.get_current_program_scene().current_program_scene_name == preview:
                        # Let OBS finish its queued transition-stop updates.
                        time.sleep(.2)
                        state.update(return_ready=False, program=False, error="", handoff=f"Cut to {preview}.")
                        if state["current"]:
                            take_rundown_off_air(c, c.get_media_input_status(SOURCE))
                        else:
                            state.update(status="Idle", cursor=0, duration=0)
                        break
        finally:
            try:
                if prior_name and prior_name != cut:
                    c.set_current_scene_transition(prior_name)
            finally:
                if change_override:
                    c.set_scene_scene_transition_override(
                        preview, override.transition_name, override.transition_duration)


def next_pending(after=-1):
    return next((clip for clip in QUEUE[after + 1:] if not clip.get("played") and not clip.get("marker")
                 and media_status(media_item(clip)) == "ready"), None)


def next_to_play(after=-1):
    clip = find_clip(state.get("next_cue"))
    return clip if clip and media_status(media_item(clip)) == "ready" else next_pending(after)


def finish_clip():
    log_playback("Completed")
    index = current_index()
    marker = index >= 0 and index + 1 < len(QUEUE) and QUEUE[index + 1].get("marker")
    upcoming = next_pending(index)
    if index >= 0:
        completed = QUEUE.pop(index)
        if marker:
            QUEUE.pop(index)
        save_queue()
        if state.get("cue") == completed["id"]:
            cue(None)
    state.update(current=None, next_cue=upcoming["id"] if upcoming else None)
    if marker:
        state.update(status="Stopped", cursor=0, duration=0)
        cue(state["next_cue"])
    mode = state["auto_cut"]
    if state["auto"] and upcoming and not marker and mode != "clip":
        play(upcoming)
        return
    state["return_ready"] = True
    try:
        release_rundown_media(obs())
    except Exception:
        state["error"] = "The clip finished, but OBS could not clear Rundown Player."
    if mode == "clip" or (mode == "rundown" and not upcoming):
        try:
            cut_to_preview()
        except Exception as exc:
            detail = str(exc) if isinstance(exc, ValueError) else "Check OBS and try Cut to Preview."
            state["error"] = "Auto-cut did not complete. " + detail


def start_on_program(previous, current):
    if previous is None or previous == SCENE or current != SCENE:
        return
    if not state["auto"] or not state["ready"]:
        return
    if state["current"] and state["status"] not in {"Idle", "Ended", "Stopped", "Error"}:
        return
    clip = next_to_play()
    if clip:
        try:
            play(clip)
            state["error"] = ""
        except ValueError as exc:
            state["error"] = str(exc)
        except Exception:
            state["error"] = "Could not start the rundown on Program. Use Play next to retry."


def poll():
    global armed, client, sampled_at
    previous_program = None
    while True:
        time.sleep(.4)
        with LOCK:
            try:
                c = obs()
                scenes = c.get_scene_list()
                state["program"] = scenes.current_program_scene_name == SCENE
                state["preview"] = scenes.current_preview_scene_name
                if not any(item["sceneName"] == SCENE for item in scenes.scenes):
                    state.update(ready=False, setup_existing=False)
                elif not state["ready"] or (state["program"] and previous_program != SCENE):
                    items = c.get_scene_item_list(SCENE).scene_items
                    source = rundown_input(c, items)
                    ready = source is not None and source.get(RUNDOWN_OWNER) is True
                    if ready and previous_program is None and not state["current"] and not state.get("interrupted"):
                        if source.get("local_file"):
                            release_rundown_media(c)
                    state.update(ready=ready, setup_existing=not ready and source is not None)
                if not state["program"]:
                    state["return_ready"] = False
                last_program = previous_program
                previous_program = scenes.current_program_scene_name
                start_on_program(last_program, previous_program)
                if not state["current"]:
                    continue
                previous_status = state["status"]
                media = c.get_media_input_status(SOURCE)
                if not state["program"]:
                    take_rundown_off_air(c, media)
                    continue
                sampled_at = time.monotonic()
                status = media.media_state.removeprefix("OBS_MEDIA_STATE_").title()
                state.update(status=status, cursor=media.media_cursor or 0, duration=media.media_duration or 0)
                if status == "Playing" and state["program"]:
                    armed = True
                    if not state.get("air_started"):
                        state["air_started"] = time.time()
                    if state["duration"] and not state.get("schedule_anchor"):
                        state["schedule_anchor"] = time.time() + (state["duration"] - state["cursor"]) / 1000
                    clip = find_clip(state["current"])
                    media_id = clip.get("media_id", clip["id"])
                    if state["duration"] and LIBRARY.get(media_id, {}).get("duration_ms") != state["duration"]:
                        LIBRARY[media_id]["duration_ms"] = state["duration"]
                        save_json(LIBRARY_FILE, LIBRARY)
                elif status == "Paused":
                    state["schedule_anchor"] = None
                if status == "Ended" and previous_status != "Ended" and (armed or state["duration"] > 0):
                    armed = False
                    finish_clip()
                elif status == "Error" or (status in {"Opening", "None", "Stopped"} and time.monotonic() - started > 8):
                    log_playback("Playback error")
                    armed = False
                    state.update(error="OBS could not play this clip. Check the file and codec.", current=None)
            except Exception:
                previous_program = None
                state.update(program=False, preview=None)
                if client:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                client = None


def category_name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(char) < 32 for char in name):
        raise ValueError("Enter a category name between 1 and 60 characters.")
    return name.strip()


def action(data):
    global armed, held_path, sampled_at
    cmd = data.get("action")
    if cmd == "restore_backup":
        name = data.get("name", "")
        if not isinstance(name, str) or name not in {item["name"] for item in list_backups() if item["name"].endswith((".sqlite", ".json"))}:
            raise ValueError("Select a rundown backup from the Backups tab.")
        restore_backup(BACKUPS / name, legacy=name.endswith(".sqlite"))
        return
    if cmd == "cue":
        clip = find_clip(data.get("id"))
        if clip and not clip.get("marker"):
            require_playable(clip)
            cue(clip["id"])
        else:
            cue(None)
        return
    if cmd == "duration":
        clip = LIBRARY.get(data.get("id"))
        duration = data.get("ms")
        if clip and type(duration) is int and 0 < duration <= 7 * 86400 * 1000 and not clip.get("duration_ms"):
            clip["duration_ms"] = duration
            save_json(LIBRARY_FILE, LIBRARY)
        return
    if cmd == "enqueue":
        item = LIBRARY.get(data.get("id"))
        if not item or item.get("removed"):
            raise ValueError("Select an active file from the library.")
        require_playable(item)
        clip = dict(item, id=uuid.uuid4().hex, media_id=item["id"], played=False)
        target = next((i for i, row in enumerate(QUEUE) if row["id"] == data.get("target")), len(QUEUE))
        position = min(len(QUEUE), target + (1 if data.get("after") is True else 0))
        QUEUE.insert(position, clip)
        save_queue()
        return
    if cmd == "restore_media":
        restore_removed_clips([data.get("id")])
        return
    if cmd in {"remove_media", "forget_media", "trash_media"}:
        if FILE_OPERATION.get("status") == "running" and FILE_OPERATION.get("clip") == data.get("id"):
            raise ValueError("Wait for the file operation to finish.")
        item = LIBRARY.get(data.get("id"))
        if not item or bool(item.get("removed")) != (cmd != "remove_media"):
            raise ValueError("This clip has already been moved or removed.")
        if any(row.get("media_id", row["id"]) == item["id"] for row in QUEUE if not row.get("marker")):
            raise ValueError("Remove this clip from the Playlist before removing it from the library.")
        if cmd in {"forget_media", "trash_media"}:
            updated = LIBRARY.copy()
            del updated[item["id"]]
            save_json(LIBRARY_FILE, updated)
            del LIBRARY[item["id"]]
        else:
            record = dict(item, removed=True)
            save_json(LIBRARY_FILE, {**LIBRARY, record["id"]: record})
            LIBRARY[record["id"]] = record
        if cmd == "remove_media" and state.get("cue") == item["id"]:
            cue(None)
        return
    if cmd == "setup":
        setup(adopt_existing=data.get("adopt_existing") is True)
        return
    if cmd in {"auto", "auto_cut", "return_playback"}:
        value = bool(data.get("value")) if cmd == "auto" else data.get("value")
        if cmd == "auto_cut" and value not in {"off", "clip", "rundown"}:
            raise ValueError("Choose an auto-cut mode.")
        if cmd == "return_playback" and value not in {"restart", "continue"}:
            raise ValueError("Choose how the interrupted clip should play.")
        settings = {key: state[key] for key in ("auto", "auto_cut", "return_playback")}
        settings[cmd] = value
        save_json(SETTINGS_FILE, settings)
        state.update(settings)
        return
    if cmd == "cut":
        cut_to_preview()
        return
    if cmd == "play":
        clip = next((clip for clip in QUEUE if clip["id"] == data.get("id")), None)
        if not clip or clip.get("marker"):
            raise ValueError("Select a video clip first.")
        play(clip)
        return
    if cmd == "stop_recue":
        index = next((i for i, item in enumerate(QUEUE)
                      if item["id"] == data.get("id") and not item.get("marker")), -1)
        if index < 0:
            raise ValueError("Select a rundown clip first.")
        if index + 1 == len(QUEUE) or not QUEUE[index + 1].get("marker"):
            QUEUE.insert(index + 1, dict(id=uuid.uuid4().hex, marker=True))
            save_queue()
        return
    if cmd == "seek":
        position = data.get("ms")
        c = obs()
        if (not state["current"] or state["current"] != data.get("id")
                or c.get_current_program_scene().current_program_scene_name != SCENE):
            raise ValueError("That clip is no longer on air.")
        media = c.get_media_input_status(SOURCE)
        duration = media.media_duration or 0
        if type(position) is not int or duration <= 0 or media.media_state not in {
            "OBS_MEDIA_STATE_PLAYING", "OBS_MEDIA_STATE_PAUSED"
        }:
            raise ValueError("The current clip cannot be scrubbed.")
        position = max(0, min(position, duration - 1))
        c.set_media_input_cursor(SOURCE, position)
        sampled_at = time.monotonic()
        state.update(cursor=position, schedule_anchor=time.time() + (duration - position) / 1000)
        return
    if cmd == "stop":
        if state["current"] or state.get("interrupted"):
            c = obs()
            if rundown_ready(c):
                release_rundown_media(c)
            log_playback("Stopped")
            if current_index() >= 0:
                state["next_cue"] = state["current"]
            armed = False
            held_path = None
            state.update(current=None, interrupted=None, status="Stopped", cursor=0, duration=0,
                         schedule_anchor=None, return_ready=False)
        return
    if cmd in {"pause", "resume"}:
        if not state["current"]:
            return
        obs().trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_" + {
            "pause": "PAUSE", "resume": "PLAY",
        }[cmd])
        return
    if cmd == "next":
        clip = next_to_play(current_index())
        if not clip:
            raise ValueError("End of the rundown.")
        play(clip)
        return
    if cmd in {"move", "remove"}:
        index = next((i for i, clip in enumerate(QUEUE) if clip["id"] == data.get("id")), -1)
        if index < 0:
            raise ValueError("Select a clip first.")
        if QUEUE[index]["id"] == state["current"]:
            raise ValueError("The current clip is locked. Stop it before removing or reordering it.")
        if cmd == "remove":
            clip = QUEUE[index]
            if (state.get("interrupted") or {}).get("id") == clip["id"]:
                action({"action": "stop"})
            QUEUE.pop(index)
            save_queue()
            if state.get("next_cue") == clip["id"]:
                state["next_cue"] = None
            if state.get("cue") == clip["id"]:
                state["cue"] = None
        else:
            other = next((i for i, clip in enumerate(QUEUE) if clip["id"] == data.get("target")), -1)
            if other < 0:
                raise ValueError("The drop target is no longer in the rundown.")
            position = other + (1 if data.get("after") is True else 0)
            if position > index:
                position -= 1
            if position != index:
                QUEUE.insert(position, QUEUE.pop(index))
                try:
                    save_queue()
                except OSError:
                    QUEUE.insert(index, QUEUE.pop(position))
                    raise
        return
    raise ValueError("Unknown command.")


def current_cue():
    clip = find_clip(state["cue"]) if state.get("cue") else next(
        (clip for clip in QUEUE if not clip.get("marker") and media_status(media_item(clip)) == "ready"), None)
    return clip if clip and not clip.get("marker") else None


def update_cue_clock(data):
    owner, clip_id, revision = data.get("owner"), data.get("id"), data.get("revision")
    position, playing = data.get("position"), data.get("playing")
    if (not isinstance(owner, str) or not re.fullmatch(r"[a-f0-9]{32}", owner)
            or not isinstance(clip_id, str) or type(revision) is not int
            or type(position) not in (float, int) or not 0 <= position <= 7 * 86400
            or type(playing) is not bool):
        raise ValueError("Invalid cue playback sample.")
    with LOCK:
        if lan_monitor is None:
            return
        clip = current_cue()
        if not clip or clip["id"] != clip_id or revision != state.get("cue_revision", 0):
            return
        now = time.monotonic()
        if (cue_clock.get("owner") != owner and cue_clock.get("id") == clip_id
                and now - cue_clock["updated"] < 4):
            return
        cue_clock.update(owner=owner, id=clip_id, position=position, playing=playing, updated=now)


def on_air_state():
    clip = find_clip(state["current"]) if state["program"] else None
    if not clip or state["status"] not in {"Playing", "Paused"}:
        return None
    cursor = state["cursor"]
    if state["status"] == "Playing" and sampled_at:
        cursor += min(max(0, time.monotonic() - sampled_at), 1) * 1000
    duration = state["duration"]
    return dict(id=clip["id"], revision=state["air_revision"], name=clip_title(clip), status=state["status"],
                cursor=min(cursor, duration) if duration else cursor, duration=duration)


def local_preview_state():
    with LOCK:
        clip = current_cue()
        air = on_air_state()
        air_clip = find_clip(air["id"]) if air else None
        return dict(cue_clip=public_clip(clip) if clip else None,
                    cue_metadata=public_library_clip(media_item(clip))["metadata"] if clip else None,
                    air_metadata=public_library_clip(media_item(air_clip))["metadata"] if air_clip else None,
                    cue_from_library=state.get("cue") in LIBRARY, cue_revision=state.get("cue_revision", 0),
                    current=state["current"], lan_monitor_enabled=lan_monitor is not None, on_air=air)


def monitor_state():
    with LOCK:
        clip = current_cue()
        cued = public_clip(clip) if clip else None
        now = time.monotonic()
        if cued:
            position, playing = 0, False
            following = (cued["media_status"] == "ready" and cue_clock.get("id") == clip["id"]
                         and now - cue_clock["updated"] < 4)
            if cue_clock.get("id") == clip["id"]:
                playing = following and cue_clock["playing"]
                position = cue_clock["position"] + (now - cue_clock["updated"] if playing else 0)
            cued.update(revision=state.get("cue_revision", 0), position=position,
                        playing=playing, following=following)
        return dict(cue=cued, on_air=on_air_state())


def open_preview_clip(clip):
    try:
        if clip and not clip.get("marker"):
            return Path(require_playable(clip)["path"]).open("rb")
    except (OSError, ValueError):
        pass
    return None


def on_air_frame():
    global preview_frame
    with LOCK:
        if not state["program"] or not state["current"] or state["status"] not in {"Playing", "Paused"}:
            preview_frame = None
            return None
        key = (state["air_revision"], state["current"], state["status"])
        now = time.monotonic()
        if preview_frame and preview_frame[0] == key and now - preview_frame[1] < 0.4:
            return preview_frame[2]
        screenshot = obs().get_source_screenshot(SOURCE, "jpg", 480, 270, 70).image_data
        payload = base64.b64decode(screenshot.split(",", 1)[1])
        preview_frame = key, time.monotonic(), payload
        return payload


class PreviewHandler(BaseHTTPRequestHandler):
    def reply(self, status, body, mime="application/json"):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self'; img-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_clip(self, stream, *, active=None):
        if stream is None:
            self.reply(404, "{}")
            return
        with stream:
            size = os.fstat(stream.fileno()).st_size
            first, last = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", requested)
                if match and match[1]:
                    first = int(match[1])
                    last = min(last, int(match[2])) if match[2] else last
                elif match and match[2]:
                    first = max(0, size - int(match[2]))
                else:
                    first = size
                if first > last or size == 0:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", mimetypes.guess_type(stream.name)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(last - first + 1))
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if requested:
                self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            self.end_headers()
            stream.seek(first)
            remaining = last - first + 1
            try:
                while remaining and (active is None or active()):
                    block = stream.read(min(remaining, 1024**2))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                pass

    def serve_frame(self):
        try:
            payload = on_air_frame()
        except Exception:
            self.reply(503, "{}")
            return
        if payload is None:
            self.reply(404, "{}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            self.wfile.write(payload)

    def serve_on_air_media(self, path):
        match = re.fullmatch(r"/on-air-media/([a-f0-9]{32})/([0-9]{1,20})", path)
        if not match:
            self.reply(404, "{}")
            return
        clip_id, revision = match[1], int(match[2])

        def still_on_air():
            return (getattr(self.server, "active", True) and state["program"]
                    and state["current"] == clip_id and state["air_revision"] == revision
                    and state["status"] in {"Playing", "Paused"})

        with LOCK:
            stream = open_preview_clip(find_clip(clip_id)) if still_on_air() else None
        self.send_clip(stream, active=still_on_air)

    def log_message(self, *_args):
        pass


class Handler(PreviewHandler):
    def do_GET(self):
        if self.headers.get("Host") != HOST:
            self.reply(403, "{}")
        elif self.path == "/":
            self.reply(200, (ROOT / "dock.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html")
        elif self.path == "/clock":
            self.reply(200, (ROOT / "clock.html").read_text(encoding="utf-8"), "text/html")
        elif self.path == "/preview":
            self.reply(200, (ROOT / "preview.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html")
        elif self.path == "/preview-state":
            self.reply(200, json.dumps(local_preview_state()))
        elif self.path == "/on-air.js":
            self.reply(200, (ROOT / "on_air.js").read_text(encoding="utf-8"), "text/javascript")
        elif self.path.startswith("/on-air-media/"):
            self.serve_on_air_media(self.path)
        elif self.path.startswith("/clip/"):
            with LOCK:
                clip = find_clip(self.path.removeprefix("/clip/"))
                stream = open_preview_clip(clip)
            self.send_clip(stream)
        elif self.path.split("?", 1)[0] == "/frame":
            self.serve_frame()
        elif self.path == "/lan-monitor":
            if not hmac.compare_digest(self.headers.get("X-Rundown", "").encode(), TOKEN.encode()):
                self.reply(403, "{}")
            else:
                self.reply(200, json.dumps(lan_monitor_settings()))
        elif self.path == "/history.csv":
            with LOCK:
                payload = history_csv().encode("utf-8-sig")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="rundown-history.csv"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/backups":
            with LOCK:
                self.reply(200, json.dumps({"folder": str(BACKUPS), "files": list_backups()}))
        elif self.path == "/state":
            show_paths = hmac.compare_digest(self.headers.get("X-Rundown", ""), TOKEN)
            with LOCK:
                clips = [public_clip(clip) for clip in QUEUE]
                library, removed = [], []
                roots = explorer_roots() if show_paths else []
                for item in LIBRARY.values():
                    if item.get("removed"):
                        removed.append(public_library_clip(item, show_path=show_paths))
                    else:
                        library.append(public_library_clip(item, show_path=show_paths, roots=roots))
                self.reply(200, json.dumps(dict(
                    state, queue=clips, library=library, removed=removed,
                    lan_monitor_enabled=lan_monitor is not None,
                    folders=[{"path": str(root), "name": root.name or str(root), "registered": str(root) in FOLDERS}
                             for root in roots],
                    favorites=favorite_entries(roots) if show_paths else [],
                    file_operation=FILE_OPERATION if show_paths else {},
                    renames=[{"id": clip_id, "old_path": item["path"], "new_path": str(path)}
                             for clip_id, (item, path, _) in RENAME_SUGGESTIONS.items()] if show_paths else [],
                    history=HISTORY,
                    sample_age_ms=max(0, (time.monotonic() - sampled_at) * 1000) if sampled_at else 0,
                )))
        else:
            self.reply(404, "{}")

    def allowed(self):
        return (self.headers.get("Host") == HOST and self.headers.get("Origin") == ORIGIN
                and hmac.compare_digest(self.headers.get("X-Rundown", ""), TOKEN))

    def do_POST(self):
        if not self.allowed():
            self.reply(403, "{}")
            return
        self.connection.settimeout(30)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.path in {"/lan-monitor", "/cue-clock"} and 0 < length <= 2048:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Invalid request.")
                if self.path == "/lan-monitor":
                    self.reply(200, json.dumps(configure_lan_monitor(data)))
                else:
                    update_cue_clock(data)
                    self.reply(200, "{}")
                return
            elif self.path == "/restore-upload":
                if not 0 < length <= 64 * 1024**2:
                    raise ValueError("Select a rundown backup up to 64 MB.")
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise ValueError("Select a complete rundown backup.")
                import_backup_payload(payload)
            elif self.path in {"/pick-restore", "/restore-picked", "/search-missing"} and 0 < length <= 8192:
                data = json.loads(self.rfile.read(length))
                if self.path == "/pick-restore":
                    result = pick_backup()
                elif self.path == "/restore-picked":
                    restore_picked_backup(data.get("id"))
                    result = {}
                else:
                    path = pick_path("Choose a folder to search for missing videos", "folder")
                    result = search_missing_folder(path) if path else {"cancelled": True}
                self.reply(200, json.dumps(result))
                return
            elif self.path in {"/favorite-folder", "/file-operation", "/pick-file-destination", "/link-file"} and 0 < length <= 8192:
                data = json.loads(self.rfile.read(length))
                if self.path == "/favorite-folder":
                    result = set_favorite(data)
                elif self.path == "/file-operation":
                    result = start_file_operation(data)
                elif self.path == "/pick-file-destination":
                    clip_id = data.get("id")
                    with LOCK:
                        item = LIBRARY.get(clip_id) if isinstance(clip_id, str) else None
                        if not item:
                            raise ValueError("Select a clip before choosing a destination.")
                        parent = Path(item["path"]).parent
                    result = {"path": pick_path(
                        "Choose a destination folder", "folder",
                        initial_folder=parent if parent.is_dir() else None,
                    )}
                else:
                    name = data.get("name", "")
                    name = "".join(char for char in name[:160] if char.isprintable()) if isinstance(name, str) else ""
                    label = "Link video" + (" - " + name if name else "")
                    path = pick_path(label, "video")
                    result = link_single_file(path) if path else {"cancelled": True}
                self.reply(200, json.dumps(result))
                return
            elif self.path == "/restore-removed" and 0 < length <= 4 * 1024**2:
                data = json.loads(self.rfile.read(length))
                count = restore_removed_clips(data.get("ids"))
                self.reply(200, json.dumps({"restored": count}))
                return
            elif self.path == "/confirm-file-rename" and 0 < length <= 8192:
                data = json.loads(self.rfile.read(length))
                confirm_external_rename(data.get("id"), data.get("path"))
            elif self.path in {"/browse-folder", "/register-folder", "/unlink-folder", "/refresh-folder", "/rename-folder"} and 0 < length <= 8192:
                data = json.loads(self.rfile.read(length))
                root, parts = data.get("root"), data.get("parts")
                if self.path == "/browse-folder":
                    result = browse_folder(root, parts)
                elif self.path == "/register-folder":
                    result = register_saved_folder(root)
                elif self.path == "/unlink-folder":
                    result = unlink_folder(root)
                elif self.path == "/refresh-folder":
                    if not isinstance(parts, list):
                        raise ValueError("Select a linked folder.")
                    result = import_folder(root, parts=parts)
                else:
                    result = rename_linked_folder(root, parts, data.get("name"))
                self.reply(200, json.dumps(result))
                return
            elif self.path in {"/link-folder", "/locate-linked"} and 0 < length <= 8192:
                data = json.loads(self.rfile.read(length))
                if self.path == "/link-folder":
                    name = data.get("name", "")
                    name = "".join(char for char in name[:180] if char.isprintable()) if isinstance(name, str) else ""
                    label = f"Link folder: {name}" if name else ""
                    path = pick_path(label or "Link video folder", "folder")
                    result = import_folder(path) if path else {"cancelled": True}
                else:
                    clip_id = data.get("id")
                    with LOCK:
                        item = LIBRARY.get(clip_id) if isinstance(clip_id, str) else None
                        if not item or media_status(item) != "missing":
                            raise ValueError("Select a missing clip.")
                        parent = Path(item["path"]).parent
                    extensions = FORMATS if item.get("linked") else {Path(item["path"]).suffix.lower()}
                    chosen = pick_path("Reconnect missing video", "video", extensions=extensions,
                                       initial_folder=parent if parent.is_dir() else None)
                    if not chosen:
                        self.reply(200, json.dumps({"cancelled": True}))
                        return
                    reconnect_picked_video(item, local_path(chosen).resolve())
                    result = {}
                self.reply(200, json.dumps(result))
                return
            elif self.path in {"/export-csv", "/backup-json"}:
                with LOCK:
                    item = create_backup("csv" if self.path == "/export-csv" else "json")
                self.reply(200, json.dumps(item))
                return
            elif self.path == "/action" and 0 < length <= 8192:
                with LOCK:
                    action(json.loads(self.rfile.read(length)))
                    state["error"] = ""
            else:
                raise ValueError("Invalid request.")
            self.reply(200, "{}")
        except ValueError as exc:
            self.reply(400, json.dumps({"error": str(exc)}))
        except Exception:
            self.reply(503, json.dumps({"error": "OBS or local storage is unavailable. Check the connection and available disk space."}))


class LANMonitorHandler(PreviewHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def do_GET(self):
        address, port = self.server.server_address
        if not self.server.active or self.headers.get("Host") != f"{address}:{port}":
            self.reply(403, "{}")
            return
        supplied = self.headers.get("Authorization", "").encode("latin-1")
        status, retry = self.server.check_authorization(self.client_address[0], supplied)
        if status != 200:
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            body = b""
            if status == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="Rundown LAN Monitor"')
            else:
                self.send_header("Retry-After", str(retry))
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                body = f"Too many incorrect access codes. Try again in {retry} seconds.".encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        path = self.path.split("?", 1)[0]
        if path in {"/", "/preview"}:
            self.reply(200, (ROOT / "lan_monitor.html").read_text(encoding="utf-8"), "text/html")
        elif path == "/on-air.js":
            self.reply(200, (ROOT / "on_air.js").read_text(encoding="utf-8"), "text/javascript")
        elif path == "/state":
            self.reply(200, json.dumps(monitor_state()))
        elif path == "/frame":
            self.serve_frame()
        elif path.startswith("/on-air-media/"):
            self.serve_on_air_media(path)
        elif match := re.fullmatch(r"/cue/([a-f0-9]{32})/([0-9]{1,20})", path):
            with LOCK:
                clip = current_cue()
                revision = state.get("cue_revision", 0)
                stream = (open_preview_clip(clip) if clip and clip["id"] == match[1]
                          and revision == int(match[2]) else None)
            self.send_clip(stream, active=lambda: self.server.active and state.get("cue_revision", 0) == revision)
        else:
            self.reply(404, "{}")


class LANMonitorServer(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"
    allow_reuse_port = False

    def __init__(self, address, password):
        self.password = password
        self.authorization = b"Basic " + base64.b64encode(f"rundown:{password}".encode("ascii"))
        self.auth_lock = threading.Lock()
        self.auth_failures = OrderedDict()
        self.active = True
        self.connections = threading.BoundedSemaphore(16)
        super().__init__((address, LAN_MONITOR_PORT), LANMonitorHandler)

    def check_authorization(self, address, supplied):
        if not supplied:
            return 401, 0
        with self.auth_lock:
            now = time.monotonic()
            failures, deadline = self.auth_failures.get(address, (0, now + 60))
            if now >= deadline:
                failures, deadline = 0, now + 60
            if failures >= 5:
                return 429, math.ceil(deadline - now)
            if hmac.compare_digest(supplied, self.authorization):
                return 200, 0
            self.auth_failures[address] = failures + 1, deadline
            self.auth_failures.move_to_end(address)
            if len(self.auth_failures) > 256:
                self.auth_failures.popitem(last=False)
        return 401, 0

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def monitor_address(value):
    if isinstance(value, str):
        with suppress(ValueError):
            address = IPv4Address(value.strip())
            if any(address in network for network in LAN_NETWORKS):
                return str(address)
    raise ValueError("Enter the OBS computer’s private LAN IPv4 address, such as 192.168.1.50.")


def detect_monitor_addresses():
    candidates = []
    with suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # Ask the routing table for its preferred IPv4 interface without sending data.
            probe.connect(("192.0.2.1", 9))
            candidates.append(probe.getsockname()[0])
    if sys.platform == "darwin":
        with suppress(OSError, subprocess.SubprocessError):
            interfaces = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True,
                                        timeout=2, check=True).stdout
            candidates.extend(re.findall(r"(?m)^\s+inet ([0-9.]+)\s", interfaces))
    else:
        with suppress(OSError):
            candidates.extend(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    addresses = []
    for candidate in dict.fromkeys(candidates):
        with suppress(ValueError, OSError):
            address = monitor_address(candidate)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as socket_check:
                socket_check.bind((address, 0))
            addresses.append(address)
    return addresses


def generate_monitor_code():
    return "".join(secrets.choice(LAN_CODE_CHARACTERS) for _ in range(4))


def bind_lan_monitor(address, password):
    try:
        return LANMonitorServer(address, password)
    except OSError as exc:
        raise ValueError(f"Could not listen on {address}:{LAN_MONITOR_PORT}. Check the local IPv4 address and whether the port is in use.") from exc


def start_lan_monitor(server):
    global lan_monitor
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True).start()
    lan_monitor = server


def stop_lan_monitor():
    global lan_monitor
    server = lan_monitor
    if server is not None:
        server.active = False
        lan_monitor = None
        server.shutdown()
        server.server_close()
    with LOCK:
        cue_clock.clear()


def restore_lan_monitor():
    global lan_monitor_error
    try:
        config = json.loads(LAN_MONITOR_FILE.read_bytes())
        if config is None:
            return
        address, password = monitor_address(config["address"]), config["password"]
        legacy_password = isinstance(password, str) and re.fullmatch(r"[a-zA-Z0-9_-]{24}", password)
        if legacy_password:
            password = generate_monitor_code()
        elif not isinstance(password, str) or len(password) != 4 or any(char not in LAN_CODE_CHARACTERS for char in password):
            raise ValueError("Invalid LAN monitor access code.")
        server = bind_lan_monitor(address, password)
        try:
            if legacy_password:
                save_json(LAN_MONITOR_FILE, dict(address=address, password=password))
            start_lan_monitor(server)
        except Exception:
            server.server_close()
            raise
    except FileNotFoundError:
        pass
    except (TypeError, KeyError, ValueError, OSError) as exc:
        lan_monitor_error = f"LAN monitor could not start. {exc}"
        print(lan_monitor_error, flush=True)


def lan_monitor_settings():
    with LAN_LOCK:
        server = lan_monitor
        error = lan_monitor_error
        if server is not None:
            address, port = server.server_address
            return dict(enabled=True, address=address, url=f"http://{address}:{port}/preview",
                        username="rundown", password=server.password)
    return dict(enabled=False, error=error, addresses=detect_monitor_addresses())


def configure_lan_monitor(data):
    global lan_monitor_error
    with LAN_LOCK:
        if data.get("enabled") is False:
            save_json(LAN_MONITOR_FILE, None)
            stop_lan_monitor()
        elif data.get("enabled") is True:
            address = monitor_address(data.get("address"))
            if lan_monitor is not None:
                if address != lan_monitor.server_address[0]:
                    raise ValueError("Disable the LAN monitor before changing its address.")
            else:
                password = generate_monitor_code()
                server = bind_lan_monitor(address, password)
                try:
                    save_json(LAN_MONITOR_FILE, dict(address=address, password=password))
                    start_lan_monitor(server)
                except Exception:
                    server.server_close()
                    raise
        else:
            raise ValueError("Choose whether to enable the LAN monitor.")
        lan_monitor_error = ""
    return lan_monitor_settings()


def main(stop=None):
    with ThreadingHTTPServer(("127.0.0.1", 46643), Handler) as server:
        load_rundown()
        threading.Thread(target=poll, daemon=True).start()
        threading.Thread(target=scan_library_metadata, daemon=True).start()
        threading.Thread(target=watch_folder_changes, daemon=True).start()
        print("OBS Video Rundown running at " + ORIGIN, flush=True)
        restore_lan_monitor()
        try:
            if stop is None:
                server.serve_forever()
            else:
                server.timeout = 0.25
                while not stop.is_set():
                    server.handle_request()
        finally:
            with LAN_LOCK:
                stop_lan_monitor()


def load_rundown():
    CACHE.mkdir(parents=True, exist_ok=True)
    if LIBRARY_FILE.exists():
        for media_id, item in json.loads(LIBRARY_FILE.read_text(encoding="utf-8")).items():
            path = (local_path(item["path"]) if item.get("linked")
                    else cache_path(media_id, item))
            if re.fullmatch(r"[a-f0-9]{32}", media_id):
                LIBRARY[media_id] = dict(item, id=media_id, path=str(path))
    if FOLDERS_FILE.exists():
        FOLDERS[:] = saved_roots(json.loads(FOLDERS_FILE.read_bytes()))
    if FAVORITES_FILE.exists():
        FAVORITES[:] = saved_roots(json.loads(FAVORITES_FILE.read_bytes()))
    recover_folder_rename()
    recover_file_change()
    migrate_unlinked_records(LIBRARY, FOLDERS)
    if QUEUE_FILE.exists():
        for clip in json.loads(QUEUE_FILE.read_text(encoding="utf-8")):
            if clip.get("marker"):
                QUEUE.append(dict(id=clip["id"], marker=True))
                continue
            media_id = clip.get("media_id", clip["id"])
            path = Path(LIBRARY[media_id]["path"]) if media_id in LIBRARY else CACHE / (media_id + Path(clip["name"]).suffix.lower())
            if not re.fullmatch(r"[a-f0-9]{32}", media_id) or media_id not in LIBRARY and not path.is_file():
                continue
            LIBRARY.setdefault(media_id, dict(id=media_id, name=clip["name"], path=str(path)))
            if not clip.get("played"):
                QUEUE.append(dict(clip, media_id=media_id, path=str(path)))
    save_json(LIBRARY_FILE, LIBRARY)
    if CATEGORIES_FILE.exists():
        CATEGORIES.extend(json.loads(CATEGORIES_FILE.read_text(encoding="utf-8")))
    register_categories(category for clip in LIBRARY.values() for category in clip.get("categories", []))
    restore_preferences_and_history()


if __name__ == "__main__":
    main()

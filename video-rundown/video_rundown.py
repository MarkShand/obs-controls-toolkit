"""Local OBS video rundown. Install obsws-python before launching."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
import base64
import csv
import io
from datetime import datetime
import mimetypes
import re
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
import math
import threading
import time
import uuid

import obsws_python

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "video-cache"
BACKUPS = ROOT / "backups"
HOST = "127.0.0.1:46643"
ORIGIN = "http://" + HOST
SCENE = "Video Rundown"
SOURCE = "Rundown Player"
FORMATS = {".mp4", ".ts", ".mov", ".flv", ".mkv", ".avi", ".gif", ".webm"}
METADATA_VERSION = 2
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
CATEGORIES = []
state = dict(ready=False, program=False, current=None, auto=False, auto_cut="off", preview=None, return_ready=False, status="Idle", cursor=0, duration=0, error="")
client = None
armed = False
started = 0.0
sampled_at = 0.0


def save_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data), encoding="utf-8")
    temp.replace(path)


def register_categories(names):
    by_name = {name.casefold(): name for name in CATEGORIES}
    for name in names:
        by_name.setdefault(name.casefold(), name)
    updated = list(by_name.values())
    if updated != CATEGORIES:
        save_json(CATEGORIES_FILE, updated)
        CATEGORIES[:] = updated


def save_queue():
    save_json(QUEUE_FILE, QUEUE)


def find_clip(clip_id):
    item = LIBRARY.get(clip_id)
    active_item = item if item and not item.get("removed") else None
    return next((clip for clip in QUEUE if clip["id"] == clip_id), active_item)


def cue(clip_id):
    state.update(cue=clip_id, cue_revision=state.get("cue_revision", 0) + 1)


def clip_title(clip):
    media = LIBRARY.get(clip.get("media_id", clip["id"]), {})
    return media.get("title") or clip.get("title") or clip["name"]


def restore_preferences_and_history():
    if SETTINGS_FILE.exists():
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        state["auto"] = settings.get("auto") is True
        if settings.get("auto_cut") in {"off", "clip", "rundown"}:
            state["auto_cut"] = settings["auto_cut"]
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


def public_clip(clip):
    if clip.get("marker"):
        return dict(id=clip["id"], name="Stop & Re-cue", marker=True)
    return dict(id=clip["id"], name=clip_title(clip),
                media_id=clip.get("media_id", clip["id"]),
                duration_ms=LIBRARY.get(clip.get("media_id", clip["id"]), {}).get("duration_ms", 0),
                played=clip.get("played", False))


def scan_library_metadata():
    import av

    attempted = set()
    while True:
        with LOCK:
            item = next((clip for clip in LIBRARY.values()
                         if not clip.get("removed") and clip["id"] not in attempted
                         and clip.get("metadata_version") != METADATA_VERSION and Path(clip["path"]).is_file()), None)
        if item is None:
            time.sleep(1)
            continue
        attempted.add(item["id"])
        path = Path(item["path"])
        metadata = {"format": path.suffix[1:].upper()}
        duration_ms = 0
        try:
            stat = path.stat()
            metadata["size_bytes"] = stat.st_size
            metadata["modified_at"] = item.get("source_modified_at", stat.st_mtime)
            created_at = getattr(stat, "st_birthtime", None)
            if created_at is not None:
                metadata["created_at"] = created_at
            metadata["cached_modified"] = "source_modified_at" not in item
            with av.open(str(path), timeout=5) as media:
                video = next(iter(media.streams.video), None)
                if video:
                    metadata.update(width=video.width, height=video.height,
                                    codec=video.codec_context.name)
                    if video.average_rate:
                        metadata["fps"] = round(float(video.average_rate), 3)
                if media.duration and media.duration > 0:
                    duration_ms = round(media.duration * 1000 / av.time_base)
        except (OSError, av.error.FFmpegError):
            pass
        with LOCK:
            if LIBRARY.get(item["id"]) is item:
                item["metadata"] = metadata
                item["metadata_version"] = METADATA_VERSION
                if duration_ms and not item.get("duration_ms"):
                    item["duration_ms"] = duration_ms
                try:
                    save_json(LIBRARY_FILE, LIBRARY)
                except OSError:
                    pass


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
            connection = sqlite3.connect(temporary)
            try:
                with connection:
                    connection.execute("PRAGMA user_version = 2")
                    connection.execute("CREATE TABLE library (id TEXT PRIMARY KEY, name TEXT, title TEXT, duration_ms INTEGER, removed INTEGER NOT NULL)")
                    connection.executemany("INSERT INTO library VALUES (?, ?, ?, ?, ?)",
                        [(item["id"], item["name"], clip_title(item), item.get("duration_ms"), int(bool(item.get("removed")))) for item in LIBRARY.values()])
                    connection.execute("CREATE TABLE library_details (id TEXT PRIMARY KEY, metadata TEXT, source_modified_at REAL)")
                    connection.executemany("INSERT INTO library_details VALUES (?, ?, ?)",
                        [(item["id"], json.dumps(item.get("metadata")), item.get("source_modified_at")) for item in LIBRARY.values()])
                    connection.execute("CREATE TABLE categories (name TEXT PRIMARY KEY)")
                    connection.executemany("INSERT INTO categories VALUES (?)", [(name,) for name in CATEGORIES])
                    connection.execute("CREATE TABLE clip_categories (media_id TEXT, category TEXT, PRIMARY KEY (media_id, category))")
                    connection.executemany("INSERT INTO clip_categories VALUES (?, ?)",
                        [(item["id"], category) for item in LIBRARY.values() for category in item.get("categories", [])])
                    connection.execute("CREATE TABLE playlist (position INTEGER PRIMARY KEY, id TEXT, media_id TEXT, title TEXT, marker INTEGER, played INTEGER)")
                    connection.executemany("INSERT INTO playlist VALUES (?, ?, ?, ?, ?, ?)",
                        [(i, item["id"], None if item.get("marker") else item.get("media_id", item["id"]),
                          None if item.get("marker") else clip_title(item), bool(item.get("marker")), bool(item.get("played")))
                         for i, item in enumerate(QUEUE, 1)])
                    connection.execute("CREATE TABLE history (clip TEXT, started_epoch REAL, ended_epoch REAL, result TEXT)")
                    connection.executemany("INSERT INTO history VALUES (?, ?, ?, ?)",
                        [(item["name"], item["started"], item["ended"], item["result"]) for item in HISTORY])
                    connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
                    connection.executemany("INSERT INTO settings VALUES (?, ?)",
                        [(key, json.dumps(state.get(key))) for key in ("auto", "auto_cut", "next_cue")] +
                        [("created_at", datetime.now().astimezone().isoformat())])
            finally:
                connection.close()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"name": name, "path": str(path)}


def restore_backup(path):
    if state["current"]:
        raise ValueError("Stop the rundown before restoring a backup.")
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

    if LIBRARY or QUEUE or HISTORY or CATEGORIES:
        create_backup("sqlite")
    updates = [(LIBRARY_FILE, library), (QUEUE_FILE, queue), (HISTORY_FILE, history),
               (CATEGORIES_FILE, categories), (SETTINGS_FILE, settings)]
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
    LIBRARY.clear()
    LIBRARY.update(library)
    QUEUE[:] = queue
    HISTORY[:] = history
    CATEGORIES[:] = categories
    state.update(settings, return_ready=False, handoff="")
    cue(None)


def list_backups():
    return [{"name": path.name, "size": path.stat().st_size} for path in
            sorted(BACKUPS.glob("rundown-*"), reverse=True)
            if path.is_file() and path.suffix in {".csv", ".sqlite"}]


def obs_settings():
    if os.name == "nt":
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


def setup():
    c = obs()
    if not any(item["sceneName"] == SCENE for item in c.get_scene_list().scenes):
        c.create_scene(SCENE)
    existing = next((item for item in c.get_input_list().inputs if item["inputName"] == SOURCE), None)
    if existing and existing["inputKind"] != "ffmpeg_source":
        raise ValueError("A different source already uses the name Rundown Player.")
    items = c.get_scene_item_list(SCENE).scene_items
    if not existing:
        c.create_input(SCENE, SOURCE, "ffmpeg_source", {"is_local_file": True}, True)
    elif not any(item["sourceName"] == SOURCE for item in items):
        c.create_scene_item(SCENE, SOURCE, True)
    item = next(item for item in c.get_scene_item_list(SCENE).scene_items if item["sourceName"] == SOURCE)
    video = c.get_video_settings()
    c.set_scene_item_transform(SCENE, item["sceneItemId"], {
        "positionX": 0, "positionY": 0, "alignment": 5,
        "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 0,
        "boundsWidth": video.base_width, "boundsHeight": video.base_height,
    })
    state["ready"] = True


def play(clip):
    if not Path(clip["path"]).is_file():
        raise ValueError("This video is missing. Reconnect it in Backups.")
    global armed, started
    c = obs()
    if c.get_current_program_scene().current_program_scene_name != SCENE:
        raise ValueError("Put Video Rundown on Program before playing a clip.")
    log_playback("Replaced")
    armed = False
    state.update(return_ready=False, handoff="")
    c.set_input_settings(SOURCE, {
        "is_local_file": True, "local_file": clip["path"], "looping": False,
        "restart_on_activate": False, "close_when_inactive": False,
        "clear_on_media_end": True,
    }, True)
    c.trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")
    clip["played"] = False
    save_queue()
    state.update(current=clip["id"], status="Loading", cursor=0, duration=0,
                 air_started=None, schedule_anchor=None, next_cue=None)
    started = time.monotonic()


def current_index():
    return next((i for i, clip in enumerate(QUEUE) if clip["id"] == state["current"]), -1)


def cut_to_preview():
    if not state["return_ready"]:
        raise ValueError("Wait for the rundown clip to finish before cutting.")
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
        state.update(return_ready=False, program=False, current=None, status="Idle",
                     cursor=0, duration=0, error="", handoff=f"Cut to {preview}.")
    finally:
        try:
            if triggered:
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    time.sleep(.05)
                    if c.get_current_program_scene().current_program_scene_name == preview:
                        # Let OBS finish its queued transition-stop updates.
                        time.sleep(.2)
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
    return next((clip for clip in QUEUE[after + 1:] if not clip.get("played") and not clip.get("marker")), None)


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
    clip = find_clip(state.get("next_cue")) or next_pending()
    if clip:
        try:
            play(clip)
            state["error"] = ""
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
                if not state["ready"] and any(item["sceneName"] == SCENE for item in scenes.scenes):
                    state["ready"] = any(item["sourceName"] == SOURCE
                                         for item in c.get_scene_item_list(SCENE).scene_items)
                if not state["program"]:
                    state["return_ready"] = False
                last_program = previous_program
                previous_program = scenes.current_program_scene_name
                start_on_program(last_program, previous_program)
                if not state["current"]:
                    continue
                previous_status = state["status"]
                media = c.get_media_input_status(SOURCE)
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
                if not state["program"]:
                    log_playback("Taken off air")
                    armed = False
                    c.trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP")
                    state.update(current=None, status="Stopped", cursor=0, duration=0)
                elif status == "Ended" and previous_status != "Ended" and (armed or state["duration"] > 0):
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
    global armed
    cmd = data.get("action")
    if cmd == "restore_backup":
        name = data.get("name", "")
        if not isinstance(name, str) or name not in {item["name"] for item in list_backups() if item["name"].endswith(".sqlite")}:
            raise ValueError("Select a SQLite backup from the Backups tab.")
        restore_backup(BACKUPS / name)
        return
    if cmd == "cue":
        clip = find_clip(data.get("id"))
        cue(clip["id"] if clip and not clip.get("marker") else None)
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
        clip = dict(item, id=uuid.uuid4().hex, media_id=item["id"], played=False)
        target = next((i for i, row in enumerate(QUEUE) if row["id"] == data.get("target")), len(QUEUE))
        position = min(len(QUEUE), target + (1 if data.get("after") is True else 0))
        QUEUE.insert(position, clip)
        save_queue()
        return
    if cmd in {"remove_media", "restore_media", "trash_media"}:
        item = LIBRARY.get(data.get("id"))
        if not item or bool(item.get("removed")) != (cmd != "remove_media"):
            raise ValueError("This clip has already been moved or removed.")
        if any(row.get("media_id", row["id"]) == item["id"] for row in QUEUE if not row.get("marker")):
            raise ValueError("Remove this clip from the Playlist before removing it from the library.")
        if cmd == "trash_media":
            try:
                from send2trash import send2trash
                send2trash(item["path"])
            except (ImportError, OSError) as exc:
                raise ValueError("Could not move this clip to the system Trash or Recycle Bin.") from exc
            del LIBRARY[item["id"]]
            save_json(LIBRARY_FILE, LIBRARY)
        else:
            previous = item.get("removed", False)
            item["removed"] = cmd == "remove_media"
            try:
                save_json(LIBRARY_FILE, LIBRARY)
            except OSError:
                item["removed"] = previous
                raise
        if cmd == "remove_media" and state.get("cue") == item["id"]:
            cue(None)
        return
    if cmd in {"rename_category", "delete_category"}:
        old_name = data.get("category")
        if old_name not in CATEGORIES:
            raise ValueError("This category no longer exists.")
        new_name = category_name(data.get("title")) if cmd == "rename_category" else None
        if new_name and any(name != old_name and name.casefold() == new_name.casefold() for name in CATEGORIES):
            raise ValueError("A category with that name already exists.")
        updated_names = [name if name != old_name else new_name for name in CATEGORIES
                         if name != old_name or new_name is not None]
        updated_library = {}
        for clip_id, clip in LIBRARY.items():
            names = clip.get("categories", [])
            if any(name.casefold() == old_name.casefold() for name in names):
                updated = [name for name in names if name.casefold() != old_name.casefold()]
                if new_name is not None:
                    updated.append(new_name)
                clip = dict(clip, categories=updated)
            updated_library[clip_id] = clip
        save_json(CATEGORIES_FILE, updated_names)
        try:
            save_json(LIBRARY_FILE, updated_library)
        except OSError:
            save_json(CATEGORIES_FILE, CATEGORIES)
            raise
        CATEGORIES[:] = updated_names
        LIBRARY.update(updated_library)
        return
    if cmd in {"create_category", "add_category", "remove_category"}:
        name = category_name(data.get("category"))
        names = [*CATEGORIES, *(category for clip in LIBRARY.values() for category in clip.get("categories", []))]
        matching = next((category for category in names if category.casefold() == name.casefold()), name)
        if cmd == "create_category":
            register_categories([matching])
            return
        item = LIBRARY.get(data.get("id"))
        if not item or item.get("removed"):
            raise ValueError("Select an active clip from the File Library.")
        previous = item.get("categories", [])
        categories = [category for category in previous if category.casefold() != matching.casefold()]
        if cmd == "add_category":
            register_categories([matching])
            categories.append(matching)
        elif len(categories) != len(previous):
            register_categories([matching])
        item["categories"] = categories
        try:
            save_json(LIBRARY_FILE, LIBRARY)
        except OSError:
            item["categories"] = previous
            raise
        return
    if cmd == "rename":
        clip = LIBRARY.get(data.get("id"))
        if clip is None:
            raise ValueError("Select a file from the library.")
        title = data.get("title")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160 or any(ord(char) < 32 for char in title):
            raise ValueError("Enter a clip name between 1 and 160 characters.")
        previous = clip.get("title")
        clip["title"] = title.strip()
        try:
            save_json(LIBRARY_FILE, LIBRARY)
        except OSError:
            if previous is None:
                del clip["title"]
            else:
                clip["title"] = previous
            raise
        return
    if cmd == "setup":
        setup()
        return
    if cmd in {"auto", "auto_cut"}:
        value = bool(data.get("value")) if cmd == "auto" else data.get("value")
        if cmd == "auto_cut" and value not in {"off", "clip", "rundown"}:
            raise ValueError("Choose an auto-cut mode.")
        settings = {key: state[key] for key in ("auto", "auto_cut")}
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
        state.update(cursor=position, schedule_anchor=time.time() + (duration - position) / 1000)
        return
    if cmd in {"pause", "resume", "stop"}:
        if not state["current"]:
            return
        obs().trigger_media_input_action(SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_" + {
            "pause": "PAUSE", "resume": "PLAY", "stop": "STOP",
        }[cmd])
        if cmd == "stop":
            log_playback("Stopped")
            if current_index() >= 0:
                state["next_cue"] = state["current"]
            armed = False
            state.update(current=None, status="Stopped", cursor=0, duration=0, return_ready=False)
        return
    if cmd == "next":
        clip = find_clip(state.get("next_cue")) if state.get("next_cue") else None
        clip = clip or next_pending(current_index())
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


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, mime="application/json"):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; media-src 'self'; img-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_clip(self, clip_id):
        with LOCK:
            clip = find_clip(clip_id)
            try:
                stream = Path(clip["path"]).open("rb") if clip and not clip.get("marker") else None
            except OSError:
                stream = None
        if stream is None:
            self.reply(404, "{}")
            return
        with stream:
            size = os.fstat(stream.fileno()).st_size
            first, last = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if match and match[1]:
                    first = int(match[1])
                    last = min(last, int(match[2])) if match[2] else last
                elif match and match[2]:
                    first = max(0, size - int(match[2]))
                else:
                    first = size
                if first > last:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", mimetypes.guess_type(clip["path"])[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(last - first + 1))
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if requested:
                self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            self.end_headers()
            stream.seek(first)
            remaining = last - first + 1
            try:
                while remaining:
                    block = stream.read(min(remaining, 1024**2))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        if self.headers.get("Host") != HOST:
            self.reply(403, "{}")
        elif self.path == "/":
            self.reply(200, (ROOT / "dock.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html")
        elif self.path == "/clock":
            self.reply(200, (ROOT / "clock.html").read_text(encoding="utf-8"), "text/html")
        elif self.path == "/preview":
            self.reply(200, (ROOT / "preview.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html")
        elif self.path.startswith("/clip/"):
            self.serve_clip(self.path.removeprefix("/clip/"))
        elif self.path == "/frame":
            try:
                with LOCK:
                    if not state["program"] or state["status"] not in {"Playing", "Paused"}:
                        self.reply(404, "{}")
                        return
                    screenshot = obs().get_source_screenshot(SOURCE, "jpg", 480, 270, 70).image_data
                payload = base64.b64decode(screenshot.split(",", 1)[1])
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.reply(503, "{}")
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
            with LOCK:
                clips = [public_clip(clip) for clip in QUEUE]
                self.reply(200, json.dumps(dict(state, queue=clips, categories=CATEGORIES, library=[dict(public_clip(item), categories=item.get("categories", []), missing=not Path(item["path"]).is_file(), original_name=item["name"], metadata={"format": Path(item["name"]).suffix[1:].upper(), **(item.get("metadata") or {})}) for item in LIBRARY.values() if not item.get("removed")], removed=[dict(public_clip(item), missing=not Path(item["path"]).is_file(), original_name=item["name"]) for item in LIBRARY.values() if item.get("removed")], history=HISTORY, sample_age_ms=max(0, (time.monotonic() - sampled_at) * 1000) if sampled_at else 0)))
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
            if self.path == "/restore-upload":
                if not 0 < length <= 64 * 1024**2:
                    raise ValueError("Select a SQLite backup up to 64 MB.")
                payload = self.rfile.read(length)
                if len(payload) != length or not payload.startswith(b"SQLite format 3\x00"):
                    raise ValueError("Select a complete SQLite backup.")
                BACKUPS.mkdir(exist_ok=True)
                temporary = BACKUPS / ("restore-" + uuid.uuid4().hex + ".tmp")
                try:
                    temporary.write_bytes(payload)
                    with LOCK:
                        restore_backup(temporary)
                        temporary.replace(BACKUPS / ("rundown-imported-" + uuid.uuid4().hex[:12] + ".sqlite"))
                finally:
                    temporary.unlink(missing_ok=True)
            elif self.path == "/relink":
                clip_id = self.headers.get("X-Clip-ID", "")
                name = unquote(self.headers.get("X-Clip-Name", ""))
                with LOCK:
                    item = LIBRARY.get(clip_id)
                    if not item or Path(item["path"]).exists():
                        raise ValueError("The selected clip is no longer missing.")
                    path = Path(item["path"])
                if Path(name).suffix.lower() != path.suffix.lower() or not 0 < length <= 4 * 1024**3:
                    raise ValueError("Choose a video with the original file format, up to 4 GB.")
                temporary = CACHE / (uuid.uuid4().hex + ".tmp")
                try:
                    with temporary.open("xb") as stream:
                        remaining = length
                        while remaining:
                            block = self.rfile.read(min(remaining, 1024**2))
                            if not block:
                                raise ValueError("The file transfer was interrupted.")
                            stream.write(block)
                            remaining -= len(block)
                    with LOCK:
                        if LIBRARY.get(clip_id) is not item or path.exists():
                            raise ValueError("The selected clip changed during the transfer.")
                        temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            elif self.path == "/upload":
                name = unquote(self.headers.get("X-Clip-Name", ""))
                extension = Path(name).suffix.lower()
                if extension not in FORMATS:
                    raise ValueError("This file type is not listed for OBS Media Source.")
                if not 0 < length <= 4 * 1024**3:
                    raise ValueError("Clips must be between 1 byte and 4 GB.")
                clip_id = uuid.uuid4().hex
                path = CACHE / (clip_id + extension)
                try:
                    with path.open("xb") as stream:
                        remaining = length
                        while remaining:
                            block = self.rfile.read(min(remaining, 1024**2))
                            if not block:
                                raise ValueError("The file transfer was interrupted.")
                            stream.write(block)
                            remaining -= len(block)
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                with LOCK:
                    item = dict(id=clip_id, name=name, path=str(path))
                    modified = self.headers.get("X-Clip-Modified", "")
                    if modified.isascii() and modified.isdecimal() and len(modified) <= 15:
                        item["source_modified_at"] = int(modified) / 1000
                    LIBRARY[clip_id] = item
                    save_json(LIBRARY_FILE, LIBRARY)
            elif self.path in {"/export-csv", "/backup-sqlite"}:
                with LOCK:
                    item = create_backup("csv" if self.path == "/export-csv" else "sqlite")
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

    def log_message(self, *_args):
        pass


def main():
    CACHE.mkdir(exist_ok=True)
    if LIBRARY_FILE.exists():
        for media_id, item in json.loads(LIBRARY_FILE.read_text(encoding="utf-8")).items():
            path = CACHE / (media_id + Path(item["name"]).suffix.lower())
            if re.fullmatch(r"[a-f0-9]{32}", media_id):
                LIBRARY[media_id] = dict(item, id=media_id, path=str(path))
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
    with ThreadingHTTPServer(("127.0.0.1", 46643), Handler) as server:
        threading.Thread(target=poll, daemon=True).start()
        threading.Thread(target=scan_library_metadata, daemon=True).start()
        print("OBS Video Rundown running at " + ORIGIN, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

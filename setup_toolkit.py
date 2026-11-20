"""Install or uninstall the toolkit in a closed OBS Studio installation."""

import argparse
from collections import Counter
import configparser
from datetime import datetime
import ipaddress
import json
import os
import re
from pathlib import Path, PureWindowsPath
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid


ROOT = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
HOTKEYS = "obs-hotkey-toggle.lua"
TRACKING = "fomako-tracking.lua"
INSTALL_RECORD = "obs-controls-toolkit-install.json"
DOCKS = {
    "OBS Controls": "http://127.0.0.1:46642/",
    "Video Rundown": "http://127.0.0.1:46643/",
    "Rundown Preview": "http://127.0.0.1:46643/preview",
    "Production Clock": "http://127.0.0.1:46643/clock",
}


def default_config():
    if WINDOWS:
        return Path(os.environ["APPDATA"]) / "obs-studio"
    return Path.home() / "Library/Application Support/obs-studio"


def require_obs_closed():
    if WINDOWS:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "if (Get-Process -Name obs64,obs32,obs -ErrorAction SilentlyContinue) { exit 1 }; exit 0"],
            capture_output=True,
        )
    else:
        result = subprocess.run(["/usr/bin/pgrep", "-x", "OBS"], capture_output=True)
    if result.returncode not in (0, 1) or result.stderr:
        raise OSError("Could not check whether OBS is open.")
    running = result.returncode == (1 if WINDOWS else 0)
    if running:
        raise ValueError("OBS Studio is open. Quit OBS completely, then run this command again.")


def read_docks(original):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(original.decode("utf-8-sig"))
    docks = json.loads(parser.get("BasicWindow", "ExtraBrowserDocks", fallback="[]"))
    if not isinstance(docks, list) or any(not isinstance(dock, dict) for dock in docks):
        raise ValueError("OBS's Custom Browser Docks list could not be read.")
    return parser, docks


def add_docks(docks):
    existing_urls = {str(dock.get("url", "")).rstrip("/") for dock in docks}
    titles = {str(dock.get("title", "")).casefold() for dock in docks}
    added = []
    for title, url in DOCKS.items():
        if url.rstrip("/") in existing_urls:
            continue
        name = title
        suffix = 1
        while name.casefold() in titles:
            name = f"{title} (Toolkit{f' {suffix}' if suffix > 1 else ''})"
            suffix += 1
        dock = dict(title=name, url=url, uuid=uuid.uuid4().hex)
        docks.append(dock)
        added.append(dock)
        titles.add(name.casefold())
    return added


def write_dock_list(original, docks):
    # Edit one OBS INI key and preserve all other lines, including DockState.
    newline = "\r\n" if b"\r\n" in original else "\n"
    lines = original.decode("utf-8").splitlines(keepends=True)
    section = False
    insertion = None
    existing = []
    for index, line in enumerate(lines):
        stripped = line.lstrip("\ufeff").strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section:
                break
            section = stripped.casefold() == "[basicwindow]"
        if section:
            insertion = index + 1
            if stripped.partition("=")[0].strip().casefold() == "extrabrowserdocks":
                existing.append(index)
    if existing:
        insertion = existing[0]
        for index in reversed(existing):
            del lines[index]
    if insertion is None:
        if lines and not lines[-1].endswith(("\r", "\n")):
            lines[-1] += newline
        lines.append("[BasicWindow]" + newline)
        insertion = len(lines)
    if insertion and not lines[insertion - 1].endswith(("\r", "\n")):
        lines[insertion - 1] += newline
    value = json.dumps(docks, ensure_ascii=False, separators=(",", ":"))
    lines.insert(insertion, "ExtraBrowserDocks=" + value + newline)
    return "".join(lines).encode("utf-8")


def script_path(name):
    return ROOT / "outputs" / name


def same_path(value, path):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        return False
    return Path(value) == path


def script_entries(scene, path):
    modules = scene.get("modules", {})
    scripts = modules.get("scripts-tool", [])
    if not isinstance(scripts, list):
        raise ValueError(f"OBS's script list in {path.name} could not be read.")
    return scripts


def register_script(scripts, name, updates, add):
    path = script_path(name)
    entry = next((item for item in scripts if isinstance(item, dict)
                  and same_path(item.get("path"), path)), None)
    if entry is None:
        if not add:
            return
        for item in scripts:
            other_path = item.get("path") if isinstance(item, dict) else None
            if isinstance(other_path, str) and PureWindowsPath(other_path).name.casefold() == name:
                raise ValueError(f"Another registration named {name} is already present at {other_path}. "
                                 "Remove that registration in OBS only if it is an old toolkit copy.")
        entry = {"path": path.as_posix(), "settings": {}}
        scripts.append(entry)
    if not isinstance(entry.get("settings"), dict):
        raise ValueError(f"OBS's {name} script settings could not be read.")
    entry["settings"].update(updates)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_optional(path):
    return path.read_bytes() if path.exists() else None


def dock_identity(dock):
    try:
        return uuid.UUID(dock.get("uuid", "")).hex, str(dock["url"]).rstrip("/")
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


def read_install_record(path):
    original = read_optional(path)
    if original is None:
        return original, set()
    record = json.loads(original)
    if (record["version"] != 1 or not isinstance(record["docks"], list)
            or not same_path(record.get("toolkit_folder"), ROOT)):
        raise ValueError("The toolkit installation record belongs to another folder or is invalid. "
                         "Run Uninstall from the folder used for Setup.")
    pairs = {dock_identity(dock) for dock in record["docks"]}
    if None in pairs or any(url not in {value.rstrip("/") for value in DOCKS.values()} for _, url in pairs):
        raise ValueError("The toolkit installation record contains an invalid dock.")
    return original, pairs


def toolkit_script(entry):
    return isinstance(entry, dict) and any(
        same_path(entry.get("path"), script_path(name)) for name in (HOTKEYS, TRACKING)
    )


def legacy_docks(config, docks, collections):
    # Older releases saved the pre-install files but did not record dock UUIDs.
    # Use a snapshot only when it also shows this toolkit's exact script being added.
    names_by_url = {url.rstrip("/"): title for title, url in DOCKS.items()}
    url_counts = Counter(str(dock.get("url", "")).rstrip("/") for dock in docks)
    candidates = set()
    root = config / "toolkit-setup-backups"
    for backup in sorted(root.glob("*")):
        saved_ini = backup / "user.ini"
        if not saved_ini.is_file():
            continue
        for path, scripts in collections:
            if not any(isinstance(entry, dict) and same_path(entry.get("path"), script_path(HOTKEYS))
                       for entry in scripts):
                continue
            old_scene = backup / path.relative_to(config)
            if not old_scene.is_file():
                continue
            try:
                old_scripts = script_entries(json.loads(old_scene.read_bytes()), old_scene)
                if any(toolkit_script(entry) for entry in old_scripts):
                    continue
                _, old_docks = read_docks(saved_ini.read_bytes())
            except (OSError, ValueError, TypeError, AttributeError, configparser.Error):
                continue
            previous_urls = {str(dock.get("url", "")).rstrip("/") for dock in old_docks}
            for dock in docks:
                identity = dock_identity(dock)
                if identity is None:
                    continue
                _, url = identity
                title = names_by_url.get(url)
                label = str(dock.get("title", ""))
                if title and url_counts[url] == 1 and url not in previous_urls and (
                    label == title or re.fullmatch(re.escape(title) + r" \(Toolkit(?: [0-9]+)?\)", label)
                ):
                    candidates.add(identity)
            break
        if candidates:
            break
    return candidates


def plan_websocket(config, enable_existing):
    path = config / "plugin_config" / "obs-websocket" / "config.json"
    original = read_optional(path)
    if original is None:
        settings = {}
    else:
        settings = json.loads(original)
        if not isinstance(settings, dict):
            raise ValueError("The OBS WebSocket configuration could not be read.")
    if settings.get("server_enabled") is True:
        return path, original, original, "existing"
    if original is not None and not enable_existing:
        return path, original, original, "disabled"
    settings.update(server_enabled=True, auth_required=True, first_load=False)
    settings.setdefault("server_port", 4455)
    if not settings.get("server_password"):
        settings["server_password"] = secrets.token_urlsafe(18)
    return path, original, json_bytes(settings), "enabled"


def plan(config, camera=None, active_only=False, *, uninstall=False, enable_websocket=False):
    ini = config / "user.ini"
    if not ini.is_file():
        raise ValueError("The OBS user.ini file was not found. Check the OBS configuration folder.")
    original = ini.read_bytes()
    user_config, docks = read_docks(original)
    scenes = config / "basic" / "scenes"
    collections = sorted(scenes.glob("*.json"))
    if active_only:
        stem = user_config.get("Basic", "SceneCollectionFile", fallback="")
        if not stem or Path(stem).name != stem:
            raise ValueError("Open a scene collection in OBS, quit it, then run Setup again.")
        active = scenes / (stem if stem.lower().endswith(".json") else stem + ".json")
        if not active.is_file():
            raise ValueError("OBS's active scene collection could not be found.")
        collections = [active]
    if not collections and not uninstall:
        raise ValueError("Open a scene collection in OBS, quit it, then run Setup again.")

    changes = {}
    current_scripts = []
    changed_collections = 0
    for path in collections:
        content = path.read_bytes()
        scene = json.loads(content)
        scripts = script_entries(scene, path)
        current_scripts.append((path, list(scripts)))
        updated = list(scripts)
        if uninstall:
            updated = [entry for entry in scripts if not toolkit_script(entry)]
        else:
            updated = json.loads(json.dumps(scripts))
            register_script(updated, HOTKEYS, {"toolkit_obs_config": str(config)}, add=True)
            register_script(updated, TRACKING, {"camera_ip": camera} if camera else {}, add=bool(camera))
        if scripts != updated:
            scene.setdefault("modules", {})["scripts-tool"] = updated
            changes[path] = (content, json_bytes(scene))
            changed_collections += 1

    record = config / INSTALL_RECORD
    previous_record, owned = read_install_record(record)
    # Leave unidentified legacy docks available for manual removal.
    if previous_record is None:
        owned.update(legacy_docks(config, docks, current_scripts))
    if uninstall:
        kept = [dock for dock in docks if dock_identity(dock) not in owned]
        dock_count = len(docks) - len(kept)
        if dock_count:
            changes[ini] = (original, write_dock_list(original, kept))
        if previous_record is not None:
            changes[record] = (previous_record, None)
        websocket_status = "untouched"
    else:
        added = add_docks(docks)
        dock_count = len(added)
        if added:
            changes[ini] = (original, write_dock_list(original, docks))
            owned.update(dock_identity(dock) for dock in added)
        if owned and (previous_record is None or added):
            record_bytes = json_bytes({
                "version": 1, "toolkit_folder": str(ROOT),
                "docks": [{"uuid": uid, "url": url} for uid, url in sorted(owned)],
            })
            changes[record] = (previous_record, record_bytes)
        path, before, after, websocket_status = plan_websocket(config, enable_websocket)
        if before != after:
            changes[path] = (before, after)
    return changes, changed_collections, dock_count, websocket_status


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        name = Path(temporary.name)
    try:
        name.write_bytes(data)
        if path.exists():
            shutil.copymode(path, name)
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


def apply_changes(config, changes):
    if not changes:
        return None
    require_obs_closed()
    for path, (before, _) in changes.items():
        if path.resolve() != path:
            raise ValueError(f"OBS settings path uses a filesystem link: {path}")
        if read_optional(path) != before:
            raise ValueError("OBS settings changed since they were read. Run the command again.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory = config / "toolkit-setup-backups" / stamp
    directory.mkdir(parents=True, mode=0o700)
    for path, (before, _) in changes.items():
        if before is not None:
            write_atomic(directory / path.relative_to(config), before)
    require_obs_closed()
    written = []
    try:
        for path, (before, after) in changes.items():
            if read_optional(path) != before:
                raise ValueError(f"OBS settings changed during the operation: {path.name}")
            if after is None:
                path.unlink()
            else:
                write_atomic(path, after)
            written.append((path, before, after))
    except (OSError, ValueError) as error:
        for path, before, after in reversed(written):
            try:
                # Preserve any edits made after our write.
                if read_optional(path) != after:
                    continue
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, before)
            except OSError:
                pass
        raise ValueError(f"{error} Original settings are backed up in {directory}.") from error
    return directory


def prepare_python():
    python = ROOT / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")
    imports = "import obsws_python, send2trash, av"
    if not python.is_file() or subprocess.run(
        [str(python), "-c", "import sys"], capture_output=True,
    ).returncode:
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    if subprocess.run([str(python), "-c", imports], capture_output=True).returncode:
        print("Installing Video Rundown components. Internet access is required for this step.", flush=True)
        subprocess.run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--only-binary=:all:", "-r", str(ROOT / "video-rundown" / "requirements.txt"),
        ], check=True)
    if not WINDOWS:
        source = ROOT / "source" / "tracking-toast.swift"
        toast = ROOT / "tracking-runtime" / "tracking-toast"
        if (not toast.exists() or toast.stat().st_mtime < source.stat().st_mtime) and subprocess.run(
            ["/usr/bin/xcode-select", "-p"], capture_output=True,
        ).returncode == 0:
            result = subprocess.run(["/usr/bin/swiftc", "-O", str(source), "-o", str(toast)])
            if result.returncode:
                print("The optional macOS notification helper could not be built.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obs-config", type=Path, help="use a custom OBS configuration folder")
    parser.add_argument("--active-only", action="store_true", help="install only in the last active scene collection")
    parser.add_argument("--camera-ip", type=ipaddress.IPv4Address, help="set an optional FoMaKo camera address")
    parser.add_argument("--enable-websocket", action="store_true",
                        help="enable password-protected WebSocket if an existing configuration has it disabled")
    parser.add_argument("--uninstall", action="store_true", help="remove the toolkit scripts and its docks")
    parser.add_argument("--dry-run", action="store_true", help="preview OBS settings changes without writing them")
    parser.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    args = parser.parse_args()
    if args.uninstall and (args.active_only or args.camera_ip or args.enable_websocket):
        parser.error("--active-only, --camera-ip, and --enable-websocket are setup options.")

    operation = "Uninstall" if args.uninstall else "Setup"
    try:
        print(f"\nOBS Control Toolkit {operation}\n", flush=True)
        if not args.dry_run:
            require_obs_closed()
        config = (args.obs_config or default_config()).expanduser().resolve()
        camera = args.camera_ip and str(args.camera_ip)
        enable_websocket = args.enable_websocket
        changes, count, docks, websocket = plan(config, camera, args.active_only,
                                                uninstall=args.uninstall, enable_websocket=enable_websocket)
        if not args.uninstall and not args.yes and not args.dry_run:
            if camera is None:
                address = input("FoMaKo camera IPv4 address (Enter to skip or keep existing camera settings): ").strip()
                camera = str(ipaddress.IPv4Address(address)) if address else None
            if websocket == "disabled":
                print("OBS WebSocket is disabled. Video Rundown needs it for Program playback.")
                enable_websocket = input("Enable it with password protection? [y/N] ").strip().lower() in ("y", "yes")
            if camera or enable_websocket:
                changes, count, docks, websocket = plan(config, camera, args.active_only,
                                                        enable_websocket=enable_websocket)

        print(f"{'Remove' if args.uninstall else 'Add'} {docks} toolkit dock(s). "
              f"{'Remove' if args.uninstall else 'Update'} toolkit scripts in {count} scene collection(s).")
        if args.uninstall:
            print("OBS scenes, sources, profiles, WebSocket settings, toolkit files, and media are kept.")
        elif websocket == "disabled":
            print("WebSocket will stay disabled. Enable it in OBS before using Program playback.")
        elif websocket == "enabled":
            print("Setup will enable OBS WebSocket with password protection.")
        if args.dry_run:
            for path in changes:
                print(f"  {path.relative_to(config)}")
            print("Preview only. No changes applied.")
            return 0

        if args.uninstall and not changes:
            print("No toolkit registrations found. Older docks without an installation record may need removal in OBS.")
            return 0
        if not args.yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            return 0
        if not args.uninstall:
            prepare_python()
        backup = apply_changes(config, changes)
        print(f"\n{operation} complete.")
        if backup:
            print(f"Backup of changed OBS settings: {backup}")
        if args.uninstall:
            print("If an older toolkit dock remains, remove it from Docks > Custom Browser Docks.")
        else:
            print("Open OBS and choose Video Rundown from Docks.")
            print("Use 'Set up scene' or 'Use existing scene' in each collection you use.")
        return 0
    except subprocess.CalledProcessError:
        print(f"\n{operation} could not finish. Check the error above, then retry.", file=sys.stderr)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, configparser.Error, EOFError) as error:
        print(f"\n{operation} could not finish. {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

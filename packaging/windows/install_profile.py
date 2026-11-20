"""Register the MSI installation in the current user's OBS profile."""

import argparse
import base64
from contextlib import redirect_stderr, redirect_stdout
import json
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import setup_toolkit as setup

STATE = ROOT.parent / "InstallerState"
PROFILE = STATE / "profile.json"


def read_profile(path):
    payload = setup.read_optional(path)
    return json.loads(payload) if payload is not None else {}


def registered_root(config):
    record = read_profile(config / setup.INSTALL_RECORD)
    owner = record.get("toolkit_folder")
    if not isinstance(owner, str) or not Path(owner).is_absolute() or setup.same_path(owner, ROOT):
        return None
    previous = Path(owner)
    if not (previous / "setup_toolkit.py").is_file() or not (previous / "outputs" / setup.HOTKEYS).is_file():
        raise ValueError("The existing toolkit folder is unavailable. Restore it before moving its OBS registrations.")
    return previous


def apply_profile(operation, configured_path, journal):
    journal.unlink(missing_ok=True)
    setup.require_obs_closed()
    profile = read_profile(PROFILE)
    config = Path(configured_path or profile.get("config") or setup.default_config()).resolve()
    if operation == "uninstall" and not (config / "user.ini").is_file():
        return
    previous = registered_root(config) if operation == "install" else None
    if operation == "uninstall" and not setup.same_path(read_profile(config / setup.INSTALL_RECORD).get("toolkit_folder"), ROOT):
        # A later manual installation may have taken ownership since the MSI ran.
        return
    if previous is not None:
        old_rundown = previous / "video-rundown"
        data = Path(profile.get("data") or old_rundown)
    else:
        data = Path(profile.get("data") or ROOT.parent / "Rundown")
    changes, _, _, websocket = setup.plan(config, uninstall=operation == "uninstall", previous_root=previous, rundown_data=data)
    if operation == "install":
        profile_bytes = setup.json_bytes(dict(config=str(config), data=str(data)))
        before = setup.read_optional(PROFILE)
        if before != profile_bytes:
            changes[PROFILE] = (before, profile_bytes)

    entries = [[str(path), encode(before), encode(after)] for path, (before, after) in changes.items()]
    setup.write_atomic(journal, setup.json_bytes(entries))
    if PROFILE in changes:
        _, profile_bytes = changes.pop(PROFILE)
    else:
        profile_bytes = None
    setup.apply_changes(config, changes)
    if profile_bytes is not None:
        setup.write_atomic(PROFILE, profile_bytes)
    if websocket == "disabled":
        print("In OBS, enable WebSocket Server under Tools → WebSocket Server Settings for Program playback.")
    print(f"Toolkit profile {operation} finished for {config}.")


def encode(payload):
    return base64.b64encode(payload).decode("ascii") if payload is not None else None


def rollback(journal):
    if not journal.is_file():
        return
    for name, before, after in reversed(json.loads(journal.read_bytes())):
        path = Path(name)
        if encode(setup.read_optional(path)) != after:
            continue
        if before is None:
            path.unlink(missing_ok=True)
        else:
            setup.write_atomic(path, base64.b64decode(before))
    journal.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "uninstall", "rollback-install", "rollback-uninstall", "commit"))
    parser.add_argument("--config", default="|")
    parser.add_argument("--product", required=True)
    args = parser.parse_args()
    product = str(setup.uuid.UUID(args.product))
    operation = args.operation.removeprefix("rollback-")
    journal = STATE / f"{product}-{operation}.json"
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "setup.log").open("a", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        try:
            if args.operation == "commit":
                (STATE / f"{product}-install.json").unlink(missing_ok=True)
            elif args.operation.startswith("rollback-"):
                rollback(journal)
            else:
                apply_profile(operation, args.config.removesuffix("|"), journal)
            return 0
        except Exception:
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(main())

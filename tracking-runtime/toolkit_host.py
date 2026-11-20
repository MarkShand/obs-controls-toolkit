"""Keep the local dock servers alive for the lifetime of the OBS script."""

import os
from pathlib import Path
import runpy
import sys
import threading
import traceback


RUNTIME = Path(__file__).resolve().parent
RUNDOWN = RUNTIME.parent / "video-rundown"


def run_rundown(stop):
    sys.path.insert(0, str(RUNDOWN))
    import video_rundown
    video_rundown.main(stop)


def run_controls(stop):
    runpy.run_path(str(RUNTIME / "hotkey-dock.py"))["serve"](stop)


def serve(target, stop):
    try:
        target(stop)
    except Exception:
        traceback.print_exc()


def main():
    if len(sys.argv) > 1 and sys.argv[1]:
        os.environ["OBS_TOOLKIT_CONFIG_DIR"] = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2]:
        os.environ["OBS_TOOLKIT_RUNDOWN_DATA"] = sys.argv[2]
    with (RUNTIME / "toolkit.log").open("w", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        stop = threading.Event()
        workers = [
            threading.Thread(target=serve, args=(target, stop), daemon=True)
            for target in (run_controls, run_rundown)
        ]
        for worker in workers:
            worker.start()
        try:
            # libobs closes the write end when the Lua script unloads.
            sys.stdin.read()
        finally:
            stop.set()
            for worker in workers:
                worker.join(timeout=0.5)
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__


if __name__ == "__main__":
    main()

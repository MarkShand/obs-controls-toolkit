"""Display the Windows version of the controls status toast."""
import os
from pathlib import Path
import sys
import tkinter as tk

tcl = Path(sys.base_prefix) / "tcl"
for variable, folder, script in (
    ("TCL_LIBRARY", tcl / f"tcl{tk.TclVersion}", "init.tcl"),
    ("TK_LIBRARY", tcl / f"tk{tk.TkVersion}", "tk.tcl"),
):
    if (folder / script).is_file():
        os.environ.setdefault(variable, str(folder))

status = sys.argv[1]
enabled = status in ("RESUMED", "ON")
tracking = status in ("ON", "OFF")
manual_locked = status == "MANUAL_LOCKED"
root = tk.Tk()
root.withdraw()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg="#171c24")
tk.Label(root, text=("Auto tracking is on" if manual_locked else ("Auto tracking is on" if enabled else "Auto tracking is off") if tracking else ("OBS controls on" if enabled else "OBS controls off")),
         fg="#f0f4fa", bg="#171c24", font=("Segoe UI", 13, "bold")).pack(pady=(10, 2))
tk.Label(root, text=("Press Ctrl+1 to use manual camera controls" if manual_locked else "Confirmed by the camera" if tracking else ("Camera and scene shortcuts are active" if enabled else "Press Control + ` to resume")),
         fg="#c3cddd", bg="#171c24", font=("Segoe UI", 10)).pack(pady=(0, 10))
root.update_idletasks()
width, height = 320, root.winfo_reqheight()
root.geometry(f"{width}x{height}+{(root.winfo_screenwidth()-width)//2}+{root.winfo_screenheight()-height-66}")
try:
    import ctypes
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
    ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x80)
except OSError:
    pass
root.deiconify()
root.after(1800, root.destroy)
root.mainloop()

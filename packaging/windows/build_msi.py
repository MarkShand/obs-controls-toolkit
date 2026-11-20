"""Build a per-user Windows x64 MSI using WiX and this interpreter's dependencies."""

import argparse
from collections import defaultdict
import hashlib
from importlib import metadata
from pathlib import Path
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import tempfile
import uuid
from xml.etree import ElementTree as xml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPGRADE_CODE = uuid.UUID("939d465f-9689-44c5-a4e7-72ef69bd9c39")
SCHEMA = "http://wixtoolset.org/schemas/v4/wxs"
FILES = (
    "README.md", "setup_toolkit.py",
    "outputs/obs-hotkey-toggle.lua", "outputs/fomako-tracking.lua", "outputs/obs-hotkeys.html",
    "tracking-runtime/toolkit_host.py", "tracking-runtime/hotkey-dock.py",
    "tracking-runtime/hotkey-toast.py", "tracking-runtime/windows-toast.lua",
    "video-rundown/video_rundown.py", "video-rundown/dock.html", "video-rundown/preview.html",
    "video-rundown/clock.html", "video-rundown/lan_monitor.html", "video-rundown/on_air.js",
    "video-rundown/graphics.py", "video-rundown/graphics_schedule.py", "video-rundown/graphics.html",
    "video-rundown/graphics.css", "video-rundown/graphics.js",
    "video-rundown/graphics_overlay.html", "video-rundown/graphics_render.js", "video-rundown/graphics_receiver.js",
    "video-rundown/support.js", "video-rundown/support.css",
    "video-rundown/choose_media.ps1", "video-rundown/folder_picker.cs",
    "video-rundown/README.md", "video-rundown/requirements.txt",
)


def copy_payload(payload):
    for relative in FILES:
        target = payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    shutil.copy2(HERE / "install_profile.py", payload / "install_profile.py")

    runtime = payload / ".venv" / "Scripts"
    runtime.mkdir(parents=True)
    base = Path(sys.base_prefix)
    for file in base.iterdir():
        if file.is_file() and (file.suffix == ".dll" or file.name in {"python.exe", "pythonw.exe", "LICENSE.txt"}):
            shutil.copy2(file, runtime)
    shutil.copytree(base / "DLLs", runtime / "DLLs", ignore=shutil.ignore_patterns("*.cat"))
    shutil.copytree(base / "Lib", runtime / "Lib", ignore=shutil.ignore_patterns(
        "site-packages", "__pycache__", "*.pyc", "test", "tests", "ensurepip", "idlelib", "turtledemo"))
    if (base / "tcl").is_dir():
        shutil.copytree(base / "tcl", runtime / "tcl")

    installed = Path(site.getsitepackages()[-1])
    bundled = runtime / "Lib" / "site-packages"
    bundled.mkdir()
    for name in ("av", "obsws-python", "Send2Trash", "websocket-client"):
        distribution = metadata.distribution(name)
        for entry in distribution.files or []:
            if ".." in entry.parts or entry.suffix == ".pyc":
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file() and source.is_relative_to(installed):
                destination = bundled / entry
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

    name = f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    (runtime / name).write_text(".\nDLLs\nLib\nLib\\site-packages\n", encoding="ascii")
    subprocess.run([str(runtime / "python.exe"), "-B", "-c",
                    "import obsws_python, av, send2trash, tkinter, sqlite3; tkinter.Tcl(); print(av.__version__)"], check=True)


def identifier(prefix, path):
    return prefix + hashlib.sha256(path.as_posix().lower().encode()).hexdigest()[:27]


def write_components(payload, path):
    xml.register_namespace("", SCHEMA)
    root = xml.Element(f"{{{SCHEMA}}}Wix")
    fragment = xml.SubElement(root, "Fragment")
    directory_elements = {Path(): xml.SubElement(fragment, "DirectoryRef", Id="INSTALLFOLDER")}
    component_group = xml.SubElement(fragment, "ComponentGroup", Id="ToolkitPayload")
    files = defaultdict(list)
    for file in sorted(payload.rglob("*")):
        if file.is_file():
            files[file.relative_to(payload).parent].append(file)
    for directory in sorted(files, key=lambda value: (len(value.parts), value)):
        for parent in [*reversed(directory.parents), directory]:
            if parent not in directory_elements:
                directory_elements[parent] = xml.SubElement(directory_elements[parent.parent], "Directory",
                                                            Id=identifier("D", parent), Name=parent.name)
        component_id = identifier("C", directory)
        component = xml.SubElement(directory_elements[directory], "Component", Id=component_id,
                                   Guid=str(uuid.uuid5(UPGRADE_CODE, directory.as_posix().lower())))
        xml.SubElement(component, "RegistryValue", Root="HKCU", Key=r"Software\OBS Control Toolkit\Components",
                       Name=component_id, Value="1", Type="integer", KeyPath="yes")
        xml.SubElement(component, "RemoveFolder", Id=identifier("Remove", directory), On="uninstall")
        xml.SubElement(component_group, "ComponentRef", Id=component_id)
        for file in files[directory]:
            relative = file.relative_to(payload)
            file_id = {".venv/Scripts/pythonw.exe": "PythonWindowless", "install_profile.py": "ProfileInstaller"}.get(
                relative.as_posix(), identifier("F", relative))
            xml.SubElement(component, "File", Id=file_id, Source=str(file))
    xml.indent(root)
    xml.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wix", type=Path, required=True, help="path to wix.exe or wix.dll from WiX 6")
    parser.add_argument("--ui-extension", type=Path, required=True, help="path to WixToolset.UI.wixext.dll")
    parser.add_argument("--util-extension", type=Path, required=True, help="path to WixToolset.Util.wixext.dll")
    parser.add_argument("--version", default="1.6.1")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True, help="directory for temporary build inputs")
    args = parser.parse_args()
    if sysconfig.get_platform() != "win-amd64" or not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("Use Windows x64 and specify a three-part MSI version.")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="toolkit-msi-", dir=args.work_dir.resolve()))
    payload = stage / "payload"
    payload.mkdir()
    copy_payload(payload)
    components = stage / "Payload.wxs"
    write_components(payload, components)
    wix = str(args.wix.resolve())
    command = ["dotnet", "--roll-forward", "Major", wix] if args.wix.suffix == ".dll" else [wix]
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*command, "build", "-arch", "x64", "-ext", str(args.ui_extension.resolve()),
                    "-ext", str(args.util_extension.resolve()),
                    "-d", f"Version={args.version}", "-d", f"ProductCode={uuid.uuid5(UPGRADE_CODE, args.version)}",
                    "-intermediatefolder", str(stage / "obj"), "-pdbtype", "none",
                    str(HERE / "Toolkit.wxs"), str(components), "-out", str(output)], check=True)
    print(output)


if __name__ == "__main__":
    main()

"""JSON graphics library and OBS Browser Source setup."""

import copy
import csv
import base64
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
import hashlib
import io
from itertools import islice
import json
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

import graphics_schedule as schedule


LABELS = dict(names="Names", headlines="Headlines", programs="Program", crawlers="Crawler", clock="Clock", date="Date", custom="Custom")
LIBRARIES = ("names", "headlines", "programs", "crawlers", "custom")
DIMENSIONS = {"names":(760, 196), "headlines":(1650, 240), "programs":(1040, 160),
              "crawlers":(1920, 128), "clock":(480, 134), "date":(630, 134), "custom":(640, 176)}
MASTER_DEFAULTS = {kind: kind in {"names", "programs"} for kind in LABELS}
ANIMATIONS = ("slide", "fade", "wipe", "cut")
DIRECTIONS = ("right", "left", "up", "down")
TEXT_CASES = ("original", "sentence", "lower", "upper", "title")
COLOR_FIELDS = ("foreground", "secondary", "background", "description_background")
DESCRIPTION_FIELDS = ("description", "show_description")
CUSTOM_CHOICES = dict(horizontal=("left", "center", "right"), vertical=("top", "middle", "bottom"),
                      align=("left", "center", "right"), animation=ANIMATIONS, direction=DIRECTIONS)
CUSTOM_FIELDS = (*CUSTOM_CHOICES, "duration")
MULTIPLE_RECEIVERS = {"names", "custom"}
FIELDS = {"names":("text", *DESCRIPTION_FIELDS), "headlines":("text",),
          "programs":("text",), "crawlers":("text",), "custom":("text", *DESCRIPTION_FIELDS, *COLOR_FIELDS, *CUSTOM_FIELDS)}
CSV_HEADERS = {
    "names": ("name",), "headlines": ("headline",), "programs": ("program_name", "program"),
    "crawlers": ("crawler_text", "crawler"), "custom": ("custom_label", "custom", "label"),
}
CSV_EXAMPLES = {
    "names": ["Maya Brooks", "Studio Anchor", "yes"],
    "headlines": ["Local film festival opens this weekend"],
    "programs": ["Evening Report"],
    "crawlers": ["Coming up next: a look at today's forecast"],
    "custom": ["FILE VIDEO", "November 18, 2026", "yes", "#FFFFFF", "#FFFFFF", "#9E222C", "#202430",
               "right", "top", "left", "slide", "right", "350"],
}
BUILTIN_PRESETS = {
    "On Air Red": ("FFFFFF", "FFFFFF", "9E222C", "55151D"),
    "Network Navy": ("FFFFFF", "E2EEFF", "113659", "09253F"),
    "Midnight": ("FFFFFF", "DCE4EF", "172331", "0C1621"),
    "Broadcast Black": ("FFFFFF", "E4E7EB", "191A1D", "313339"),
    "Control Room Slate": ("FFFFFF", "ECF2F7", "3C4B5F", "202B39"),
    "Studio White": ("172131", "374459", "FFFFFF", "DFE7F2"),
    "Newsprint": ("1E262D", "343E44", "F4F0E7", "E6DFD3"),
    "Signal Blue": ("FFFFFF", "E8F1FF", "194A92", "133265"),
    "Deep Teal": ("FFFFFF", "E5F8F5", "0A574F", "043B36"),
    "Field Green": ("FFFFFF", "EEF8E7", "335335", "233821"),
    "Burgundy": ("FFFFFF", "F7E4EC", "602643", "381A2B"),
    "Executive Plum": ("FFFFFF", "F0E7FC", "4B3568", "322445"),
    "Editorial Copper": ("FFFFFF", "FFF1E7", "854327", "592E1D"),
    "Alert Amber": ("24211D", "EFE8D8", "F3BE53", "4D3719"),
    "Glacier": ("102D42", "183B50", "D4F0F5", "A9D7E2"),
}
CSV_LIMIT = 16 * 1024**2
OWNER = "obs_controls_toolkit_graphics"
TARGET = re.compile(r"[a-f0-9]{32}")
TIME_FORMATS = ("12hm", "12hms", "12hmsms", "24hm", "24hms", "24hmsms")
DATE_FORMATS = ("long", "weekday", "short", "ymd", "mdy", "dmy")
MODELS = {
    "names": dict(x=8, right=53, y=65, width=39, font=44, lines=1),
    "headlines": dict(x=7, y=74, width=86, font=52, lines=2, interval=8, advance="animated", headline_height=None),
    "programs": dict(x=7, y=8, width=54, font=43, lines=1),
    "crawlers": dict(x=0, y=92, width=100, font=37, lines=1, speed=165, separator="dot", logo=""),
    "clock": dict(x=74, y=7, width=23, font=42, lines=1, show_time=True, show_date=True,
                  time_format="12hms", date_format="short"),
    "date": dict(x=66, y=18, width=31, font=42, lines=1, date_format="short"),
    "custom": dict(x=62, y=5, width=34, font=46, lines=1),
}


def default_style(kind):
    horizontal = {"names":"left", "programs":"right", "custom":"right"}.get(kind,"center")
    return dict(MODELS[kind], foreground="#14171c", secondary="#39434e", background="#ffffff",
                transparent=False, opacity=100, radius=7, padding=18, align=horizontal, text_vertical="middle",
                padding_mode="all", padding_top=18, padding_right=18, padding_bottom=18, padding_left=18,
                family="Arial", bold=False,
                animation="slide", direction="right", duration=350, text_case="original",
                background_size="fit" if kind == "custom" else "manual", manual_width=None, horizontal=horizontal, vertical="middle",
                corners="individual" if kind == "names" else "all",
                radius_tl=7, radius_tr=7, radius_br=7, radius_bl=7, description_font=None,
                **(dict(description_background="#e6edf5", description_transparent=True, description_layout="compact")
                   if kind in ("names", "custom") else {}))


def font_name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100 or any(ord(char) < 32 for char in value):
        raise ValueError("Choose a font name.")
    return value.strip()


def logo_value(value):
    if not value:
        return ""
    match = re.fullmatch(r"data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)", value) if isinstance(value, str) else None
    if not match or len(match[2]) > 720000:
        raise ValueError("Use a PNG, JPEG, GIF, or WebP logo up to 512 KB.")
    payload = base64.b64decode(match[2], validate=True)
    format_name = match[1]
    signature = {"png":b"\x89PNG\r\n\x1a\n", "jpeg":b"\xff\xd8\xff", "gif":b"GIF8", "webp":b"RIFF"}[format_name]
    if len(payload) > 512 * 1024 or not payload.startswith(signature) or (format_name == "webp" and payload[8:12] != b"WEBP"):
        raise ValueError("The selected logo is not a supported image.")
    return value


def validate_style(kind, data):
    if not isinstance(data, dict):
        raise ValueError("Enter valid appearance settings.")
    style = default_style(kind)
    numbers = dict(x=(0, 100), right=(0, 100), y=(0, 100), width=(5, 100), font=(12, 180), headline_height=(5, 100),
                   lines=(1, 2), radius=(0, 120), padding=(0, 80), speed=(25, 1200), opacity=(0, 100),
                   duration=(50, 3000), interval=(1, 120), manual_width=(5, 100), description_font=(8, 180),
                   **dict.fromkeys(("radius_tl", "radius_tr", "radius_br", "radius_bl"), (0, 120)),
                   **dict.fromkeys(("padding_top", "padding_right", "padding_bottom", "padding_left"), (0, 80)))
    options = dict(align=("left", "center", "right"), time_format=TIME_FORMATS, date_format=DATE_FORMATS,
                   animation=ANIMATIONS, direction=DIRECTIONS, text_case=TEXT_CASES, advance=("animated", "cut"),
                   separator=("space", "dot", "logo"), background_size=("manual", "fit", "fill"),
                   description_layout=("compact", "band"),
                   horizontal=("existing", "left", "center", "right"), vertical=("existing", "top", "middle", "bottom"),
                   corners=("all", "individual"), padding_mode=("all", "sides"), text_vertical=("top", "middle", "bottom"))
    for key, default in style.items():
        value = data.get(key, data.get(key.split("_",1)[0], default)
                         if key.startswith(("radius_", "padding_")) and key != "padding_mode" else default)
        if key == "background_size" and kind == "headlines" and value == "fit":
            value = "manual"
        if key == "family":
            style[key] = font_name(value)
            continue
        if key == "logo":
            style[key] = logo_value(value)
            continue
        if default is None and value is None:
            continue
        if key in numbers:
            low, high = numbers[key]
            valid = type(value) is int and low <= value <= high
        elif key in options:
            valid = value in options[key]
        elif isinstance(default, bool):
            valid = type(value) is bool
        else:
            valid = isinstance(value, str) and re.fullmatch(r"#[A-Fa-f0-9]{6}", value)
        if not valid:
            raise ValueError(f"Invalid appearance setting ({key}).")
        style[key] = value
    return style


def entry_text(value, *, required=False, limit):
    if not isinstance(value, str):
        raise ValueError("Enter text for the graphic.")
    value = " ".join(value.split())
    if len(value) > limit or (required and not value):
        raise ValueError(f"Enter text between {1 if required else 0} and {limit} characters.")
    return value


def make_entry(kind, data, key=None):
    limit = 2000 if kind == "crawlers" else 600 if kind == "headlines" else 200
    result = dict(id=key or uuid4().hex, text=entry_text(data.get("text", ""), required=True, limit=limit))
    if kind in ("names", "custom"):
        result["description"] = entry_text(data.get("description", ""), limit=200)
        show_description = data.get("show_description", True)
        if type(show_description) is not bool:
            raise ValueError("Choose whether to show the description.")
        result["show_description"] = show_description
    if kind == "custom":
        result.update({field: hex_color(data.get(field), optional=True) for field in COLOR_FIELDS})
        for field in CUSTOM_FIELDS:
            value = data.get(field)
            if value is not None:
                valid = type(value) is int and 50 <= value <= 3000 if field == "duration" else value in CUSTOM_CHOICES[field]
                if not valid:
                    raise ValueError(f"Invalid Custom entry setting ({field}).")
            result[field] = value
        source = data.get("default_source")
        if source is not None:
            if not isinstance(source, dict) or set(source) != {"scene", "receiver"} or not all(map(schedule.is_id, source.values())):
                raise ValueError("Choose a valid default OBS source.")
        result["default_source"] = source
    return result


def require_default_source(entry, scene, receiver):
    source = entry.get("default_source")
    if source and source != {"scene": scene, "receiver": receiver}:
        raise ValueError("This entry is assigned to another OBS source. Select its default source first.")


def hex_color(value, *, optional=False):
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", value.strip()):
        raise ValueError("Use a six-digit HEX color like #26415B.")
    return value.strip().upper()


def csv_rows(payload):
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = payload.decode("cp1252", errors="replace")
    try:
        sample = decoded[:4096]
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter if sample.strip() else ","
    except csv.Error:
        first = next((line for line in sample.splitlines() if line.strip()), "")
        try:
            delimiter = csv.Sniffer().sniff(first, delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    try:
        for index, row in enumerate(csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True), 1):
            if any(field.strip() for field in row):
                yield index, row
    except csv.Error as exc:
        raise ValueError(f"Could not read CSV. {exc}") from exc


CSV_ALIASES = {
    "description": ("description", "role", "subtitle", "location"),
    "show_description": ("show_description",),
    "foreground": ("foreground", "text_color", "main_text_color"),
    "secondary": ("secondary", "description_color", "description_text_color"),
    "background": ("background", "background_color"),
    "description_background": ("description_background", "description_background_color"),
    **{field: (field,) for field in CUSTOM_FIELDS if field != "duration"},
    "duration": ("duration", "duration_ms"),
}


def csv_schema(kind):
    return dict(columns=["number", CSV_HEADERS[kind][0], *FIELDS[kind][1:]],
                sample=["1", *CSV_EXAMPLES[kind]])


def csv_key(value):
    return re.sub(r"[\s_-]+", "_", value.strip().casefold())


def csv_mapping(kind, headers):
    normalized = [csv_key(value) for value in headers]
    types = [key for key, aliases in CSV_HEADERS.items() if any(alias in normalized for alias in aliases)]
    if kind is None and len(types) == 1:
        kind = types[0]
    if not isinstance(kind, str) or kind not in CSV_HEADERS:
        return {}, types, ""
    if types and kind not in types:
        names = ", ".join(LABELS[key] for key in types)
        return {}, types, f"This file has {names} columns. For {LABELS[kind]}, use the format shown below."
    fields = dict(text=(*CSV_HEADERS[kind], "text", "title"), **CSV_ALIASES)
    mapping = {}
    for field in FIELDS[kind]:
        for alias in fields[field]:
            if normalized.count(alias) == 1:
                mapping[field] = normalized.index(alias)
                break
    return mapping, types, ""


def csv_preview(payload, has_header, kind=None):
    rows = csv_rows(payload)
    first = next(rows, None)
    if first is None:
        return dict(columns=[], sample=[], mapping={}, types=[], warning="", empty=True)
    samples = [row for _, row in islice(rows,3)]
    headers = first[1] if has_header else []
    if not has_header:
        samples.insert(0, first[1])
    count = max(map(len, [headers, *samples]))
    if count > 200:
        raise ValueError("Choose a CSV with at most 200 columns.")
    columns = [(headers[i] if i < len(headers) else "").strip()[:160] or f"Column {i+1}" for i in range(count)]
    mapping, types, warning = csv_mapping(kind, headers)
    return dict(columns=columns, sample=[[value[:120] for value in row] for row in samples[:3]],
                mapping=mapping, types=types, warning=warning, empty=not samples)


def csv_entries(kind, payload, options):
    rows = csv_rows(payload)
    if options.get("header") is True:
        header = next(rows, None)
        if header is None:
            return []
        headers = header[1]
        _, _, warning = csv_mapping(kind, headers)
        if warning:
            raise ValueError(warning)
    mapping = options.get("mapping", {})
    if not isinstance(mapping, dict) or type(mapping.get("text")) is not int or any(
        key not in FIELDS[kind] or type(index) is not int or not 0 <= index < 200 for key,index in mapping.items()
    ) or len(set(mapping.values())) != len(mapping):
        raise ValueError("Map a different CSV column to each selected field, including the main text field.")
    if options.get("header") is True:
        column = mapping["text"]
        if column >= len(headers):
            raise ValueError("Map the main text to a column in the CSV header.")
        key = csv_key(headers[column])
        wrong = next((other for other, aliases in CSV_HEADERS.items() if other != kind and key in aliases), None)
        if key in ("number", "no", "#") or wrong:
            raise ValueError(f"Map the main text to the {CSV_HEADERS[kind][0]} column.")
    result = []
    for index, row in rows:
        try:
            data = {key: row[column] if column < len(row) else "" for key,column in mapping.items()}
            if not data["text"].strip():
                continue
            if "show_description" in data:
                option = data["show_description"].strip().casefold()
                if option not in ("", "yes", "true", "1", "no", "false", "0"):
                    raise ValueError("Show description must use yes/no, true/false, or 1/0.")
                data["show_description"] = option not in ("no", "false", "0")
            if kind == "custom":
                for field in CUSTOM_FIELDS:
                    if field in data:
                        value = data[field].strip().casefold()
                        if field == "duration" and value:
                            if not value.isdecimal() or len(value) > 4:
                                raise ValueError("Use an animation duration from 50 to 3000 milliseconds.")
                            value = int(value)
                        data[field] = value or None
            result.append(make_entry(kind, data))
        except ValueError as exc:
            raise ValueError(f"CSV record {index}. {exc}") from exc
    return result


def csv_batch(files):
    if not isinstance(files, list) or not files:
        raise ValueError("Stage at least one CSV file to import.")
    records, size = [], 0
    for file in files:
        if not isinstance(file, dict) or not isinstance(file.get("kind"), str) or file["kind"] not in CSV_HEADERS:
            raise ValueError("Choose a destination for each CSV.")
        kind = file["kind"]
        name = str(file.get("name", "CSV"))[:240]
        try:
            payload = base64.b64decode(file.get("data", ""), validate=True)
            size += len(payload)
            if size > CSV_LIMIT:
                raise ValueError("Choose CSV files totaling up to 16 MB per batch.")
            records.append((kind, csv_entries(kind, payload, file)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} — {exc}") from exc
    return records


def clean_preset(data, key):
    if not isinstance(data, dict):
        raise ValueError("Choose a valid color preset.")
    colors = {field: hex_color(data.get(field)) for field in COLOR_FIELDS}
    return dict(id=key, name=entry_text(data.get("name"), required=True, limit=60), **colors)


def color_presets(saved):
    items = [dict(id=f"builtin-{index}", name=name, **dict(zip(COLOR_FIELDS, ("#" + color for color in values))))
             for index,(name,values) in enumerate(BUILTIN_PRESETS.items())]
    edited = {item["id"] for item in saved}
    return saved + [item for item in items if item["id"] not in edited]


def validate_settings(settings):
    if not isinstance(settings, dict) or not isinstance(settings.get("master", {}), dict):
        raise ValueError("Choose valid graphics settings.")
    override = settings.get("override", False)
    custom_override = settings.get("custom_override", False)
    master = {kind:settings.get("master", {}).get(kind, default) for kind,default in MASTER_DEFAULTS.items()}
    if type(override) is not bool or type(custom_override) is not bool or any(type(value) is not bool for value in master.values()):
        raise ValueError("Choose whether to enable each setting.")
    saved = settings.get("color_presets", [])
    if not isinstance(saved, list):
        raise ValueError("Choose a valid list of color presets.")
    presets, ids = [], set()
    factory = {preset["id"] for preset in color_presets([])}
    for item in saved:
        key = item.get("id") if isinstance(item, dict) else None
        if not isinstance(key, str) or (not TARGET.fullmatch(key) and key not in factory) or key in ids:
            raise ValueError("The data contains an invalid or duplicate color preset ID.")
        ids.add(key)
        presets.append(clean_preset(item, key))
    return dict(override=override, family=font_name(settings.get("family", "Arial")), master=master,
                custom_override=custom_override, color_presets=presets)


@lru_cache(maxsize=1)
def installed_fonts():
    values = {"Arial"}
    if sys.platform == "win32":
        import ctypes as c
        from ctypes import wintypes as w

        class LogFont(c.Structure):
            _fields_ = [(name, w.LONG) for name in ("height", "width", "escapement", "orientation", "weight")] + [
                (name, w.BYTE) for name in ("italic", "underline", "strikeout", "charset", "precision", "clip", "quality", "pitch")
            ] + [("face", w.WCHAR * 32)]

        user, gdi = c.windll.user32, c.windll.gdi32
        user.GetDC.argtypes, user.GetDC.restype = [w.HWND], w.HDC
        user.ReleaseDC.argtypes, user.ReleaseDC.restype = [w.HWND, w.HDC], c.c_int
        callback = c.WINFUNCTYPE(c.c_int, c.POINTER(LogFont), c.c_void_p, w.DWORD, w.LPARAM)
        gdi.EnumFontFamiliesExW.argtypes = [w.HDC, c.POINTER(LogFont), callback, w.LPARAM, w.DWORD]

        @callback
        def record(font, _metric, _kind, _data):
            name = font.contents.face
            if name and not name.startswith("@"):
                values.add(name)
            return 1

        font = LogFont()
        font.charset = 1
        dc = user.GetDC(None)
        if dc:
            try:
                gdi.EnumFontFamiliesExW(dc, c.byref(font), record, 0, 0)
            finally:
                user.ReleaseDC(None, dc)
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(["/usr/sbin/system_profiler", "SPFontsDataType", "-json"],
                                    capture_output=True, check=True, timeout=10)
            for file in json.loads(result.stdout).get("SPFontsDataType", []):
                values.update(face["family"] for face in file.get("typefaces", [])
                              if isinstance(face.get("family"), str) and face.get("enabled", "yes") == "yes")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return sorted(values, key=str.casefold)


def clean_library(data):
    if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("entries"), dict)
            or not isinstance(data.get("styles"), dict)):
        raise ValueError("Choose a valid Broadcast Graphics JSON file.")
    entries = {}
    for kind in LIBRARIES:
        records = data["entries"].get(kind, [])
        if not isinstance(records, list):
            raise ValueError("The graphics JSON contains an invalid list.")
        ids = set()
        entries[kind] = []
        for item in records:
            key = item.get("id") if isinstance(item, dict) else None
            if not isinstance(key, str) or not TARGET.fullmatch(key) or key in ids:
                raise ValueError("The graphics JSON contains an invalid or duplicate entry ID.")
            ids.add(key)
            entries[kind].append(make_entry(kind,item,key))
    styles = {kind:validate_style(kind, data["styles"].get(kind, {})) for kind in LABELS}
    if "date" not in data["styles"] and "clock" in data["styles"]:
        previous = styles["clock"]
        styles["date"].update({key:previous[key] for key in ("date_format","family","foreground","background","transparent")})
    return dict(version=1, entries=entries, styles=styles, settings=validate_settings(data.get("settings", {})),
                scheduler=schedule.clean(data.get("scheduler",{}),make_entry))


class Library:
    def __init__(self, path, save):
        self.path = path
        self.state_path = path.with_name("graphics-output.json")
        self.save = save
        self.lock = threading.RLock()
        self.data = None
        self.outputs = None
        self.events = {}
        self.deadlines = {}
        self.previews = {}
        self.revision = uuid4().hex

    def read(self):
        if self.data is None:
            try:
                data = json.loads(self.path.read_bytes())
            except FileNotFoundError:
                data = dict(version=1, entries={}, styles={})
            self.data = clean_library(data)
        return self.data

    def live(self):
        if self.outputs is None:
            try:
                data = json.loads(self.state_path.read_bytes())
            except FileNotFoundError:
                data = {}
            if not isinstance(data, dict) or any(
                not isinstance(state, dict) or not isinstance(state.get("items"), dict)
                or type(state.get("visible")) is not bool for state in data.values()
            ):
                raise ValueError("Could not read saved graphics output state.")
            self.outputs = data
        return self.outputs

    def editor(self, kind):
        with self.lock:
            data = self.read()
            settings = data["settings"]
            return dict(entries=data["entries"].get(kind, []), style=data["styles"].get(kind), settings=settings,
                        presets=color_presets(settings["color_presets"]),
                        csv_templates={key: csv_schema(key) for key in LIBRARIES})

    def autoplay_receivers(self):
        with self.lock:
            return {key.removeprefix("headlines/") for key, state in self.live().items()
                    if key.startswith("headlines/") and state.get("autoplay")}

    def save_edit(self, kind, action, data):
        with self.lock:
            update = copy.deepcopy(self.read())
            result = {}
            if action == "settings":
                changes = data.get("settings")
                if not isinstance(changes, dict):
                    raise ValueError("Choose valid graphics settings.")
                allowed = ("override", "family", "master", "custom_override")
                update["settings"] = validate_settings(dict(update["settings"], **{key:changes[key] for key in allowed if key in changes}))
            elif action == "preset":
                saved = update["settings"]["color_presets"]
                key = data.get("id")
                if key and not any(item["id"] == key for item in color_presets(saved)):
                    raise ValueError("Choose an existing color preset.")
                preset = clean_preset(data, key or uuid4().hex)
                update["settings"]["color_presets"] = [preset, *(item for item in saved if item["id"] != key)]
                result = dict(id=preset["id"], presets=color_presets(update["settings"]["color_presets"]))
            elif action == "style":
                update["styles"][kind] = validate_style(kind, data.get("style"))
            elif kind not in LIBRARIES:
                raise ValueError("Choose a library tab.")
            elif action == "import":
                update["entries"][kind].extend(data)
                result = dict(imported=len(data))
            elif action == "clear" and kind == "headlines":
                update["entries"][kind].clear()
            else:
                entries = update["entries"][kind]
                key = data.get("id")
                index = next((i for i,item in enumerate(entries) if item["id"] == key), None)
                if key and index is None:
                    raise ValueError("This entry was removed. Reload the library.")
                if action == "delete" and index is not None:
                    entries.pop(index)
                    for field in ("plans","queue"):
                        update["scheduler"][field] = [row for row in update["scheduler"][field]
                                                      if row["kind"]!=kind or row["entry"]!=key]
                elif action == "save":
                    if kind == "custom" and index is not None and "default_source" not in data:
                        data = dict(data, default_source=entries[index]["default_source"])
                    item = make_entry(kind, data,key)
                    if index is None:
                        entries.append(item)
                    else:
                        entries[index] = item
                    result = dict(id=item["id"])
                    if source := item.get("default_source"):
                        result["schedule_conflicts"] = sum(
                            row["kind"] == kind and row["entry"] == item["id"] and schedule.pending(row)
                            and (row["scene"], row["receiver"]) != (source["scene"], source["receiver"])
                            for row in update["scheduler"]["plans"]
                        )
                else:
                    raise ValueError("Select an entry first.")
            self.save(self.path, update)
            self.data = update
            if action in ("style", "settings"):
                self.revision = uuid4().hex
            return result

    def import_batch(self, records):
        with self.lock:
            update = copy.deepcopy(self.read())
            counts = {}
            for kind, entries in records:
                if entries:
                    update["entries"][kind].extend(entries)
                    counts[kind] = counts.get(kind, 0) + len(entries)
            if counts:
                self.save(self.path, update)
                self.data = update
            return dict(imported=sum(counts.values()), counts=counts)

    def import_json(self, payload):
        try:
            data = clean_library(json.loads(payload))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Could not import graphics JSON. {exc}") from exc
        with self.lock:
            self.save(self.path, data)
            self.data = data
            self.revision = uuid4().hex
        return dict(imported=sum(map(len,data["entries"].values())))

    def export(self, kind, format_name):
        with self.lock:
            data = self.read()
            folder = self.path.parent / "graphics-exports"
            folder.mkdir(parents=True,exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
            if format_name == "json":
                path = folder / f"graphics-{stamp}.json"
                self.save(path,data)
            elif format_name == "csv" and kind in LIBRARIES:
                path = folder / f"{kind}-{stamp}.csv"
                with path.open("x",encoding="utf-8-sig",newline="") as stream:
                    writer = csv.writer(stream)
                    fields = FIELDS[kind]
                    writer.writerow(csv_schema(kind)["columns"])
                    for number,item in enumerate(data["entries"][kind],1):
                        writer.writerow((number,*(item.get(key,"") for key in fields)))
            else:
                raise ValueError("Choose a library for CSV export, or export all settings and entries as JSON.")
            return dict(path=str(path))

    def scheduler_view(self):
        with self.lock:
            data = self.read()
            calendar = data["scheduler"]
            entries = {kind:{row["id"]:row for row in data["entries"][kind]} for kind in schedule.KINDS}
            plans = [dict(row,graphic=entries[row["kind"]].get(row["entry"])) for row in calendar["plans"]]
            return dict(enabled=calendar["enabled"],plans=plans,queue=calendar["queue"])

    def advance_schedule(self, now):
        with self.lock:
            data = self.read()
            calendar = data["scheduler"]
            if not calendar["enabled"] or not any(row["next"] and row["next"]<=schedule.minute(now) for row in calendar["plans"]):
                return
            update = copy.deepcopy(calendar)
            if schedule.due_changes(update,data["entries"],now):
                self.save(self.path,dict(data,scheduler=update))
                self.data = dict(data,scheduler=update)

    def advance_rundown(self, clip, clip_name, now, program_targets):
        """Consume one-shot schedules at a confirmed on-air playlist start."""
        with self.lock:
            data = self.read()
            calendar = data["scheduler"]
            if not calendar["enabled"]:
                return
            matches = [plan for plan in calendar["plans"] if plan.get("trigger") == "rundown"
                       and schedule.pending(plan) and plan["clip"] in (None, clip)]
            if not matches:
                return
            try:
                active = program_targets()
            except Exception:
                active = None
            update = copy.deepcopy(calendar)
            plans = {plan["id"]:plan for plan in update["plans"]}
            changes = []
            claimed = set()
            completed = []
            for plan in sorted(matches, key=lambda row: row["clip"] is None):
                kind, target = plan["kind"], plan["receiver"]
                graphic = next((entry for entry in data["entries"][kind] if entry["id"] == plan["entry"]), None)
                key = f"{kind}/{target}"
                error = None
                if graphic is None:
                    error = "The saved entry is unavailable."
                elif graphic.get("default_source") and graphic["default_source"] != {"scene": plan["scene"], "receiver": target}:
                    error = "The entry’s default source changed."
                elif active is None:
                    error = "Could not verify the receivers on Program."
                elif (plan["scene"], kind, target) not in active:
                    error = "The selected receiver was unavailable on Program."
                elif key in claimed:
                    error = "Another schedule already used this receiver at the clip start."
                else:
                    claimed.add(key)
                    changes.append((key, dict(items={"main":graphic}, visible=True, autoplay=False), dict(action="show")))
                result = dict(at=now.isoformat(timespec="seconds"),clip_name=schedule.playlist_title(clip_name),error=error)
                plans[plan["id"]]["rundown_result"] = result
                if not error:
                    completed.append(result)
            update_data = dict(data, scheduler=update)
            self.save(self.path, update_data)
            self.data = update_data
            try:
                self.change_outputs(changes)
            except OSError:
                for result in completed:
                    result["error"] = "Could not write the graphics output."
                self.save(self.path, update_data)
                raise
            for key, *_ in changes:
                self.previews.pop(key, None)

    def schedule_command(self, command, payload, scenes=(), playlist=()):
        with self.lock:
            data = self.read()
            now = datetime.now()
            calendar = copy.deepcopy(data["scheduler"])
            entries = {kind:copy.copy(rows) for kind,rows in data["entries"].items()}
            result = {}
            if command in ("schedule-export","schedule-sample"):
                if command=="schedule-sample":
                    template = schedule.demo(scenes,now)
                else:
                    records = []
                    for row in self.scheduler_view()["plans"]:
                        if row["graphic"] is None or not schedule.pending(row):
                            continue
                        graphic = {key:row["graphic"][key] for key in FIELDS[row["kind"]]}
                        target = {key:row[key] for key in ("kind","scene","scene_name","receiver","receiver_name")}
                        if row.get("trigger") == "rundown":
                            target.update(trigger="rundown", clip=row["clip"])
                        else:
                            target.update(start=row["start"], repeat=row["repeat"])
                        records.append(dict(target,graphic=graphic))
                    if not records:
                        raise ValueError("There are no upcoming schedules to export.")
                    template = schedule.template(records)
                folder = self.path.parent / "graphics-exports"
                folder.mkdir(parents=True,exist_ok=True)
                mode = "cnn-style-sample" if command == "schedule-sample" else "schedule"
                path = folder / f"{mode}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}.json"
                self.save(path,template)
                return dict(path=str(path))
            if command=="schedule-toggle":
                enabled = payload.get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("Choose whether Scheduler is enabled.")
                if enabled and not calendar["enabled"]:
                    for plan in calendar["plans"]:
                        if plan["next"] is None:
                            continue
                        due = schedule.next_occurrence(schedule.timestamp(plan["start"]),plan["repeat"],now.replace(second=0,microsecond=0))
                        plan["next"] = schedule.minute(due) if due else None
                calendar["enabled"] = enabled
            elif command=="schedule-import":
                created = 0
                imported = 0
                signatures = {kind:defaultdict(list) for kind in schedule.KINDS}
                for kind, matches in signatures.items():
                    for item in entries[kind]:
                        matches[tuple(item[field] for field in FIELDS[kind])].append(item)
                scheduled = {schedule.identity(row) for row in calendar["plans"] if schedule.pending(row)}
                for index,row in enumerate(schedule.template_rows(payload, FIELDS),1):
                    kind = row["kind"]
                    try:
                        target = schedule.target_of(kind,row,scenes,template=True)
                        timing = schedule.timing(row,now,playlist)
                        graphic = make_entry(kind,row["graphic"])
                        signature = tuple(graphic[field] for field in FIELDS[kind])
                        matches = signatures[kind][signature]
                        binding = {field:target[field] for field in ("scene", "receiver")}
                        existing = next((item for item in matches if item.get("default_source") == binding), None)
                        if existing is None:
                            existing = next((item for item in matches if not item.get("default_source")), None)
                        if existing is None and matches:
                            require_default_source(matches[0], target["scene"], target["receiver"])
                    except ValueError as exc:
                        raise ValueError(f"Scheduler template row {index}. {exc}") from exc
                    if existing is None:
                        entries[kind].append(graphic)
                        matches.append(graphic)
                        created += 1
                    entry = (existing or graphic)["id"]
                    record = dict(target,**timing,kind=kind,entry=entry)
                    key = schedule.identity(record)
                    if key not in scheduled:
                        calendar["plans"].append(dict(record,id=uuid4().hex))
                        scheduled.add(key)
                        imported += 1
                result = dict(imported=imported,created=created)
            elif command=="schedule-save":
                kind, entry = payload.get("kind"), payload.get("entry")
                graphic = next((row for row in entries[kind] if row["id"]==entry), None) if kind in schedule.KINDS else None
                if graphic is None:
                    raise ValueError("Choose a saved Names, Program, or Custom entry.")
                key = payload.get("id")
                existing = next((row for row in calendar["plans"] if row["id"]==key),None)
                if key and not existing:
                    raise ValueError("This schedule was already removed.")
                if existing and (kind, entry)!=(existing["kind"],existing["entry"]):
                    raise ValueError("Choose the original saved entry.")
                target = schedule.target_of(kind,payload,scenes)
                require_default_source(graphic, target["scene"], target["receiver"])
                timing = schedule.timing(payload,now,playlist)
                record = dict(target,**timing,kind=kind,entry=entry)
                if existing:
                    existing.clear()
                    existing.update(record,id=key)
                else:
                    calendar["plans"].append(dict(record,id=uuid4().hex))
            elif command in ("schedule-delete","schedule-accept","schedule-dismiss"):
                sid = payload.get("id")
                field = "plans" if command=="schedule-delete" else "queue"
                row = next((row for row in calendar[field] if row["id"]==sid),None)
                if row is None:
                    raise ValueError("This scheduled change has already been handled.")
                if command=="schedule-accept":
                    target = schedule.target_of(row["kind"],row,scenes)
                    graphic = next((item for item in entries[row["kind"]] if item["id"] == row["entry"]), None)
                    if graphic is None:
                        raise ValueError("The scheduled entry is no longer available.")
                    require_default_source(graphic, target["scene"], target["receiver"])
                    source = next(source for scene in scenes if scene["key"]==target["scene"]
                                  for source in scene["sources"] if source["key"]==target["receiver"])
                    if not source["enabled"]:
                        raise ValueError("Turn on this receiver’s visibility in OBS Sources before applying the change.")
                    snapshot = dict(row["graphic"], default_source=graphic.get("default_source")) if row["kind"] == "custom" else row["graphic"]
                    self.take(row["kind"],row["receiver"],{"action":"show","scene":target["scene"]},entry=snapshot)
                calendar[field].remove(row)
                if command=="schedule-delete":
                    calendar["queue"] = [change for change in calendar["queue"] if change["plan"]!=sid]
                result = dict(receiver=row["receiver_name"])
            else:
                raise ValueError("Choose a Scheduler action.")
            update = dict(data,scheduler=calendar,entries=entries)
            self.save(self.path,update)
            self.data = update
            return result

    def change_outputs(self, changes):
        if not changes:
            return
        updated = dict(self.live())
        for key,state,_animation in changes:
            updated[key] = state
        self.save(self.state_path,updated)
        self.outputs = updated
        self.revision = uuid4().hex
        for key,_state,animation in changes:
            if animation is not None:
                self.events[key] = dict(animation,id=uuid4().hex,at=int(time.time()*1000))

    def take(self, kind, target, data, *, entry=None):
        key = f"{kind}/{target}"
        with self.lock:
            state = dict(self.live().get(key,dict(items={},visible=False)))
            action = data["action"]
            event = None
            if action == "hide":
                state["visible"] = False
                state["autoplay"] = False
                event = dict(action="hide")
            elif action == "autoplay-stop":
                state["autoplay"] = False
            else:
                state["visible"] = True
                if kind in ("clock", "date"):
                    items = {}
                else:
                    entries = self.read()["entries"][kind]
                    if kind == "crawlers":
                        if not entries:
                            raise ValueError("Save at least one crawler entry first.")
                        items = dict(parts=[item["text"] for item in entries])
                    else:
                        if entry is None:
                            entry = next((item for item in entries if item["id"] == data.get("id")),None)
                        if entry is None and action == "autoplay-start" and entries:
                            entry = entries[0]
                        if entry is None:
                            raise ValueError("Select a saved entry to display.")
                        require_default_source(entry, data.get("scene"), target)
                        items = entry
                state.update(items={"main":items}, autoplay=action == "autoplay-start")
                event = dict(action="show")
            self.previews.pop(key, None)
            self.change_outputs([(key,state,event)])
            self.deadlines.pop(key,None)
            return bool(state.get("autoplay"))

    def scene_live(self, sources):
        with self.lock:
            master = self.read()["settings"]["master"]
            changes = []
            for source in sources:
                kind, target = source["kind"], source["key"]
                key = f"{kind}/{target}"
                saved = self.live().get(key)
                if source["enabled"] and master[kind] and saved and saved["items"]:
                    changes.append((key,dict(saved, visible=True),dict(action="show", scene=True)))
            self.change_outputs(changes)

    def advance(self, now):
        with self.lock:
            if not any(state.get("autoplay") for state in self.live().values()):
                return
            entries = self.read()["entries"]["headlines"]
            style = self.read()["styles"]["headlines"]
            changes = []
            for key,state in self.live().items():
                if not key.startswith("headlines/") or not state["visible"] or not state.get("autoplay"):
                    continue
                target = self.deadlines.setdefault(key,now + style["interval"])
                if now < target or not entries:
                    continue
                selected = state["items"].get("main",{}).get("id")
                index = next((i for i,item in enumerate(entries) if item["id"] == selected),-1)
                item = entries[(index+1) % len(entries)]
                self.deadlines[key] = now + style["interval"]
                changes.append((key,dict(state,items={"main":item}),dict(action="show", cut=style["advance"] == "cut")))
            self.change_outputs(changes)

    def preview(self, kind, target, data):
        key = f"{kind}/{target}"
        with self.lock:
            if data["action"] == "preview-stop":
                self.previews.pop(key, None)
                return
            style = validate_style(kind, data.get("style"))
            style = self.render_style(kind, style)
            item = data.get("item")
            items = {}
            if kind in ("clock", "date"):
                items = {"main":{}}
            elif item is not None:
                if not isinstance(item, dict):
                    raise ValueError("Choose a valid preview entry.")
                if kind == "crawlers":
                    parts = item.get("parts")
                    if not isinstance(parts,list) or not parts:
                        raise ValueError("Enter crawler text to preview.")
                    items = {"main":{"parts":[entry_text(part,required=True,limit=2000) for part in parts]}}
                else:
                    items = {"main":make_entry(kind,item)}
                    items["main"].pop("id")
            previous = self.previews.get(key, {})
            action = data.get("motion")
            frame = dict(style=style,items={} if data.get("hidden") is True or action=="hide" else items,scene=data["scene"])
            if action in ("show","hide") or any(previous.get(name) != value for name,value in frame.items()):
                frame["revision"] = uuid4().hex
                frame["event"] = dict(action=action,id=frame["revision"]) if action in ("show","hide") else None
            else:
                frame.update(revision=previous["revision"],event=previous["event"])
            self.previews[key] = dict(frame,expires=time.monotonic()+2.5)

    def preview_scene(self, kind, target):
        with self.lock:
            key = f"{kind}/{target}"
            frame = self.previews.get(key)
            if frame and frame["expires"] > time.monotonic():
                return frame["scene"]
            self.previews.pop(key,None)
            return None

    def output(self, kind, target, revision=None, *, preview_scene=None):
        with self.lock:
            key = f"{kind}/{target}"
            preview = self.previews.get(key)
            if not preview or preview["scene"] != preview_scene or preview["expires"] <= time.monotonic():
                preview = None
            outgoing = self.revision + (preview["revision"] if preview else "")
            if revision == outgoing:
                return None
            data = self.read()
            style = self.render_style(kind, data["styles"][kind])
            state = self.live().get(key,{})
            items = state.get("items",{}) if state.get("visible") else {}
            public_items = {slot:{field:value for field,value in item.items() if field != "id"} for slot,item in items.items()}
            result = dict(revision=outgoing, kind=kind, style=style, items=public_items,
                          event=self.events.get(key), autoplay=bool(state.get("autoplay")))
            if preview:
                result["preview"] = {key:preview[key] for key in ("items","style","event")}
            return result

    def render_style(self, kind, style):
        settings = self.read()["settings"]
        style = dict(style)
        if settings["override"]:
            style["family"] = settings["family"]
        if kind == "custom":
            style["custom_override"] = settings["custom_override"]
        return style


def scene_key(scene):
    value = scene.get("sceneUuid") or scene["sceneName"]
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def scene_targets(response):
    return [dict(name=item["sceneName"], key=scene_key(item)) for item in response.scenes]


def walk_scene_items(client, name, *, nested=True, active_only=False):
    visited = set()

    def walk(container, group, enabled):
        key = (container, group, enabled)
        if key in visited:
            return
        visited.add(key)
        items = (client.get_group_scene_item_list(container) if group else client.get_scene_item_list(container)).scene_items
        for item in items:
            active = enabled and item.get("sceneItemEnabled") is not False
            if active_only and not active:
                continue
            yield item, active
            child = item["sourceName"]
            if item.get("isGroup") and hasattr(client, "get_group_scene_item_list"):
                yield from walk(child, True, active)
            elif nested and item.get("sourceType") == "OBS_SOURCE_TYPE_SCENE":
                yield from walk(child, False, active)

    yield from walk(name, False, True)


def scene_sources(client, name, origin, known=None, *, nested=False):
    registered = {} if known is None else known
    sources = []

    for item, enabled in walk_scene_items(client, name, nested=nested):
        source = item["sourceName"]
        if item.get("inputKind") != "browser_source":
            continue
        if source not in registered:
            settings = client.get_input_settings(source).input_settings
            marker = settings.get(OWNER, "")
            match = re.fullmatch(r"([a-z]+)/([a-f0-9]{32})",marker) if isinstance(marker,str) else None
            base = f"{origin}/graphics-overlay/{marker}"
            registered[source] = None
            if match and match[1] in LABELS and settings.get("url") in (base,base+"?compact=1"):
                width, height = settings.get("width"), settings.get("height")
                registered[source] = dict(kind=match[1], key=match[2], compact=settings["url"] == base+"?compact=1",
                                          width=width if type(width) is int and width > 0 else None,
                                          height=height if type(height) is int and height > 0 else None)
        match = registered[source]
        if match is not None:
            sources.append(dict(match, name=source, enabled=enabled))
    unique = {}
    for source in sources:
        key = source["kind"], source["key"]
        if source["enabled"] or key not in unique:
            unique[key] = source
    return list(unique.values())


def scenes(client, origin):
    response = client.get_scene_list()
    preview = getattr(response,"current_preview_scene_name",None)
    preferred = preview or response.current_program_scene_name
    targets = scene_targets(response)
    known = {}
    for scene in targets:
        scene["sources"] = scene_sources(client,scene["name"],origin,known)
    return dict(scenes=targets,preferred=preferred,preview=preview,program=response.current_program_scene_name)


def program_receivers(client, response, program, origin):
    active_scenes = {program}
    active_scenes.update(item["sourceName"] for item, _ in walk_scene_items(client, program, active_only=True)
                         if not item.get("isGroup") and item.get("sourceType") == "OBS_SOURCE_TYPE_SCENE")
    known = {}
    receivers = {(scene["key"], source["kind"], source["key"])
                 for scene in scene_targets(response) if scene["name"] in active_scenes
                 for source in scene_sources(client, scene["name"], origin, known) if source["enabled"]}
    return receivers if client.get_current_program_scene().current_program_scene_name == program else set()


def set_up_source(client, kind, scene_id, origin, style, *, follow_preview=False, entry=None):
    response = client.get_scene_list()
    targets = scene_targets(response)
    if follow_preview:
        preview = getattr(response, "current_preview_scene_name", None) or response.current_program_scene_name
        current = next((item for item in targets if item["name"] == preview), None)
        if current is None or (scene_id is not None and current["key"] != scene_id):
            raise ValueError("The preview scene changed. Wait for the dock to update and try again.")
        scene_id = current["key"]
    scene = next((item for item in targets if item["key"] == scene_id),None)
    if scene is None:
        raise ValueError("That OBS scene changed. Reload the scene list and select it again.")
    existing = scene_sources(client,scene["name"],origin)
    if kind not in MULTIPLE_RECEIVERS and (current := next((item for item in existing if item["kind"] == kind
                                              and (kind != "clock" or item["compact"])),None)):
        return dict(source=current["name"],scene=scene["name"],key=current["key"])
    taken = {item["inputName"].casefold() for item in client.get_input_list().inputs}
    taken.update(item["name"].casefold() for item in targets)
    if hasattr(client,"get_group_list"):
        taken.update(name.casefold() for name in client.get_group_list().groups)
    suffix=1
    base = source = f"Toolkit {LABELS[kind]}"
    if kind in MULTIPLE_RECEIVERS:
        while f"{base} • Receiver {suffix}".casefold() in taken:
            suffix+=1
        source = f"{base} • Receiver {suffix}"
    elif source.casefold() in taken:
        source = f"{base} • {scene['name']}"
        while source.casefold() in taken:
            suffix+=1
            source = f"{base} • {scene['name']} ({suffix})"
    key = uuid4().hex
    marker = f"{kind}/{key}"
    width, height = DIMENSIONS[kind]
    canvas = client.get_video_settings()
    ratio = canvas.base_width / 1920
    width,height = max(1,round(width*ratio)),max(1,round(height*ratio))
    settings = dict(url=f"{origin}/graphics-overlay/{marker}?compact=1",width=width,height=height,is_local_file=False,
                    shutdown=True,restart_when_active=False,reroute_audio=False,webpage_control_level=0,**{OWNER:marker})
    item = client.create_input(scene["name"],source,"browser_source",settings,True)
    names_count = sum(s["kind"] == "names" for s in existing) if kind == "names" else 0
    x = style["right"] if names_count % 2 else style["x"]
    y = style["y"] + names_count // 2 * 11
    if kind == "custom":
        count = sum(s["kind"] == kind for s in existing)
        entry = entry or {}
        horizontal, vertical = entry.get("horizontal"), entry.get("vertical")
        side_x = 100 * (1 - width / canvas.base_width)
        side_y = 100 * (1 - height / canvas.base_height)
        x = {"left": 4, "center": side_x / 2, "right": side_x - 4}.get(horizontal, 4 if count % 2 else x)
        y = {"top": 5, "middle": side_y / 2, "bottom": side_y - 5}.get(vertical, y + count // 2 * 11)
    try:
        client.set_scene_item_transform(scene["name"],item.scene_item_id,dict(
            positionX=max(0,min(canvas.base_width*x/100,canvas.base_width-width)),
            positionY=max(0,min(canvas.base_height*y/100,canvas.base_height-height)),alignment=5))
    except Exception:
        client.remove_input(source)
        raise
    return dict(source=source,scene=scene["name"],key=key)

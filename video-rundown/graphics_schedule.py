"""Local wall-clock schedule and the versioned schedule template."""
from calendar import monthrange
from datetime import datetime, timedelta
import re
from uuid import uuid4

KINDS = ("names", "programs")
REPEATS = ("once", "weekly", "monthly", "yearly")
SCHEMA = "obs-controls-toolkit.graphics-schedule"
MINUTE = "%Y-%m-%dT%H:%M"
ID = re.compile(r"[a-f0-9]{32}")


def timestamp(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", value):
        try:
            return datetime.strptime(value, MINUTE)
        except ValueError:
            pass
    raise ValueError("Enter a valid local date and time.")


def minute(value):
    return value.strftime(MINUTE)


def next_occurrence(anchor, repeat, earliest):
    """First occurrence on or after earliest. Clamp month ends from the original date."""
    if anchor >= earliest:
        return anchor
    if repeat == "once":
        return None
    if repeat == "weekly":
        weeks = (earliest - anchor).days // 7
        candidate = anchor + timedelta(weeks=weeks)
        return candidate if candidate >= earliest else candidate + timedelta(weeks=1)
    for gap in (0, 1):
        if repeat == "monthly":
            year, zero_month = divmod(earliest.year*12 + earliest.month-1 + gap,12)
            month = zero_month + 1
        else:
            year, month = earliest.year+gap, anchor.month
        if year > 9999:
            return None
        candidate = anchor.replace(year=year,month=month,day=min(anchor.day,monthrange(year,month)[1]))
        if candidate >= earliest:
            return candidate
    return None


def is_id(value):
    return isinstance(value,str) and ID.fullmatch(value) is not None


def label(value):
    if not isinstance(value,str) or len(value)>500 or not value.strip() or any(ord(char)<32 for char in value):
        raise ValueError("Enter a valid OBS scene and receiver name.")
    return value.strip()


def target_of(kind, data, scenes, *, template=False):
    scene_id, receiver_id = data.get("scene"), data.get("receiver")
    if template:
        scene_name, receiver_name = label(data.get("scene_name")), label(data.get("receiver_name"))
        scene = next((row for row in scenes if row["key"]==scene_id or row["name"]==scene_name),None)
    else:
        scene = next((row for row in scenes if row["key"]==scene_id),None)
    if not scene:
        raise ValueError("That scene was not found in OBS.")
    receiver = next((row for row in scene["sources"] if row["kind"]==kind and
                     (row["key"]==receiver_id or (template and row["name"]==receiver_name))),None)
    if not receiver:
        raise ValueError("That graphics receiver was not found in the selected OBS scene.")
    return dict(scene=scene["key"], scene_name=scene["name"], receiver=receiver["key"], receiver_name=receiver["name"])


def timing(data, now):
    repeat, start = data.get("repeat"), timestamp(data.get("start"))
    if repeat not in REPEATS:
        raise ValueError("Choose Once, Weekly, Monthly, or Yearly.")
    following = next_occurrence(start,repeat,now.replace(second=0,microsecond=0))
    if following is None:
        raise ValueError("The schedule has no upcoming occurrence. Choose a future time.")
    return dict(start=minute(start), repeat=repeat, next=minute(following))


def clean(data, make_entry):
    if not isinstance(data,dict) or type(data.get("enabled",False)) is not bool:
        raise ValueError("The graphics scheduler data is invalid.")
    plans, queue = data.get("plans",[]), data.get("queue",[])
    if not isinstance(plans,list) or not isinstance(queue,list):
        raise ValueError("The graphics scheduler data is invalid.")
    result = dict(enabled=data.get("enabled",False), plans=[], queue=[])
    for records, key in ((plans,"plans"),(queue,"queue")):
        seen = set()
        for row in records:
            if (not isinstance(row,dict) or any(not is_id(row.get(field)) for field in ("id","entry","scene","receiver"))
                    or row["id"] in seen or row.get("kind") not in KINDS):
                raise ValueError("The graphics scheduler contains an invalid or duplicate row.")
            seen.add(row["id"])
            record = {field:row[field] for field in ("id","entry","scene","receiver","kind")}
            record.update(scene_name=label(row.get("scene_name")),receiver_name=label(row.get("receiver_name")))
            if key == "plans":
                if row.get("repeat") not in REPEATS:
                    raise ValueError("The graphics scheduler contains an invalid repeat setting.")
                record.update(start=minute(timestamp(row.get("start"))),repeat=row["repeat"],
                              next=minute(timestamp(row["next"])) if row.get("next") is not None else None)
            else:
                if not is_id(row.get("plan")) or not isinstance(row.get("graphic"),dict):
                    raise ValueError("The graphics approval queue contains an invalid change.")
                record.update(plan=row["plan"],due=minute(timestamp(row.get("due"))),
                              graphic=make_entry(row["kind"],row["graphic"],row["entry"]))
            result[key].append(record)
    return result


def due_changes(schedule, entries, now, limit=100):
    """Advance alongside queue persistence. No output is changed here."""
    if not schedule["enabled"]:
        return False
    changed = False
    by_id = {kind:{row["id"]:row for row in entries[kind]} for kind in KINDS}
    for plan in sorted(schedule["plans"],key=lambda row:row["next"] or "9999"):
        while plan["next"] and limit and timestamp(plan["next"]) <= now:
            due = timestamp(plan["next"])
            graphic = by_id[plan["kind"]].get(plan["entry"])
            if graphic:
                change = {field:plan[field] for field in ("entry","scene","scene_name","receiver","receiver_name","kind")}
                schedule["queue"].append(dict(change,id=uuid4().hex,plan=plan["id"],due=minute(due),graphic=graphic.copy()))
            future = next_occurrence(timestamp(plan["start"]),plan["repeat"],due+timedelta(minutes=1))
            plan["next"] = minute(future) if future else None
            limit -= 1
            changed = True
    if changed:
        schedule["queue"].sort(key=lambda row:row["due"])
    return changed


def template(records):
    return dict(schema=SCHEMA,version=1,schedules=records)


def template_rows(data):
    if (not isinstance(data,dict) or set(data)!={"schema","version","schedules"} or data.get("schema")!=SCHEMA
            or type(data.get("version")) is not int or data["version"]!=1 or not isinstance(data.get("schedules"),list)):
        raise ValueError("Choose a Toolkit Scheduler v1 JSON template.")
    if not data["schedules"] or len(data["schedules"])>5000:
        raise ValueError("Include between 1 and 5,000 schedules in the template.")
    required = {"kind","graphic","start","repeat","scene_name","receiver_name"}
    for index,row in enumerate(data["schedules"],1):
        if (not isinstance(row,dict) or not required <= row.keys() or row.keys()-required-{"scene","receiver"}
                or row.get("kind") not in KINDS or not isinstance(row.get("graphic"),dict)
                or any(field in row and not is_id(row[field]) for field in ("scene","receiver"))):
            raise ValueError(f"Invalid Scheduler template row {index}.")
        fields = {"text","description","show_description"} if row["kind"]=="names" else {"text"}
        if not row["graphic"].keys() <= fields or "text" not in row["graphic"]:
            raise ValueError(f"Invalid graphic fields in Scheduler template row {index}.")
    return data["schedules"]


def demo(scenes, today):
    examples = (
        ("names","Jordan Reyes","Anchor · New York","weekly"),
        ("names","Maya Brooks","Correspondent · Washington","monthly"),
        ("programs","World Desk Tonight","","yearly"),
    )
    records = []
    for index,(kind,text,description,repeat) in enumerate(examples,1):
        scene, receiver = next(((row,source) for row in scenes for source in row["sources"] if source["kind"]==kind), ({},{}))
        graphic = dict(text=text)
        if kind=="names":
            graphic.update(description=description,show_description=True)
        start = (today+timedelta(days=index)).replace(hour=18+index,minute=0)
        records.append(dict(kind=kind,graphic=graphic,start=minute(start),repeat=repeat,
                            scene_name=scene.get("name","Choose your OBS scene"),
                            receiver_name=receiver.get("name","Choose your Toolkit receiver")))
    return template(records)

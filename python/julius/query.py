"""Inclusive-start/exclusive-end reporting windows."""

import re
from datetime import datetime, time, timedelta, timezone


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def query_window(options: dict | None = None, now: datetime | None = None) -> dict[str, str]:
    options = options or {}
    # Stored events have millisecond precision. Include a just-recorded event in
    # the default moving window while keeping the documented exclusive end.
    current = now if now is not None else datetime.now(timezone.utc) + timedelta(milliseconds=1)
    value = options.get("since") or "7d"
    if value == "previous-week":
        if options.get("until"):
            raise ValueError("--until cannot be combined with previous-week")
        local_now = now if now is not None else datetime.now().astimezone()
        monday = local_now.date() - timedelta(days=local_now.weekday())
        prior_monday = monday - timedelta(days=7)
        if now is None:
            # Naive local dates use the system timezone rules for each midnight,
            # including a daylight-saving transition inside the previous week.
            start = datetime.combine(prior_monday, time.min).astimezone(timezone.utc)
            end = datetime.combine(monday, time.min).astimezone(timezone.utc)
        else:
            start = datetime.combine(prior_monday, time.min, local_now.tzinfo).astimezone(timezone.utc)
            end = datetime.combine(monday, time.min, local_now.tzinfo).astimezone(timezone.utc)
        label = str(local_now.tzinfo)
    else:
        end = _parse_date(options["until"]) if options.get("until") else current
        duration = re.fullmatch(r"(\d+)([dhm])", value)
        if duration:
            seconds = int(duration[1]) * {"d": 86400, "h": 3600, "m": 60}[duration[2]]
            start = end - timedelta(seconds=seconds)
        else:
            start = _parse_date(value)
        label = str(datetime.now().astimezone().tzinfo)
    if start >= end:
        raise ValueError("The start must precede the exclusive end.")
    return {
        "since": iso_utc(start),
        "until": iso_utc(end),
        "timezone": label,
    }


def _parse_date(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", value):
        raise ValueError(f"Invalid date: {value}")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.astimezone(timezone.utc)

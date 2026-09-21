"""Inclusive-start/exclusive-end reporting windows."""

import re
from datetime import datetime, timedelta, timezone


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def query_window(options: dict | None = None, now: datetime | None = None) -> dict[str, str]:
    options = options or {}
    # Stored events have millisecond precision. Include a just-recorded event in
    # the default moving window while keeping the documented exclusive end.
    current = now if now is not None else datetime.now(timezone.utc) + timedelta(milliseconds=1)
    end = _parse_date(options["until"]) if options.get("until") else current
    value = options.get("since") or "7d"
    duration = re.fullmatch(r"(\d+)([dhm])", value)
    if duration:
        seconds = int(duration[1]) * {"d": 86400, "h": 3600, "m": 60}[duration[2]]
        start = end - timedelta(seconds=seconds)
    else:
        start = _parse_date(value)
    if start >= end:
        raise ValueError("The start must precede the exclusive end.")
    return {
        "since": iso_utc(start),
        "until": iso_utc(end),
        "timezone": str(datetime.now().astimezone().tzinfo),
    }


def _parse_date(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", value):
        raise ValueError(f"Invalid date: {value}")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.astimezone(timezone.utc)

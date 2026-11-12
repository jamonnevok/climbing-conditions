from __future__ import annotations

from datetime import datetime, timedelta, timezone

H = timedelta(hours=1)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def parse(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    if len(s) == 16:  # YYYY-MM-DDTHH:MM without zone -> UTC
        s += "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

"""Daily score, best 2-4 h window, drying time, outlook."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .timeutil import H, iso, parse


def local(t_iso: str, tz: ZoneInfo) -> datetime:
    return parse(t_iso).astimezone(tz)


def is_daytime(t_iso: str, tz: ZoneInfo, hours: list[int]) -> bool:
    return hours[0] <= local(t_iso, tz).hour < hours[1]


def best_window(rows: list[dict], mode: str, lengths: list[int], tolerance: float):
    """Best contiguous run of scored hours. Picks the best 2 h mean, then the
    longest window whose mean is within `tolerance` of it."""
    best = {}
    for L in lengths:
        for i in range(len(rows) - L + 1):
            seg = rows[i:i + L]
            if any(r["score"].get(mode) is None for r in seg):
                continue
            if any(parse(b["t"]) - parse(a["t"]) != H for a, b in zip(seg, seg[1:])):
                continue
            mean = sum(r["score"][mode] for r in seg) / L
            if L not in best or mean > best[L][0]:
                best[L] = (mean, seg[0]["t"], iso(parse(seg[-1]["t"]) + H))
    if not best:
        return None
    ref = best[min(best)][0]
    L = max(k for k, v in best.items() if v[0] >= ref - tolerance)
    mean, start, end = best[L]
    return {"start": start, "end": end, "score": round(mean, 1), "hours": L}


def hours_to_dry(rows: list[dict], start_idx: int, dry_ok: float):
    """Hours from rows[start_idx] until wet_mm <= dry_ok. -1 if not within the timeline."""
    for j in range(start_idx, len(rows)):
        w = rows[j].get("wet_mm")
        if w is not None and w <= dry_ok:
            return j - start_idx, rows[j]["t"]
    return -1, None


def day_groups(rows: list[dict], tz: ZoneInfo, now: datetime, n_days: int):
    today = now.astimezone(tz).date()
    groups = []
    for d in range(n_days):
        date = today + timedelta(days=d)
        idx = [i for i, r in enumerate(rows) if local(r["t"], tz).date() == date]
        groups.append((date, idx))
    return groups

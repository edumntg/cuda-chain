"""Org policy: stored in the settings table, with the config file as the default."""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session

from . import db
from .config import OrgPolicy, Window

KEY = "policy"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def load(session: Session, default: OrgPolicy) -> OrgPolicy:
    row = session.get(db.Setting, KEY)
    if row is None:
        return default
    return OrgPolicy.model_validate(json.loads(row.value.decode("utf-8")))


def save(session: Session, policy: OrgPolicy) -> None:
    value = json.dumps(policy.model_dump(mode="json")).encode("utf-8")
    row = session.get(db.Setting, KEY)
    if row is None:
        session.add(db.Setting(key=KEY, value=value))
    else:
        row.value = value


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def window_open(window: Window, at: dt.datetime) -> bool:
    """True when `at` (local time) falls inside the window. Windows may cross midnight."""
    minute = at.hour * 60 + at.minute
    day = DAYS[at.weekday()]
    start, end = _minutes(window.start), _minutes(window.end)
    if start <= end:
        return day in window.days and start <= minute < end
    # crosses midnight: the part after `start` belongs to `day`, the part before `end` to the day before
    if day in window.days and minute >= start:
        return True
    yesterday = DAYS[(at.weekday() - 1) % 7]
    return yesterday in window.days and minute < end


def available(policy: OrgPolicy, at: dt.datetime | None = None) -> tuple[bool, str]:
    """Return (available, reason). An empty window list means always available."""
    at = at or dt.datetime.now()
    if not policy.windows:
        return True, ""
    for w in policy.windows:
        if window_open(w, at):
            return True, ""
    desc = "; ".join(f"{','.join(w.days)} {w.start}-{w.end}" for w in policy.windows)
    return False, f"outside window ({desc})"


def parse_hours(text: str) -> Window:
    """`19:00-08:00` or `weekdays 19:00-08:00` or `sat,sun 00:00-23:59`."""
    parts = text.split()
    span = parts[-1]
    days: list[str]
    if len(parts) == 1 or parts[0] in ("daily", "every"):
        days = list(DAYS)
    elif parts[0] == "weekdays":
        days = list(DAYS[:5])
    elif parts[0] == "weekends":
        days = ["sat", "sun"]
    else:
        days = [d.strip() for d in parts[0].split(",")]
    start, end = span.split("-")
    return Window(days=days, start=start, end=end)  # type: ignore[arg-type]

"""Injectable clock. Business logic never calls datetime.now() directly —
the Saturday-due-date and Eastern Time rules depend on a controllable "now",
and tests freeze it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


@dataclass(frozen=True)
class FrozenClock:
    """A clock pinned to one instant. The only Clock the harness ships."""

    instant: datetime

    def now(self) -> datetime:
        return self.instant

    def today(self) -> date:
        return self.instant.astimezone(EASTERN).date()

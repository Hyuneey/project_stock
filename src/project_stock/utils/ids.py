from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from uuid import uuid4

_COUNTERS: dict[str, count] = {}


def make_id(prefix: str, when: datetime | None = None) -> str:
    """Create a readable unique identifier with a stable prefix."""
    when = when or datetime.now(UTC)
    seq = next(_COUNTERS.setdefault(prefix, count(1)))
    return f"{prefix}_{when:%Y%m%d}_{seq:06d}_{uuid4().hex[:6].upper()}"

"""Feed-level freshness state: one classification, one cache, four states.

Before this module existed, feed freshness was computed independently in
three places (``scheduler.is_stale``, ``data_refresh.data_freshness`` and an
inline pair of queries in ``/health``), and none of them could distinguish
"the database has no price rows" from "the database could not be reached":
a connection failure was reported the same as an empty feed, or (in the
scheduler) silently swallowed and read as *current*. This module is the
single classification every feed-level consumer shares.

The four states, and the rule that ties them together:

* ``FRESH``        — the newest market date is within ``price_max_age_days``.
* ``STALE``        — price rows exist but the newest one is older than the SLA.
* ``EMPTY``        — the query SUCCEEDED and the price table has no rows.
* ``UNAVAILABLE``  — freshness could not be determined: the query raised, or
                     rows exist but carry no usable date. NEVER ``FRESH``
                     and never implied by absence of data.

Database exceptions must map to ``UNAVAILABLE`` — never ``EMPTY`` (which
claims "we looked and there was nothing") and never ``FRESH``. Unknown is
reported as unknown.

The cache (``FRESHNESS``) exists so ``/health`` can answer without touching
the database at all — a load-balancer probe must not cost three queries per
hit, and must never re-derive freshness with its own ad-hoc rules. Its
contract:

* Initial state is ``UNAVAILABLE`` ("no check has completed yet"), which is
  conservative: a process that never reached the database says so rather
  than claiming a fresh feed. This is what lets ``/health`` tests run
  without lifespan or the scheduler.
* Only *lifecycle code* updates it — the startup warm-up in ``main.lifespan``,
  the independent read-only monitor (``scheduler.freshness_monitor_loop``,
  which runs whatever ``REFRESH_ENABLED`` says), every ``scheduler.is_stale()``
  read, every completed ``refresh_once`` attempt, and a successful
  ``/internal/data/status`` read (which shares its freshly computed
  snapshot rather than querying twice). Health requests only read.
* A failed read sets ``UNAVAILABLE`` with the (redacted) reason. It does NOT
  keep a previous ``FRESH`` alive, because an unreachable database makes the
  stored "fresh" claim unverifiable, and a stale-but-unverifiable cache is
  exactly the misleading signal this stage exists to remove.
* Even a successfully ``set`` snapshot expires: once older than
  ``freshness_cache_ttl_seconds`` the effective state degrades to
  ``UNAVAILABLE`` ("no freshness check has run recently"). Nothing forces a
  background recompute — expiry keeps the cache honest rather than lucky.

Safe for the single-threaded asyncio/FastAPI loop by construction: the
snapshot is one immutable frozen dataclass swapped by an atomic attribute
store under a small lock (so an executor-thread warm-up and the loop can
never interleave a torn read). No external cache framework — one module
global, no dependencies.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Callable

from sqlalchemy import func, select

from backend.core.config import redact_secrets, settings
from backend.core.models import CropDeclaration, MandiPrice


class FreshnessState(str, Enum):
    """The four feed-level states. Values are the wire strings in responses."""

    FRESH = "fresh"
    STALE = "stale"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


def normalise_market_date(value: Any) -> date | None:
    """arrival_date reaches us as datetime, date or str depending on driver."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


@dataclass(frozen=True)
class FreshnessSnapshot:
    """One determination of feed freshness, plus when it was made.

    ``checked_at`` is ``time.monotonic()`` (age maths), ``checked_at_wall``
    is a real timestamp for reporting only. Both are ``None`` for the
    never-computed initial snapshot.
    """

    state: FreshnessState
    newest_market_date: date | None = None
    age_days: int | None = None
    rows: int | None = None
    declarations: int | None = None
    max_age_days: int = field(default_factory=lambda: settings.price_max_age_days)
    detail: str | None = None
    checked_at: float | None = None
    checked_at_wall: datetime | None = None
    # Connectivity is a SEPARATE fact from freshness (review B1): the last
    # check either reached the database or it did not, independent of what
    # the data said. ``None`` = no check has run yet (never claim, never
    # assume); ``True`` = the query completed, including a valid EMPTY/STALE
    # result; ``False`` = the query failed. A TTL expiry downgrade deliberately
    # PRESERVES this field: an expired verdict says "we cannot currently prove
    # the feed is fresh", which does not retract "we reached the database at
    # the last check".
    db_reachable: bool | None = None

    @property
    def forecastable(self) -> bool:
        """The ONLY state that supports a forecast. Unknown is never
        forecastable, and neither is a confident-looking cached date."""
        return self.state is FreshnessState.FRESH

    def is_current(self, *, ttl_seconds: int, now: float) -> bool:
        return (
            self.checked_at is not None
            and (now - self.checked_at) <= ttl_seconds
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "newest_market_date": (
                self.newest_market_date.isoformat()
                if self.newest_market_date else None
            ),
            "age_days": self.age_days,
            "rows": self.rows,
            "declarations": self.declarations,
            "max_age_days": self.max_age_days,
            "forecastable": self.forecastable,
            "detail": self.detail,
            "db_reachable": self.db_reachable,
            "checked_at": (
                self.checked_at_wall.isoformat() if self.checked_at_wall else None
            ),
        }


def unavailable(detail: str, *, db_reachable: bool | None = None) -> FreshnessSnapshot:
    """Explicit UNAVAILABLE — use for 'we could not determine freshness'.

    ``db_reachable`` stays ``None`` (no connectivity observation) for the
    never-checked initial state; callers that know the database was reached
    and said no, or was not reached at all, pass False explicitly.
    """
    return FreshnessSnapshot(state=FreshnessState.UNAVAILABLE, detail=detail,
                             db_reachable=db_reachable)


async def compute_freshness(
    db,
    *,
    today: date | None = None,
    started_at: float | None = None,
) -> FreshnessSnapshot:
    """Classify the feed from live tables. NEVER raises.

    A database error here is a fact to report (``UNAVAILABLE`` + redacted
    reason), not an exception for each caller to interpret differently —
    divergent interpretation of the same failure is what this module exists
    to prevent. The three aggregates are the only queries freshness needs;
    they are read-only and cheap.

    ``started_at`` (or the value captured here, before any query) is the
    ORDERING timestamp stored in ``checked_at``. Stamping at START, not
    completion, is what lets ``FreshnessCache.set`` reject a stalled
    older computation that finishes after a newer one already recorded the
    outage it began before (review R1). A caller that opened the session —
    ``FreshnessCache.refresh`` — passes its own pre-session stamp so the
    whole attempt orders by when checking began.
    """
    today = today or datetime.now(timezone.utc).date()
    t_start = started_at if started_at is not None else time.monotonic()
    try:
        newest_raw = (await db.execute(
            select(func.max(MandiPrice.arrival_date))
        )).scalar_one_or_none()
        rows = (await db.execute(
            select(func.count()).select_from(MandiPrice)
        )).scalar() or 0
        declarations = (await db.execute(
            select(func.count()).select_from(CropDeclaration)
        )).scalar() or 0
    except Exception as exc:  # noqa: BLE001 — failure IS the data point
        # The failed query is itself a connectivity observation: the database
        # was NOT reachable (or not usable). UNAVAILABLE + db_reachable=False.
        # Carries the START stamp (and a timestamp at all) so this failure
        # participates in set()'s ordering: a newer failure must be able to
        # beat an older stalled success, and vice versa.
        return FreshnessSnapshot(
            state=FreshnessState.UNAVAILABLE,
            detail=f"freshness query failed: {redact_secrets(str(exc))[:300]}",
            db_reachable=False,
            checked_at=t_start,
            checked_at_wall=datetime.now(timezone.utc),
        )

    base = {
        "rows": rows,
        "declarations": declarations,
        "max_age_days": settings.price_max_age_days,
        # Reaching here means every aggregate query completed — even the
        # EMPTY and unusable-date verdicts are statements about DATA made
        # over a working connection.
        "db_reachable": True,
        # Ordering stamp: when this computation BEGAN, not when it finished.
        # checked_at_wall remains the human-readable completion time.
        "checked_at": t_start,
        "checked_at_wall": datetime.now(timezone.utc),
    }
    newest = normalise_market_date(newest_raw)
    if newest is None:
        # The query succeeded, so this is a statement about the DATA, not the
        # connection: no rows at all is EMPTY; rows without a usable date
        # cannot be aged, which is genuinely UNABLE-TO-DETERMINE, not empty.
        if rows == 0:
            return FreshnessSnapshot(
                state=FreshnessState.EMPTY,
                detail="the price table has no rows",
                **base,
            )
        return FreshnessSnapshot(
            state=FreshnessState.UNAVAILABLE,
            detail=f"{rows} price rows carry no usable arrival_date",
            **base,
        )

    age_days = (today - newest).days
    if age_days <= settings.price_max_age_days:
        return FreshnessSnapshot(
            state=FreshnessState.FRESH, newest_market_date=newest,
            age_days=age_days, **base,
        )
    return FreshnessSnapshot(
        state=FreshnessState.STALE, newest_market_date=newest,
        age_days=age_days,
        detail=f"newest market date is {age_days} days old (SLA {settings.price_max_age_days})",
        **base,
    )


class FreshnessCache:
    """The one mutable freshness value the process shares."""

    def __init__(self) -> None:
        # Conservative by construction: nobody has proven the feed fresh yet.
        self._snapshot = unavailable("no freshness check has completed yet")
        self._lock = threading.Lock()

    def set(self, snapshot: FreshnessSnapshot) -> FreshnessSnapshot:
        """Order-guarded store: an older-started computation never overwrites
        a newer-started snapshot (review R1).

        ``checked_at`` is the computation START stamp, so the comparison
        reflects when each observation began, not when it happened to
        finish — a freshness query that stalls across an outage cannot come
        back later and replace the UNAVAILABLE a newer check already
        recorded. Comparison and replacement are one atomic step under the
        cache lock. Explicit rules:

        * current has no timestamp — only the never-computed initial state
          can be in this position, and no computation can predate module
          import, so any computed result replaces it (there is no older/newer
          relation yet). The startup "could not reach the database" marker is
          NOT untimestamped: it carries a real start stamp (review R1) so it
          orders against concurrent checks instead of erasing a newer
          observation's stamp and letting a stalled older success land behind
          it;
        * incoming has no timestamp → it is an EXPLICIT INVALIDATION (an
          untimestamped claim of "unknown", ``db_reachable`` included) and
          always wins — it asserts no data, so it can never be a stale
          overwrite of a newer observation;
        * equal start stamps → the later write wins (deterministic).

        Returns the snapshot the cache actually holds after the operation,
        which may differ from the incoming one if it was rejected as older.
        """
        with self._lock:
            current = self._snapshot
            if (current.checked_at is None
                    or snapshot.checked_at is None
                    or snapshot.checked_at >= current.checked_at):
                self._snapshot = snapshot
            return self._snapshot

    def get(self) -> FreshnessSnapshot:
        """Effective snapshot now: an expired cache degrades to UNAVAILABLE.

        Expiry is a downgrade, not a refresh — the caller asked for cached
        state, and the truthful answer for a too-old check is "unknown".
        """
        with self._lock:
            snapshot = self._snapshot
        ttl = settings.freshness_cache_ttl_seconds
        if snapshot.checked_at is None:
            return snapshot
        now = time.monotonic()
        if not snapshot.is_current(ttl_seconds=ttl, now=now):
            age = int(now - snapshot.checked_at)
            return replace(
                snapshot, state=FreshnessState.UNAVAILABLE,
                detail=(
                    f"freshness cache expired: last check was {age}s ago "
                    f"(TTL {ttl}s)"
                ),
                # Keep nothing date-wise forward: the newest date itself was
                # fine but its freshness verdict is no longer provable.
                newest_market_date=None, age_days=None,
            )
        return snapshot

    async def refresh(
        self, session_factory: Callable[[], Any], *, today: date | None = None
    ) -> FreshnessSnapshot:
        """Compute from the database and store the result (success or failure).

        This is the controlled update point used by startup and scheduler
        lifecycle code. A raise inside compute is already an UNAVAILABLE
        snapshot, which by design REPLACES any previous FRESH state — an
        unreachable database makes the old verdict unverifiable.

        The ordering timestamp is captured BEFORE the session is opened, so
        even a hung or instantly-failing session start orders correctly
        against concurrent computations.
        """
        t_start = time.monotonic()
        try:
            async with session_factory() as db:
                snapshot = await compute_freshness(db, today=today,
                                                   started_at=t_start)
        except Exception as exc:  # noqa: BLE001 — session creation itself failed
            snapshot = FreshnessSnapshot(
                state=FreshnessState.UNAVAILABLE,
                detail=(
                    f"could not open a session to check freshness: "
                    f"{redact_secrets(str(exc))[:300]}"
                ),
                db_reachable=False,
                checked_at=t_start,
                checked_at_wall=datetime.now(timezone.utc),
            )
        return self.set(snapshot)


# Process-wide singleton: the startup warm-up, every scheduler read, and the
# health endpoint all go through this one object. Test code that needs an
# isolated cache should instantiate its own FreshnessCache.
FRESHNESS = FreshnessCache()

"""
backend/services/data_refresh.py — Scheduled AGMARKNET ingest pipeline

Why this exists
---------------
`price_service` refuses to forecast from a price older than
`settings.price_max_age_days` (3 days by default). That gate is only useful if
something keeps the feed current — otherwise the whole system degrades into
"stale_data" and looks broken to a farmer who asked a perfectly reasonable
question.

Design commitments
------------------
1. Incremental, never destructive. We insert rows that do not exist yet and
   leave history untouched. The unique constraint
   (commodity, market, arrival_date) makes the write idempotent, so a retried
   run cannot double-count a mandi day.
2. Validate before trusting. A row only lands if its date parses, is neither in
   the future nor absurdly old, and its min <= modal <= max with positive
   prices. Rejections are counted and reported, never silently dropped.
3. Three outcomes are recorded, not one. `success`, `no_new_data` and `failed`
   are distinct because they demand different operator actions. Collapsing them
   would make a dead pipeline indistinguishable from a closed mandi.
4. One runner at a time. A PostgreSQL session-level advisory lock serialises
   refreshes across every Uvicorn worker; a second contender skips its turn
   rather than queueing a duplicate fetch.
5. The fetcher is injectable. `run_refresh(..., fetcher=...)` lets the tests
   cover the whole pipeline without a socket, and lets the live run be proved
   against the real API separately.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence

import requests
from sqlalchemy import func, literal, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import redact_secrets, settings
from backend.core.models import DataRefreshRun, MandiPrice

logger = logging.getLogger("kisanmitra.data_refresh")

# Advisory lock key — arbitrary but fixed. Any two callers using it serialise.
REFRESH_LOCK_KEY = 771_102_451

# The bot's crop vocabulary -> the exact `Commodity` string AGMARKNET publishes.
# Mismatches here mean a crop silently stops refreshing, so the reverse map
# below rewrites whatever the API returns back into our canonical spelling.
CROP_API_NAMES: dict[str, str] = {
    "Tomato":    "Tomato",
    "Potato":    "Potato",
    "Onion":     "Onion",
    "Maize":     "Maize",
    "Brinjal":   "Brinjal",
    "Ragi":      "Ragi (Finger Millet)",
    "Capsicum":  "Capsicum",
    "Cabbage":   "Cabbage",
    "Groundnut": "Groundnut",
    "Marigold":  "Hybrid Marigold",
}
_API_NAME_TO_CROP: dict[str, str] = {v.lower(): k for k, v in CROP_API_NAMES.items()}

# Rejection reasons (also the vocabulary for monitoring dashboards).
REJECT_BAD_DATE   = "unparseable_arrival_date"
REJECT_FUTURE     = "arrival_date_in_future"
REJECT_TOO_OLD    = "arrival_date_before_window"
REJECT_MISSING    = "missing_required_field"
REJECT_BAD_PRICE  = "non_positive_price"
REJECT_BAD_ORDER  = "min_price_above_modal"
REJECT_OTHER_MARKET = "state_mismatch"

_WINDOW_START_KEY = "_window_start"


class RefreshFetchError(RuntimeError):
    """Upstream could not be read (auth, HTTP, timeout, malformed payload).

    Any message built here goes through `config.redact_secrets` first: requests
    embeds the full URL in its exceptions and the data.gov.in key is a URL
    parameter, so an unredacted failure would put a live credential into the
    application log and into data_refresh_runs.error — which
    `/internal/data/status` returns to any holder of an admin token.
    """


def _day(value: Any) -> date:
    """Normalise a date/datetime/str to a plain date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def parse_arrival_date(raw: Any) -> date | None:
    """
    AGMARKNET publishes `dd/mm/yyyy`; our own CSV exports and the cleaning
    scripts emit ISO. Accept both rather than losing a day of real data to a
    format assumption.
    """
    if raw in (None, ""):
        return None
    if isinstance(raw, (datetime, date)):
        return _day(raw)
    text_raw = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text_raw, fmt).date()
        except ValueError:
            continue
    try:
        # Timestamps with an offset ("2026-08-25T00:00:00+05:30") are what our own
        # TIMESTAMPTZ column hands back, so the parser must accept them too.
        return datetime.fromisoformat(text_raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    try:
        f = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # guard NaN


def normalize_record(raw: dict) -> dict | None:
    """Map one AGMARKNET record onto our MandiPrice columns, or None if unusable."""
    get = lambda *keys: next((raw[k] for k in keys if raw.get(k) not in (None, "")), None)

    api_commodity = get("Commodity", "commodity")
    if api_commodity is None:
        return None
    api_commodity = str(api_commodity).strip()
    crop = _API_NAME_TO_CROP.get(api_commodity.lower(), api_commodity.title())

    market   = (get("Market", "market") or "").strip()
    district = (get("District", "district") or "").strip()
    state    = (get("State", "state") or settings.refresh_state).strip()
    variety  = get("Variety", "variety")

    modal = _num(get("Modal_Price", "modal_price", "ModalPrice"))
    min_p = _num(get("Min_Price", "min_price", "MinPrice"))
    max_p = _num(get("Max_Price", "max_price", "MaxPrice"))
    arrivals = _num(get("Arrival_Date_Stock", "Total_Arrival", "arrivals_tonnes"))

    return {
        "state": state,
        "district": district,
        "market": market,
        "commodity": crop,
        "variety": (str(variety).strip() if variety else None),
        "arrival_date": parse_arrival_date(get("Arrival_Date", "arrival_date")),
        "min_price": min_p,
        "max_price": max_p,
        "modal_price": modal,
        "arrivals_tonnes": arrivals,
    }


def validate_record(rec: dict, *, window_start: date, today: date) -> str | None:
    """Return a rejection reason, or None when the record is fit to store."""
    if not all([rec.get("commodity"), rec.get("market"), rec.get("district")]):
        return REJECT_MISSING
    if str(rec.get("state", "")).strip().lower() != settings.refresh_state.lower():
        return REJECT_OTHER_MARKET
    d = rec.get("arrival_date")
    if d is None:
        return REJECT_BAD_DATE
    if d > today:
        return REJECT_FUTURE
    if d < window_start:
        return REJECT_TOO_OLD
    modal = rec.get("modal_price")
    if modal is None or modal <= 0:
        return REJECT_BAD_PRICE
    lo, hi = rec.get("min_price"), rec.get("max_price")
    if (lo is not None and hi is not None) and (lo > modal or hi < modal):
        return REJECT_BAD_ORDER
    return None


def validate_records(
    records: Iterable[dict], *, window_start: date, today: date
) -> tuple[list[dict], dict[str, int]]:
    """Split into (acceptable, rejection counts by reason)."""
    valid: list[dict] = []
    rejected: dict[str, int] = {}
    for rec in records:
        reason = validate_record(rec, window_start=window_start, today=today)
        if reason is None:
            valid.append(rec)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
    return valid, rejected


def dedupe_records(records: Sequence[dict]) -> tuple[list[dict], int]:
    """
    Collapse repeated (commodity, market, arrival_date) triples inside one batch.
    The last occurrence wins — AGMARKNET re-publishes corrected figures for a day
    and the later row is the revision. Returns (unique_records, dropped_count).
    """
    keyed: dict[tuple, dict] = {}
    for rec in records:
        key = (
            str(rec["commodity"]).lower(),
            str(rec["market"]).lower(),
            rec["arrival_date"],
        )
        keyed[key] = rec
    unique = list(keyed.values())
    return unique, len(records) - len(unique)


def _as_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ── Upstream fetch ─────────────────────────────────────────

def fetch_window(
    crop: str,
    window_start: date,
    window_end: date,
    *,
    api_key: str,
    resource_id: str | None = None,
    limit: int = 1000,
    max_pages: int = 20,
    timeout: int = 30,
    session: requests.Session | None = None,
    max_attempts: int = 3,
    retry_backoff: float = 2.0,
    pace_seconds: float = 0.4,
) -> list[dict]:
    """
    Pull one crop's records for [window_start, window_end] from data.gov.in.

    Queries ONE ARRIVAL DATE AT A TIME with an equality filter. Verified live
    2026-10-27 against resource 35985678-…: this resource silently returns
    ZERO records for every date-RANGE spelling tried (`a:b` colon, `filters
    [..][op]=between`, `field[..][condition][op]=between`, yyyy-mm-dd), while
    `filters[Arrival_Date]=26/10/2026` correctly returns that day's rows — and
    the resource does carry same-week data. A range-based refresh therefore
    looked "upstream had nothing new" forever. Equality per day costs a few
    more requests (window × pages) but is the only syntax the server honors.

    Per-day requests need server manners: data.gov.in throttles roughly 3
    req/s per key and, when pushed faster than that, does not answer with 429
    — it STALLS the connection mid-body (verified live 2026-10-27: single
    spaced requests answer in ~1s, an unpaced 11-request burst died with a
    read timeout partway through). `pace_seconds` self-times requests and
    `max_attempts`/`retry_backoff` absorb intermittent NIC stalls; a truly
    exhausted retry still raises so the run is marked `failed`, never
    silently short.

    Raises RefreshFetchError on any upstream problem — the caller turns
    that into a `failed` run rather than a `no_new_data` one.
    """
    if not api_key:
        raise RefreshFetchError("DATA_GOV_API_KEY is not configured")

    resource = resource_id or settings.agmarknet_resource_id
    api_crop = CROP_API_NAMES.get(crop, crop)
    http = session or requests.Session()
    # NIC's WAF silently BLACKHOLES the `python-requests/x.y` User-Agent
    # against api.data.gov.in — connections neither reject nor answer, they
    # hang until read timeout (verified 2026-10-27: that UA times out at 30s,
    # a browser UA answers in 0.4s). NOTE: requests.Session() ships with the
    # python-requests UA ALREADY in .headers, so headers.setdefault() is a
    # NO-OP here — it must be a direct assignment. The legacy
    # scripts/01_download_data.py carried this workaround; it was lost in
    # the service rewrite and every refresh since failed as "network error".
    http.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    own_session = session is None

    records: list[dict] = []
    url = f"https://api.data.gov.in/resource/{resource}"

    def _fetch_page(params: dict) -> list[dict]:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = http.get(url, params=params, timeout=timeout)
            except requests.RequestException as e:
                if attempt < max_attempts:
                    time.sleep(retry_backoff * attempt)
                    continue
                raise RefreshFetchError(
                    f"network error fetching {crop} after {max_attempts} "
                    f"attempts: {redact_secrets(str(e))}"
                ) from e

            if resp.status_code == 429:
                if attempt < max_attempts:
                    time.sleep(retry_backoff * attempt * 2)
                    continue
                raise RefreshFetchError(
                    f"rate limited (HTTP 429) while fetching {crop}"
                )
            if resp.status_code != 200:
                raise RefreshFetchError(
                    f"HTTP {resp.status_code} while fetching {crop}: "
                    f"{redact_secrets(resp.text[:200])}"
                )
            try:
                payload = resp.json()
            except ValueError as e:
                raise RefreshFetchError(f"unparseable JSON for {crop}") from e
            return payload.get("records") or []
        raise AssertionError("unreachable")  # pragma: no cover

    try:
        day = window_start
        first_request = True
        while day <= window_end:
            offset = 0
            while offset < limit * max_pages:
                if not first_request and pace_seconds > 0:
                    time.sleep(pace_seconds)
                first_request = False
                params = {
                    "api-key": api_key,
                    "format": "json",
                    "limit": limit,
                    "offset": offset,
                    "filters[State]": settings.refresh_state,
                    "filters[Commodity]": api_crop,
                    "filters[Arrival_Date]": f"{day:%d/%m/%Y}",
                }
                batch = _fetch_page(params)
                records.extend(batch)
                if len(batch) < limit:
                    break
                offset += limit
            day += timedelta(days=1)
    finally:
        if own_session:
            http.close()

    return records


# ── Database side ──────────────────────────────────────────

async def get_newest_date(db: AsyncSession) -> date | None:
    newest = (await db.execute(select(func.max(MandiPrice.arrival_date)))).scalar_one_or_none()
    return _day(newest) if newest is not None else None


async def existing_keys(db: AsyncSession, records: Sequence[dict], crop: str) -> set[tuple]:
    """Triples already stored in this window, so duplicates are counted for real."""
    if not records:
        return set()
    days = {r["arrival_date"] for r in records}
    rows = (await db.execute(
        select(MandiPrice.commodity, MandiPrice.market, MandiPrice.arrival_date)
        .where(MandiPrice.commodity == crop)
        .where(MandiPrice.arrival_date >= _as_utc(min(days)))
        .where(MandiPrice.arrival_date <= _as_utc(max(days)) + timedelta(days=1))
    )).all()
    return {(str(c).lower(), str(m).lower(), _day(d)) for c, m, d in rows}


async def upsert_records(db: AsyncSession, records: Sequence[dict]) -> int:
    """
    Insert rows, ignoring conflicts, and return how many were ACTUALLY written.

    The count comes from RETURNING rather than `rowcount`: psycopg3 reports -1
    for a multi-row INSERT ... ON CONFLICT DO NOTHING, and a -1 would make an
    idempotent re-run look like a successful one that landed rows.
    """
    if not records:
        return 0
    inserted = 0
    chunk = 500
    for i in range(0, len(records), chunk):
        stmt = pg_insert(MandiPrice).values([
            {**r, "arrival_date": _as_utc(r["arrival_date"])} for r in records[i:i + chunk]
        ]).on_conflict_do_nothing(
            index_elements=["commodity", "market", "arrival_date"]
        ).returning(literal(1))
        result = await db.execute(stmt)
        inserted += len(result.fetchall())
    await db.commit()
    return inserted


async def get_row_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(MandiPrice))).scalar() or 0


# ── Refresh orchestration ──────────────────────────────────

Fetcher = Callable[[str, date, date], list[dict]]


async def run_refresh(
    db: AsyncSession,
    *,
    trigger: str = "manual",
    fetcher: Fetcher | None = None,
    crops: Sequence[str] | None = None,
    api_key: str | None = None,
    today: date | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    """
    Fetch, validate, dedupe and store the recent AGMARKNET window.

    Exactly one DataRefreshRun row is written per call — including when the
    refresh fails — because an operator debugging a stall needs to see the
    attempt, its error, and when it happened.
    """
    today = today or datetime.now(timezone.utc).date()
    lookback = lookback_days if lookback_days is not None else settings.refresh_lookback_days
    window_start = today - timedelta(days=lookback)
    crops = list(crops) if crops else list(CROP_API_NAMES)
    key = api_key if api_key is not None else settings.data_gov_api_key

    started = datetime.now(timezone.utc)
    prev_newest = await get_newest_date(db)

    summary: dict[str, Any] = {
        "trigger": trigger,
        "window_start": window_start.isoformat(),
        "window_end": today.isoformat(),
        "crops": crops,
        "rejection_reasons": {},
        "per_crop": {},
    }

    fetcher = fetcher or (
        lambda crop, ws, we: fetch_window(crop, ws, we, api_key=key)
    )

    total_fetched = total_valid = total_dup = total_inserted = 0
    rejected_tally: dict[str, int] = {}
    status, error_text = "success", None
    newest_seen: date | None = None

    try:
        for crop in crops:
            # Blocking HTTP in a worker thread: this runs inside the API's loop.
            raw = await asyncio.to_thread(fetcher, crop, window_start, today)
            records = [n for n in (normalize_record(r) for r in raw) if n]
            valid, rejected = validate_records(
                records, window_start=window_start, today=today
            )
            unique, dupes = dedupe_records(valid)

            already = await existing_keys(db, unique, crop)
            fresh = [
                r for r in unique
                if (str(r["commodity"]).lower(), str(r["market"]).lower(), r["arrival_date"])
                not in already
            ]
            inserted = await upsert_records(db, fresh)

            total_fetched += len(raw)
            total_valid += len(valid)
            total_dup += dupes + len(already)
            total_inserted += inserted
            for reason, count in rejected.items():
                rejected_tally[reason] = rejected_tally.get(reason, 0) + count
            if unique:
                seen = max(r["arrival_date"] for r in unique)
                newest_seen = max(newest_seen, seen) if newest_seen else seen
            summary["per_crop"][crop] = {
                "fetched": len(raw), "validated": len(valid),
                "new": inserted, "already_present": len(unique) - len(fresh),
            }

        summary["rejection_reasons"] = rejected_tally
        post_newest = await get_newest_date(db)
        if total_inserted == 0:
            # Nothing new landed. Was that the upstream being quiet, or us
            # failing to read it? A window with zero acceptable records and no
            # error means the source simply has not published newer data.
            status = "no_new_data"
        else:
            summary["newest_date_after"] = post_newest.isoformat() if post_newest else None

    except RefreshFetchError as e:
        status, error_text = "failed", redact_secrets(str(e))
        await db.rollback()
    except Exception as e:  # noqa: BLE001 — a refresh must never crash a worker
        status, error_text = "failed", redact_secrets(f"{type(e).__name__}: {e}")
        logger.exception("AGMARKNET refresh aborted")
        await db.rollback()

    finished = datetime.now(timezone.utc)
    summary.update({
        "status": status,
        "rows_fetched": total_fetched,
        "rows_validated": total_valid,
        "rows_duplicate": total_dup,
        "rows_inserted": total_inserted,
        "rows_rejected": sum(rejected_tally.values()),
        "prev_newest_date": prev_newest.isoformat() if prev_newest else None,
        "upstream_newest_date": newest_seen.isoformat() if newest_seen else None,
        "error": error_text,
        "duration_seconds": round((finished - started).total_seconds(), 2),
    })

    run = DataRefreshRun(
        started_at=started,
        finished_at=finished,
        status=status,
        trigger=trigger,
        rows_fetched=total_fetched,
        rows_validated=total_valid,
        rows_rejected=summary["rows_rejected"],
        rows_duplicate=total_dup,
        rows_inserted=total_inserted,
        prev_newest_date=_as_utc(prev_newest) if prev_newest else None,
        new_newest_date=_as_utc(newest_seen) if newest_seen else (
            _as_utc(prev_newest) if prev_newest else None
        ),
        error=error_text,
        details=summary,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    logger.info(
        "refresh %s status=%s fetched=%s inserted=%s dup=%s rejected=%s error=%s",
        run.id, status, total_fetched, total_inserted, total_dup,
        summary["rows_rejected"], error_text,
    )
    summary["run_id"] = run.id
    return summary


async def data_freshness(db: AsyncSession, *, today: date | None = None) -> dict[str, Any]:
    """
    Current feed health: newest market date, its age, and the last refresh
    attempt. Consumed by `/system/data/status` and by the answer formatter, so
    a farmer is told the truth about *why* no forecast exists.
    """
    today = today or datetime.now(timezone.utc).date()
    newest = await get_newest_date(db)
    age_days = (today - newest).days if newest else None

    last = (await db.execute(
        select(DataRefreshRun)
        .order_by(DataRefreshRun.started_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    return {
        "rows": await get_row_count(db),
        "newest_market_date": newest.isoformat() if newest else None,
        "age_days": age_days,
        "max_age_days": settings.price_max_age_days,
        "forecastable": bool(age_days is not None and age_days <= settings.price_max_age_days),
        "last_refresh": None if last is None else {
            "id": last.id,
            "status": last.status,
            "trigger": last.trigger,
            "started_at": last.started_at.isoformat() if last.started_at else None,
            "finished_at": last.finished_at.isoformat() if last.finished_at else None,
            "rows_inserted": last.rows_inserted,
            "rows_rejected": last.rows_rejected,
            # Same reason as the router: a row stored before redaction existed
            # still contains the raw request URL.
            "error": redact_secrets(last.error),
        },
    }


# ── Single-runner lock ─────────────────────────────────────

class RefreshAlreadyRunning(Exception):
    """Another worker holds the advisory lock."""


class refresh_lock:
    """
    Session-level advisory lock held on a dedicated connection.

    Uvicorn runs multiple workers and a systemd timer may fire alongside them;
    process-local flags would not see each other, so the mutex lives in
    PostgreSQL. A holder that dies releases the lock automatically with its
    connection — no stale lock files to clean up.
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        self._conn = None

    async def __aenter__(self):
        self._conn = await self.engine.connect()
        got = (await self._conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": REFRESH_LOCK_KEY}
        )).scalar()
        if not got:
            await self._conn.close()
            self._conn = None
            raise RefreshAlreadyRunning("another refresh holds the lock")
        return self

    async def __aexit__(self, *exc) -> None:
        if self._conn is not None:
            await self._conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": REFRESH_LOCK_KEY}
            )
            await self._conn.close()
            self._conn = None

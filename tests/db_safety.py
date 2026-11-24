"""
tests/db_safety.py — connection-level test-database safety guard (B2 hardening).

The previous guard keyed everything off the `integration_db` pytest marker, so a
new DB-writing test that simply forgot `@requires_db` could still connect to and
mutate a real database. This module makes protection independent of what test
authors remember, through TWO independent layers:

  1. A pure CONFIG policy — `disposable_db_status()` — that decides whether this
     process is authorized to talk to a disposable test database. It reads only
     configuration (env + Settings); it NEVER opens a connection, so importing
     the suite or running `--collect-only` or a mock-only test contacts no
     database. Authorization requires ALL of:
        * `KM_TEST_DB_APPROVED` truthy        (explicit operator opt-in), and
        * `APP_ENV == test`, and
        * `KM_TEST_DB_NAME` set, and `DB_NAME == KM_TEST_DB_NAME` exactly
          (a strict allowlist, not a `"test" in name` substring heuristic), and
        * `DB_NAME` not a reserved real-database name, and
        * `DB_HOST` is loopback or listed in `KM_TEST_DB_HOSTS` (a remote or
          production host is never trusted merely because `APP_ENV=test`).

  2. A SQLAlchemy connection guard — `install_engine_guard()` — wrapped around
     `create_async_engine`/`create_engine`. PostgreSQL engines get a
     `"do_connect"` PRE-connect listener that raises `DisallowedDatabaseAccess`
     BEFORE the DBAPI driver opens a socket to a non-approved target — regardless
     of markers. Only the approved disposable PostgreSQL database and local /
     in-memory SQLite may be used: any other network dialect (MySQL, Oracle,
     MSSQL, …), an unknown scheme, or an unparseable URL is refused BEFORE the
     engine is built, and if the pre-connect listener cannot be attached the
     engine is refused rather than handed back unguarded. This is the backstop
     that makes an unmarked rogue test fail closed (and never even reach the
     network) instead of writing. Factory wrapping is reinforced by a CLASS-WIDE
     `"do_connect"` listener on `Engine`, which fires for every engine instance
     regardless of how it was created — so a factory reference captured before
     install, or an import alias we did not think to rebind, still cannot open a
     socket to an unapproved target.

Credentials are never embedded in the raised reason or any log line: targets are
described as `host:port/database` parsed from the URL, never the raw DSN.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, event, make_url
from sqlalchemy.ext.asyncio import create_async_engine

# Names that always denote a real store. Never an acceptable test target,
# whatever else the environment says.
RESERVED_DB_NAMES = frozenset(
    {"kisanmitra", "neondb", "postgres", "template0", "template1"}
)
# Hosts that are inherently a local disposable sandbox. 0.0.0.0 is deliberately
# EXCLUDED: it is the wildcard "bind all interfaces" address, not a loopback
# address, so it must never be treated as implying "local only". A remote host
# is allowed only when the operator adds it to KM_TEST_DB_HOSTS explicitly.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TRUTHY = {"1", "true", "yes", "on"}


class DisallowedDatabaseAccess(RuntimeError):
    """Raised in place of opening a connection to a non-approved database."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def _approved_hosts() -> frozenset[str]:
    extra = {h.strip() for h in os.environ.get("KM_TEST_DB_HOSTS", "").split(",") if h.strip()}
    return frozenset(LOOPBACK_HOSTS | extra)


def classify_target(url: object) -> dict:
    """Describe a connection target from its URL, password-free.

    Returns at least {kind, safe_repr}. `safe_repr` never contains a username or
    password, so it is safe to surface in an assertion or a CI log.
    """
    try:
        u = make_url(str(url))
    except Exception:  # noqa: BLE001 - unparseable is reported, never a crash path
        return {"kind": "unknown", "safe_repr": "<unparseable-url>"}
    driver = (u.drivername or "").split("+")[0].lower()
    if driver in ("", "sqlite"):
        return {"kind": "sqlite", "safe_repr": "sqlite"}
    if driver not in ("postgresql", "postgres"):
        return {"kind": driver or "other", "safe_repr": f"{driver}-url"}
    return {
        "kind": "postgresql",
        "host": u.host,
        "port": u.port,
        "database": u.database,
        "safe_repr": f"{u.host}:{u.port}/{u.database}",
    }


def disposable_db_status() -> tuple[bool, str]:
    """Is a disposable test database explicitly authorized RIGHT NOW?

    Config-only: no network, no probe. The reason is safe to log (no secrets).
    """
    if not _truthy(os.environ.get("KM_TEST_DB_APPROVED")):
        return False, "KM_TEST_DB_APPROVED is not set (no explicit disposable-test-DB opt-in)"
    if (os.environ.get("APP_ENV") or "").strip().lower() != "test":
        return False, f"APP_ENV is {os.environ.get('APP_ENV')!r}, not 'test'"
    approved_name = (os.environ.get("KM_TEST_DB_NAME") or "").strip()
    if not approved_name:
        return False, "KM_TEST_DB_NAME must name the exact disposable test database"

    from backend.core.config import settings  # local import: keeps module import cheap

    name = (settings.db_name or "").strip()
    if name != approved_name:
        return False, f"DB_NAME {name!r} != required KM_TEST_DB_NAME {approved_name!r}"
    if name in RESERVED_DB_NAMES:
        return False, f"{name!r} is a reserved real-database name"
    host = (settings.db_host or "").strip()
    if host not in _approved_hosts():
        return False, f"host {host!r} is neither loopback nor in KM_TEST_DB_HOSTS"
    return True, f"{name}@{host}:{settings.db_port}"


def approved_coordinates() -> tuple | None:
    """The (host, port, database) an engine must target, or None if unauthorized."""
    ok, _ = disposable_db_status()
    if not ok:
        return None
    from backend.core.config import settings

    return ((settings.db_host or "").strip(), int(settings.db_port), (settings.db_name or "").strip())


# Local, non-network DIALECTS that are safe to allow WITHOUT a disposable-DB
# authorization. This is matched against the normalized dialect (the portion of
# the SQLAlchemy drivername BEFORE any `+driver`, e.g. `sqlite+aiosqlite` and
# `sqlite+pysqlite` both reduce to `sqlite` in classify_target), so async/file
# SQLite variants are treated as local — not as network databases. Anything that
# can talk to a network-backed store (PostgreSQL, MySQL, Oracle, MSSQL, unknown
# schemes) is either guarded by the full policy or rejected outright.
LOCAL_SQLITE_DIALECTS = frozenset({"sqlite"})


def _dialect_decision(url: object) -> tuple[str, dict]:
    """Classify a target into an attach-time action.

    Returns ``(action, cls)`` where ``action`` is one of:
      * ``"guard"``       — PostgreSQL: attach the pre-connect authorization listener.
      * ``"allow-local"`` — local / in-memory SQLite: no network, nothing to guard.
      * ``"reject"``      — any other, unknown, or unparseable dialect. Fails
        closed: the engine is refused rather than silently allowed through.
    """
    cls = classify_target(url)
    kind = cls["kind"]
    if kind == "postgresql":
        return "guard", cls
    if kind in LOCAL_SQLITE_DIALECTS:
        return "allow-local", cls
    return "reject", cls


def _reject_reason(cls: dict) -> str:
    return (
        f"Refusing {cls['kind']!r} database target ({cls['safe_repr']}). Test "
        "engines may only target the approved disposable PostgreSQL database or "
        "local/in-memory SQLite; every other, unknown, or unparseable dialect "
        "fails closed."
    )


def _precheck(url: object) -> None:
    """Reject a disallowed dialect BEFORE any engine (or connection) is built."""
    action, cls = _dialect_decision(url)
    if action == "reject":
        raise DisallowedDatabaseAccess(_reject_reason(cls))


def _coords_from_connect_args(args, kwargs):
    """Pull (host, port, database) out of a `do_connect` call, driver-agnostically.

    psycopg/psycopg2 hand the connect-kwargs dict (host, port, dbname|database) to
    `do_connect`. Scanning every dict in the positional args plus the keyword args
    reads the target the driver is ABOUT to dial from the driver's own parameters —
    the most ground-truth view available, independent of how the engine was built.
    """
    params: dict = {}
    for a in args[1:]:
        if isinstance(a, dict):
            params.update(a)
    if isinstance(kwargs, dict):
        params.update(kwargs)
    return (
        params.get("host"),
        params.get("port"),
        params.get("dbname") or params.get("database"),
    )


def _enforce_postgres(host, port, database, safe_repr: str) -> None:
    """The single PostgreSQL authorization decision, shared by both guards.

    Raised from a `do_connect` listener, so it aborts BEFORE the DBAPI socket.
    """
    ok, why = disposable_db_status()
    if not ok:
        raise DisallowedDatabaseAccess(
            f"Refusing PostgreSQL connection to {safe_repr}: {why}. "
            "DB-backed tests require an explicit disposable test database "
            "(KM_TEST_DB_APPROVED=1, APP_ENV=test, KM_TEST_DB_NAME=<name>, "
            "loopback or KM_TEST_DB_HOSTS host)."
        )
    approved = approved_coordinates()
    try:
        port = int(port) if port is not None else port
    except (TypeError, ValueError):
        pass
    if approved is None or (host, port, database) != approved:
        raise DisallowedDatabaseAccess(
            f"Engine targets {safe_repr} which is not the approved disposable "
            f"test database {approved[2]!r}@{approved[0]}:{approved[1]}."
        )


def _pg_connect_guard(cls: dict):
    """Per-engine `"do_connect"` listener, using the URL captured at attach time.

    `do_connect` is a PRE-connect event: it fires before the DBAPI driver opens a
    socket, so raising here means no TCP connection is ever attempted to an
    unapproved database. The listener ignores the dialect-specific positional
    args (they vary across drivers) and validates the engine's OWN url, captured
    when the guard was attached. Returning None lets the default connect proceed.
    """

    def _guard(*args, **kwargs):  # noqa: ANN002,ANN003 - dialect signature varies
        _enforce_postgres(
            cls.get("host"), cls.get("port"), cls.get("database"), cls["safe_repr"]
        )
        return None  # authorized + exact target: allow the driver to connect

    return _guard


def attach_existing(engine) -> None:  # noqa: ANN001
    """Guard an engine created before install_engine_guard() ran."""
    _attach(engine, getattr(engine, "url", None))


def _attach(engine, url) -> None:  # noqa: ANN001
    sync_engine = getattr(engine, "sync_engine", engine)
    if getattr(sync_engine, "_km_dbguard_attached", False):
        return
    target = url if url is not None else getattr(engine, "url", "")
    action, cls = _dialect_decision(target)
    if action == "reject":
        # Fail closed: never hand back an engine for a disallowed dialect.
        raise DisallowedDatabaseAccess(_reject_reason(cls))
    if action == "allow-local":
        return  # local SQLite: no network, nothing to enforce at connect time
    # PostgreSQL: attach the pre-connect authorization listener. If registration
    # itself fails we must NOT return a usable unguarded engine — fail closed.
    guard = _pg_connect_guard(cls)
    try:
        event.listen(sync_engine, "do_connect", guard)
    except Exception as exc:  # noqa: BLE001 - re-raised as a refusal, never swallowed
        raise DisallowedDatabaseAccess(
            f"FATAL: could not attach the pre-connect DB guard to {cls['safe_repr']}; "
            "refusing to return an unguarded engine."
        ) from exc
    sync_engine._km_dbguard_attached = True


_INSTALLED = False
_CLASS_GUARD_INSTALLED = False


def _install_class_guard() -> None:
    """Register a class-wide `do_connect` guard on `Engine` — the bypass-proof layer.

    A listener attached to the `Engine` CLASS fires for EVERY engine instance at
    `do_connect` — before the DBAPI socket opens — no matter which factory or
    import path produced it. So even code that captured the ORIGINAL factory
    reference before `install_engine_guard()` ran (or imports it through a module
    attribute we did not think to rebind) still hits this check. It reads the real
    target from the driver's own connect parameters via `_coords_from_connect_args`.
    """
    global _CLASS_GUARD_INSTALLED
    if _CLASS_GUARD_INSTALLED:
        return
    from sqlalchemy import Engine

    def _class_guard(*args, **kwargs):  # noqa: ANN002,ANN003 - dialect signature varies
        dialect = args[0] if args else None
        name = (getattr(dialect, "name", "") or "").lower()
        if name in LOCAL_SQLITE_DIALECTS:
            return None  # local / in-memory SQLite: non-network, allowed
        if name not in ("postgresql", "postgres"):
            raise DisallowedDatabaseAccess(
                f"Refusing to connect a {name or 'unknown'} database dialect. "
                "Only the approved disposable PostgreSQL test database and local "
                "SQLite are permitted; every other/unknown dialect fails closed."
            )
        host, port, database = _coords_from_connect_args(args, kwargs)
        _enforce_postgres(host, port, database, f"{host}:{port}/{database}")
        return None  # authorized + exact target: let the driver connect

    event.listen(Engine, "do_connect", _class_guard)
    _CLASS_GUARD_INSTALLED = True


def install_engine_guard() -> None:
    """Guard every engine-creation path, twice over.

    Idempotent. Call at the top of conftest, before backend modules import the
    shared engine. Layer 1 rebinds the factory on EVERY module attribute a caller
    could import it through (rebinding one alias does not touch the others), so
    post-install `from sqlalchemy.engine import create_engine` also yields the
    guarded wrapper. Layer 2 installs the class-wide `Engine` listener, which is
    the authoritative backstop for any engine created through a path we cannot
    enumerate (a factory captured before install, a direct class build, …).
    """
    global _INSTALLED
    if _INSTALLED:
        return
    import sqlalchemy
    import sqlalchemy.engine as sa_engine
    import sqlalchemy.engine.create as sa_engine_create
    import sqlalchemy.ext.asyncio as sa_ext
    import sqlalchemy.ext.asyncio.engine as sa_ext_engine

    _orig_async = sa_ext_engine.create_async_engine
    _orig_sync = sa_engine.create_engine

    def _wrap_async(url, *args, **kwargs):  # noqa: ANN001
        _precheck(url)  # reject a disallowed dialect before any engine is built
        eng = _orig_async(url, *args, **kwargs)
        _attach(eng, url)
        return eng

    def _wrap_sync(url, *args, **kwargs):  # noqa: ANN001
        _precheck(url)
        eng = _orig_sync(url, *args, **kwargs)
        _attach(eng, url)
        return eng

    # Expose the marker + the raw original so regression tests can prove both that
    # every path is wrapped AND that even a pre-captured original is still blocked
    # by the class-level guard.
    _wrap_async._km_guarded = True
    _wrap_sync._km_guarded = True
    _wrap_async.__wrapped__ = _orig_async
    _wrap_sync.__wrapped__ = _orig_sync

    # Rebind EVERY importable attribute. They reference the same object today, but
    # attribute assignment is per-module, so each must be set explicitly.
    for _mod in (sqlalchemy, sa_engine, sa_engine_create):
        _mod.create_engine = _wrap_sync
    for _mod in (sa_ext, sa_ext_engine):
        _mod.create_async_engine = _wrap_async

    # The definitive, factory-independent backstop.
    _install_class_guard()
    _INSTALLED = True

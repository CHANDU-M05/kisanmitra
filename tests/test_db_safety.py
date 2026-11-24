"""
tests/test_db_safety.py — regression proof for the release-candidate DB guard.

These tests are MOCK-ONLY: they never open a socket to a database. They pin the
three behaviours the reviewer required before release:

  * protection is a CONNECTION-level property, not a marker the author must
    remember (an unapproved target is refused by the guard itself);
  * designation is a strict, explicit disposable allowlist (exact name + host +
    opt-in), not a "test" substring heuristic and never granted to a remote or
    reserved target merely because APP_ENV=test;
  * collection/mock-only runs contact no database (no import/collection probe).

The end-to-end "the disposable PostgreSQL integration tests still pass" case runs
only inside CI (its PostgreSQL service + the opt-in env) and is covered there;
the CI wiring that enforces it is asserted statically below.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

import db_safety
from db_safety import (
    DisallowedDatabaseAccess,
    approved_coordinates,
    classify_target,
    disposable_db_status,
)

from backend.core.config import settings

CI_FILE = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

REAL_URL = "postgresql+psycopg://km_user:SUPERSECRETPW@127.0.0.1:5432/kisanmitra"


# ── env/setting fixtures ──────────────────────────────────────────────────────
@pytest.fixture
def cleared(monkeypatch):
    """No disposable-test-DB authorization at all (the safe local default)."""
    for var in ("KM_TEST_DB_APPROVED", "KM_TEST_DB_NAME", "KM_TEST_DB_HOSTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    return monkeypatch


@pytest.fixture
def authorized_ci(cleared):
    """Exactly what the CI job sets: opt-in, test env, named disposable, loopback."""
    m = cleared
    m.setenv("KM_TEST_DB_APPROVED", "1")
    m.setenv("APP_ENV", "test")
    m.setenv("KM_TEST_DB_NAME", "kisanmitra_test")
    m.setattr(settings, "db_host", "localhost", raising=False)
    m.setattr(settings, "db_port", 5432, raising=False)
    m.setattr(settings, "db_name", "kisanmitra_test", raising=False)
    return m


def _fire(url):
    """Simulate engine creation + the DBAPI connect event for ``url``.

    Mirrors the real flow: a disallowed dialect is refused at creation
    (``_precheck``/``_dialect_decision``); a PostgreSQL engine then runs its
    pre-connect ``do_connect`` guard. Returns normally only when the target is
    permitted. No socket is ever opened here.

    The guard is invoked with the EXACT positional shape SQLAlchemy dispatches
    for a ``do_connect`` event — ``dialect, connection_record, cargs, cparams`` —
    with ``cparams`` carrying the psycopg-style connect coordinates. Using the
    real arity means a change to the callback's argument handling would surface
    here instead of the test quietly passing on ``(None, None)``.
    """
    action, cls = db_safety._dialect_decision(url)
    if action == "reject":
        raise DisallowedDatabaseAccess(db_safety._reject_reason(cls))
    if action == "allow-local":
        return
    dialect, connection_record, cargs, cparams = _do_connect_args(cls)
    db_safety._pg_connect_guard(cls)(dialect, connection_record, cargs, cparams)


def _do_connect_args(cls):
    """The four positional args SQLAlchemy hands a ``do_connect`` listener, in the
    psycopg shape verified against the real driver (host/port/dbname in cparams).
    """
    cparams = {
        "host": cls.get("host"),
        "port": cls.get("port"),
        "dbname": cls.get("database"),
    }
    return None, None, [], cparams


def test_guard_callback_accepts_the_real_do_connect_arity(cleared, authorized_ci):
    # Contract lock: the callback SQLAlchemy registers must be callable with the
    # exact (dialect, connection_record, cargs, cparams) it dispatches — no
    # TypeError on the authorized path, DisallowedDatabaseAccess on the refused
    # one. This pins _pg_connect_guard's signature to the documented event form.
    authorized = db_safety.classify_target(
        "postgresql+psycopg://u:p@localhost:5432/kisanmitra_test"
    )
    dialect, connection_record, cargs, cparams = _do_connect_args(authorized)
    assert (
        db_safety._pg_connect_guard(authorized)(
            dialect, connection_record, cargs, cparams
        )
        is None
    )

    unauthorized = db_safety.classify_target(REAL_URL)
    dialect, connection_record, cargs, cparams = _do_connect_args(unauthorized)
    with pytest.raises(DisallowedDatabaseAccess):
        db_safety._pg_connect_guard(unauthorized)(
            dialect, connection_record, cargs, cparams
        )


# ── 1. designation is explicit, not a substring ───────────────────────────────
def test_no_opt_in_is_never_authorized(cleared):
    ok, why = disposable_db_status()
    assert not ok
    assert "KM_TEST_DB_APPROVED" in why


def test_substring_test_is_not_trusted_without_exact_named_allowlist(cleared):
    # Everything says "test" but KM_TEST_DB_NAME does not match the target name.
    cleared.setenv("KM_TEST_DB_APPROVED", "1")
    cleared.setenv("APP_ENV", "test")
    cleared.setenv("KM_TEST_DB_NAME", "kisanmitra_test")
    cleared.setattr(settings, "db_host", "localhost", raising=False)
    cleared.setattr(settings, "db_name", "mytestingdb", raising=False)  # contains "test"
    ok, why = disposable_db_status()
    assert not ok and "!=" in why  # rejected because it is not the named db


def test_remote_host_rejected_even_with_test_env_and_test_name(cleared):
    # APP_ENV=test + a *_test name is NOT enough for a remote target.
    cleared.setenv("KM_TEST_DB_APPROVED", "1")
    cleared.setenv("APP_ENV", "test")
    cleared.setenv("KM_TEST_DB_NAME", "kisanmitra_test")
    cleared.setattr(settings, "db_name", "kisanmitra_test", raising=False)
    cleared.setattr(settings, "db_host", "prod-pg.example.com", raising=False)
    ok, why = disposable_db_status()
    assert not ok and "host" in why


def test_remote_host_allowed_only_when_explicitly_approved_infrastructure(cleared):
    cleared.setenv("KM_TEST_DB_APPROVED", "1")
    cleared.setenv("APP_ENV", "test")
    cleared.setenv("KM_TEST_DB_NAME", "kisanmitra_test")
    cleared.setenv("KM_TEST_DB_HOSTS", "ci-pg.internal")  # explicit allowlist
    cleared.setattr(settings, "db_name", "kisanmitra_test", raising=False)
    cleared.setattr(settings, "db_host", "ci-pg.internal", raising=False)
    assert disposable_db_status()[0] is True


def test_reserved_name_rejected_even_when_authorized_in_everything_else(cleared):
    cleared.setenv("KM_TEST_DB_APPROVED", "1")
    cleared.setenv("APP_ENV", "test")
    cleared.setenv("KM_TEST_DB_NAME", "kisanmitra")  # operator mistake
    cleared.setattr(settings, "db_host", "localhost", raising=False)
    cleared.setattr(settings, "db_name", "kisanmitra", raising=False)  # the real store
    ok, why = disposable_db_status()
    assert not ok and "reserved" in why


def test_wildcard_host_is_not_treated_as_loopback(cleared):
    # 0.0.0.0 is the bind-all-interfaces wildcard, NOT a loopback address; it must
    # never satisfy the "local disposable sandbox" host check merely by being in
    # the default set.
    assert "0.0.0.0" not in db_safety.LOOPBACK_HOSTS
    cleared.setenv("KM_TEST_DB_APPROVED", "1")
    cleared.setenv("APP_ENV", "test")
    cleared.setenv("KM_TEST_DB_NAME", "kisanmitra_test")
    cleared.setattr(settings, "db_name", "kisanmitra_test", raising=False)
    cleared.setattr(settings, "db_host", "0.0.0.0", raising=False)
    ok, why = disposable_db_status()
    assert not ok and "host" in why


# ── 2. the connection guard, independent of any marker ───────────────────────
def test_guard_refuses_unauthorized_connection(cleared):
    with pytest.raises(DisallowedDatabaseAccess):
        _fire(REAL_URL)


def test_guard_refuses_wrong_target_even_when_ci_is_authorized(authorized_ci):
    # CI is authorized for kisanmitra_test, but this engine points at the real
    # `kisanmitra` on the same host — the guard must still refuse it.
    with pytest.raises(DisallowedDatabaseAccess):
        _fire("postgresql+psycopg://km_user:pw@localhost:5432/kisanmitra")


def test_guard_allows_the_approved_disposable_target(authorized_ci):
    # Same host/port/name the policy authorized -> the guard does not raise.
    _fire("postgresql+psycopg://km_user:pw@localhost:5432/kisanmitra_test")


def test_guard_never_leaks_the_password(cleared):
    with pytest.raises(DisallowedDatabaseAccess) as exc:
        _fire(REAL_URL)
    assert "SUPERSECRETPW" not in str(exc.value)
    assert "km_user" not in str(exc.value)


@pytest.mark.parametrize("url", [
    "sqlite://",                       # bare in-memory
    "sqlite:///:memory:",              # explicit in-memory
    "sqlite:///test.db",              # on-disk, sync driver
    "sqlite+aiosqlite://",            # async driver variant — still local
    "sqlite+aiosqlite:///:memory:",   # async in-memory
    "sqlite+pysqlite:///test.db",     # explicit pysqlite driver — still local
])
def test_sqlite_dialect_and_driver_variants_are_allowed_local(cleared, url):
    # The allowlist keys off the normalized DIALECT, not the raw drivername, so
    # `sqlite+aiosqlite`/`sqlite+pysqlite` are treated as local (never rejected as
    # if they were network databases). classify_target strips `+driver` first.
    assert db_safety.classify_target(url)["kind"] == "sqlite"
    assert db_safety._dialect_decision(url)[0] == "allow-local"
    _fire(url)  # returns without raising


# ── 2b. fail-closed dialect handling (reviewer finding: non-pg bypass) ────────
@pytest.mark.parametrize("url", [
    "mysql+pymysql://u:p@db.internal:3306/app",        # network-backed, not our DB
    "mysql://db.internal:3306/app",
    "mssql+pyodbc://u:p@db.internal:1433/app",
    "oracle+cx_oracle://u:p@db.internal:1521/?sid=x",
    "mariadb+mariadbconnector://db.internal:3306/app",
])
def test_non_postgres_network_dialects_are_rejected(cleared, url):
    # Anything that is neither the guarded PostgreSQL store nor local SQLite must
    # be refused by default, not waved through because it is "not postgresql".
    assert db_safety._dialect_decision(url)[0] == "reject"
    with pytest.raises(DisallowedDatabaseAccess):
        _fire(url)


def test_unparseable_target_fails_closed(cleared):
    # An unparseable URL classifies as unknown and is REJECTED, never allowed.
    assert db_safety.classify_target("this is not a url")["kind"] == "unknown"
    assert db_safety._dialect_decision("this is not a url")[0] == "reject"
    with pytest.raises(DisallowedDatabaseAccess):
        _fire("this is not a url")


def test_guard_registration_failure_refuses_the_engine(cleared, monkeypatch):
    # Reviewer finding #1: if event.listen fails, _attach must NOT return a
    # usable unguarded engine — it must fail closed. We exercise _attach in
    # isolation (SQLAlchemy also uses event.listen internally when building a
    # real engine, so patching it globally would test the wrong failure).
    url = "postgresql+psycopg://u:p@127.0.0.1:5432/kisanmitra_test"

    class _FakeEngine:
        def __init__(self, u):
            self.url = u
            self.sync_engine = self

    def _boom(*a, **k):
        raise RuntimeError("simulated listener-registration failure")

    monkeypatch.setattr(db_safety.event, "listen", _boom)
    with pytest.raises(DisallowedDatabaseAccess) as exc:
        db_safety._attach(_FakeEngine(url), url)
    assert "could not attach" in str(exc.value)


def test_guard_blocks_before_any_socket_attempt(cleared, monkeypatch):
    """End-to-end: the do_connect guard must refuse BEFORE the driver opens a
    socket, so an unapproved (here, remote) target causes ZERO network attempts.

    This is the reviewer's core requirement: a reachable-looking unauthorized
    host is rejected during connection creation, not after a TCP handshake."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    attempts = []

    def _spy(self, addr, *a, **k):
        attempts.append(addr)
        raise AssertionError("a socket was attempted for an unauthorized target")

    monkeypatch.setattr(socket.socket, "connect", _spy)

    async def _try():
        eng = create_async_engine(
            "postgresql+psycopg://u:p@remote-db.example:5432/kisanmitra"
        )
        try:
            async with eng.connect() as c:
                await c.execute(text("SELECT 1"))
        finally:
            await eng.dispose()

    with pytest.raises(DisallowedDatabaseAccess):
        asyncio.run(_try())
    assert attempts == []  # no TCP/DNS connect was ever tried


def test_unreachable_does_not_fall_back_to_safe(cleared):
    # "not authorized" is decided by config and enforced by a hard raise; there
    # is no code path that treats an unreachable/unclear target as safe.
    ok, _ = disposable_db_status()
    assert ok is False
    assert approved_coordinates() is None
    with pytest.raises(DisallowedDatabaseAccess):
        _fire(REAL_URL)


# ── 2c. factory interception holds for EVERY importable path (reviewer concern) ─
@pytest.mark.parametrize("path", [
    "sqlalchemy.create_engine",
    "sqlalchemy.engine.create_engine",
    "sqlalchemy.engine.create.create_engine",
    "sqlalchemy.ext.asyncio.create_async_engine",
    "sqlalchemy.ext.asyncio.engine.create_async_engine",
])
def test_every_importable_factory_attribute_is_wrapped(path):
    # Rebinding one alias does not touch the others, so install_engine_guard must
    # set the wrapper on every module attribute a caller could import through.
    import importlib

    mod_name, attr = path.rsplit(".", 1)
    factory = getattr(importlib.import_module(mod_name), attr)
    assert getattr(factory, "_km_guarded", False) is True


def test_sync_engine_imported_via_secondary_alias_is_blocked(cleared, monkeypatch):
    # `from sqlalchemy.engine import create_engine` executed after install used to
    # be able to grab the ORIGINAL (conftest only rebound sqlalchemy.create_engine).
    # Now that alias is rebound too, and the class-wide guard backstops it anyway.
    import socket
    import sqlalchemy.engine as eng_pkg

    attempts = []

    def _spy(self, addr, *a, **k):
        attempts.append(addr)
        raise AssertionError("socket attempted for an unauthorized target")

    monkeypatch.setattr(socket.socket, "connect", _spy)
    eng = eng_pkg.create_engine(
        "postgresql+psycopg://u:p@unauth.example:5432/kisanmitra"
    )
    with pytest.raises(DisallowedDatabaseAccess):
        with eng.connect():
            pass
    assert attempts == []


def test_async_engine_imported_via_inner_module_is_blocked(cleared, monkeypatch):
    import asyncio
    import socket
    import sqlalchemy.ext.asyncio.engine as sa_ext_engine

    attempts = []

    def _spy(self, addr, *a, **k):
        attempts.append(addr)
        raise AssertionError("socket attempted for an unauthorized target")

    monkeypatch.setattr(socket.socket, "connect", _spy)

    async def _go():
        eng = sa_ext_engine.create_async_engine(
            "postgresql+psycopg://u:p@unauth.example:5432/kisanmitra"
        )
        try:
            async with eng.connect():
                pass
        finally:
            await eng.dispose()

    with pytest.raises(DisallowedDatabaseAccess):
        asyncio.run(_go())
    assert attempts == []


@pytest.mark.parametrize("driver", ["psycopg", "psycopg2"])
def test_class_guard_blocks_a_preinstalled_factory_reference(cleared, monkeypatch, driver):
    # The reviewer's hardest case: code that captured the ORIGINAL factory BEFORE
    # install_engine_guard() ran. Building an engine through that reference skips
    # _precheck and the per-engine listener entirely — yet the CLASS-WIDE do_connect
    # listener on Engine must still refuse, before any socket is opened. The
    # listener fires for an engine that already existed when it was registered
    # (verified: SQLAlchemy resolves class-level listeners at dispatch time), so
    # this is real event dispatch, not a helper call. Parametrized across the sync
    # PostgreSQL drivers so the connect-args shape is proven for each, not assumed.
    import socket
    import sqlalchemy

    attempts = []

    def _spy(self, addr, *a, **k):
        attempts.append(addr)
        raise AssertionError("socket attempted for an unauthorized target")

    monkeypatch.setattr(socket.socket, "connect", _spy)
    # The wrapper exposes the raw original it delegates to; grabbing it here is
    # exactly what a module that imported create_engine before install would hold.
    raw_create = sqlalchemy.create_engine.__wrapped__  # the true original factory
    eng = raw_create(f"postgresql+{driver}://u:p@unauth.example:5432/kisanmitra")
    with pytest.raises(DisallowedDatabaseAccess):
        with eng.connect():
            pass
    assert attempts == []


def test_class_guard_blocks_preinstalled_asyncpg_reference(cleared, monkeypatch):
    # asyncpg hands do_connect a connect-params dict keyed 'database' (not
    # 'dbname' like psycopg/psycopg2). The extractor must read it via the fallback
    # and still refuse an unauthorized target before the socket opens.
    import asyncio
    import socket
    import sqlalchemy.ext.asyncio as sa_ext

    attempts = []

    def _spy(self, addr, *a, **k):
        attempts.append(addr)
        raise AssertionError("socket attempted for an unauthorized target")

    monkeypatch.setattr(socket.socket, "connect", _spy)
    raw_async = sa_ext.create_async_engine.__wrapped__
    eng = raw_async("postgresql+asyncpg://u:p@unauth.example:5432/kisanmitra")

    async def _go():
        try:
            async with eng.connect():
                pass
        finally:
            await eng.dispose()

    with pytest.raises(DisallowedDatabaseAccess):
        asyncio.run(_go())
    assert attempts == []


def test_class_guard_fails_closed_when_coordinates_are_unreadable(authorized_ci):
    # Point 2 of the review gate: if a driver hands a shape from which host/port/
    # database cannot be read, the guard must NOT treat the blank target as safe.
    # Even with a disposable DB fully authorized, extracted (None, None, None)
    # can never equal the approved coordinates, so the connection is refused.
    with pytest.raises(DisallowedDatabaseAccess, match="not the approved"):
        db_safety._enforce_postgres(None, None, None, "<unreadable>")


def test_original_factory_captured_before_install_is_still_blocked():
    # The __wrapped__ tests above reach through the wrapper AFTER install, which is
    # not literally a reference grabbed BEFORE install_engine_guard() ran. This runs
    # a fresh child process that captures sqlalchemy.create_engine first, installs
    # the guard second, then builds + connects through the pre-captured reference —
    # proving the class-wide Engine listener (not the factory wrapper) is what stops
    # a factory reference that predates installation. Unauthorized env => fail closed.
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    child = r"""
import os, socket, sys
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "tests"))
sys.path.insert(0, root)
for k in ("KM_TEST_DB_APPROVED", "KM_TEST_DB_NAME", "KM_TEST_DB_HOSTS"):
    os.environ.pop(k, None)
os.environ["APP_ENV"] = "development"

# 1. capture the ORIGINAL factory BEFORE the guard exists at all
import sqlalchemy
raw_before = sqlalchemy.create_engine

# 2. install the guard AFTER the reference was captured
import db_safety
db_safety.install_engine_guard()

# 3. the captured reference must be the pristine original, not the wrapper
assert getattr(raw_before, "_km_guarded", False) is False
assert raw_before is not sqlalchemy.create_engine

# 4. a socket spy proves the connect is refused before any TCP attempt
attempts = []
def _spy(self, addr, *a, **k):
    attempts.append(addr)
    raise AssertionError("socket attempted for an unauthorized target")
socket.socket.connect = _spy

eng = raw_before("postgresql+psycopg://u:p@unauth.example:5432/kisanmitra")
try:
    with eng.connect():
        raise SystemExit("FAIL: pre-install factory produced an unguarded engine")
except db_safety.DisallowedDatabaseAccess:
    pass
if attempts:
    raise SystemExit("FAIL: a socket was attempted before the guard refused")
print("PASS: pre-install-captured factory blocked with 0 sockets")
"""
    out = subprocess.run(
        [sys.executable, "-c", child, str(root)],
        cwd=root, capture_output=True, text=True,
    )
    # Two independent conditions, so a child that prints PASS and then fails on
    # the way out (interpreter shutdown, a post-print crash) cannot masquerade as
    # a success: clean exit first, then the sentinel.
    assert out.returncode == 0, (
        f"child exited {out.returncode}; stderr={out.stderr!r} stdout={out.stdout!r}"
    )
    assert "PASS: pre-install-captured factory blocked with 0 sockets" in out.stdout, (
        f"stdout missing PASS sentinel; stderr={out.stderr!r} stdout={out.stdout!r}"
    )


# ── 3. no network at policy evaluation or collection ─────────────────────────
def test_policy_and_engine_creation_open_no_socket(cleared, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("test-db-safety contacted the network")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    from sqlalchemy.ext.asyncio import create_async_engine

    ok, _ = disposable_db_status()  # config only
    assert ok is False
    classify_target(REAL_URL)  # string parse only
    eng = create_async_engine(settings.database_url)  # lazy: connects on use
    assert eng.pool.checkedout() == 0
    import asyncio

    asyncio.run(eng.dispose())


# ── 4. CI enforces the exact integration inventory (manifest), not a weak min ─
MANIFEST = Path(__file__).resolve().parent / "integration_manifest.txt"


def _manifest_ids():
    return {
        ln.strip()
        for ln in MANIFEST.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }


def test_ci_sets_explicit_disposable_designation():
    text = CI_FILE.read_text()
    assert "KM_TEST_DB_APPROVED" in text
    assert "KM_TEST_DB_NAME" in text
    # CI enforces the manifest by exact-set comparison, not a min-of-N heuristic.
    assert "integration_manifest.txt" in text
    assert "diff -u" in text
    assert "no tests ran" in text
    assert "integration tests must execute" in text.lower()


def test_manifest_matches_collected_integration_inventory():
    # The manifest is the contract: the collected `-m integration_db` set must equal
    # it exactly. Renaming, deleting, or de-marking a DB test without editing the
    # manifest fails here (and in CI). Collection is probe-free, so this needs no DB.
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-m", "integration_db", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True,
    )
    collected = {
        ln.strip() for ln in out.stdout.splitlines()
        if ln.startswith("tests/") and "::" in ln
    }
    expected = _manifest_ids()
    assert expected, "manifest must declare at least one integration test"
    assert collected == expected, (
        "integration inventory drift — in manifest but not collected: "
        f"{sorted(expected - collected)}; collected but not in manifest: "
        f"{sorted(collected - expected)}"
    )

"""
scripts/tools/scrub_secret_exposure.py — find and remove leaked credentials at rest

A refresh failure used to write the data.gov.in request URL — key included — into
`data_refresh_runs.error` and into logs/kisanmitra.log (see
backend/services/data_refresh.redact_secrets). The code is fixed; this tool fixes
what a running system already stored.

It checks every configured credential against the application log files, the
refresh-run error/details columns, and local review artifacts (generated patches,
working checkpoints), and by default only REPORTS. Pass --apply to replace the
exact secret strings with [REDACTED]. Nothing else in the text is touched, no row
is deleted, and no secret value is ever printed.

Values that have already been rotated out of the environment are still caught:
`historical_compromised_values()` re-reads the revoked strings from Git history
and trusts one only when its SHA-256 digest is in the compromise list.

Usage:
    python scripts/tools/scrub_secret_exposure.py            # report
    python scripts/tools/scrub_secret_exposure.py --apply    # remediate
    python scripts/tools/scrub_secret_exposure.py --path some/file.diff
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from backend.core import config as config_module  # noqa: E402
from backend.core.config import secret_values  # noqa: E402
from backend.core.database import AsyncSessionLocal, engine  # noqa: E402
from sqlalchemy import text  # noqa: E402

# Anything that looks like a credential passed as a URL/query parameter, whatever
# its value: catches keys this deployment does not have loaded (a rotated value,
# a second tenant's key) that exact-string matching would miss.
PARAM_PATTERNS = (
    re.compile(r"((?:api[-_]?key|access[-_]?token|secret|password|token)=)(?!%24\[REDACTED\]|\[REDACTED\])[^&\s\"']+", re.IGNORECASE),
)

# Files whose historical versions published a credential, and the default local
# artifacts to sweep.
HISTORY_PROBE_PATHS = (
    "backend/core/config.py",
    "backend/core/security.py",
    "scripts/fetch_all_crops_full.py",
    "scripts/fetch_potato_full.py",
    "scripts/download_real_agmarknet_history.py",
)
ARTIFACT_GLOBS = ("artifacts/*.patch", "artifacts/*.diff", ".checkpoints/*.diff")
# Credential-shaped substrings inside a historical blob (quoted defaults, keys).
_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_\-]{8,80}")


def scrub_text(content: str, secrets: tuple[str, ...],
               allow_params: bool = True) -> tuple[str, int]:
    """
    Return (cleaned_text, replacement_count) for one body of text.

    allow_params=False replaces only the exact known credential values. Logs and
    database rows are runtime output, so sweeping every `...api_key=<value>` shape
    is safe and also catches a key this deployment never loaded. Patch and diff
    files are not: the generic pattern would rewrite placeholder lines such as
    `DATA_GOV_API_KEY=your-key` and source text like `token=`, silently corrupting
    a diff that is meant to apply cleanly. Artifacts therefore use exact matching
    and report anything that still looks like a credential parameter.
    """
    hits = sum(content.count(s) for s in secrets)
    cleaned = content
    for secret in secrets:
        if secret in cleaned:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    if not allow_params:
        residual = sum(len(p.findall(content)) for p in PARAM_PATTERNS)
        if residual:
            print(f"  note: {residual} credential-shaped parameter(s) left untouched "
                  "(only exact known values are replaced in diff/patch files)")
        return cleaned, hits
    for pattern in PARAM_PATTERNS:
        cleaned, n = pattern.subn(r"\1[REDACTED]", cleaned)
        hits += n
    return cleaned, hits


def find_log_files() -> list[Path]:
    """Current log plus any rotated backups (kisanmitra.log.1 … )."""
    log_dir = BASE_DIR / "logs"
    if not log_dir.is_dir():
        return []
    return sorted([p for p in log_dir.glob("kisanmitra.log*") if p.is_file()])


def find_artifact_files(extra: list[str] | None = None) -> list[Path]:
    """Generated patches and checkpoints that reproduce the working tree verbatim."""
    found = {p for pattern in ARTIFACT_GLOBS for p in BASE_DIR.glob(pattern) if p.is_file()}
    for raw in extra or []:
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.is_file():
            found.add(p)
        else:
            print(f"  warning: --path {raw} is not a readable file, skipped")
    return sorted(found)


def historical_compromised_values() -> tuple[str, ...]:
    """
    Recover the credential strings this repository published from Git history so
    they can be removed from local artifacts even after rotation. A recovered
    string is trusted only if its digest is in the compromise list, so the
    history scan can never inject an arbitrary value into the replacement set.
    Returns () when git is unavailable; values are never printed.
    """
    leaked = {v.lower() for v in config_module._KNOWN_COMPROMISED_SHA256.values()}

    def git(*args) -> str:
        try:
            done = subprocess.run(["git", "-C", str(BASE_DIR), *args],
                                  capture_output=True, text=True, timeout=60)
            return done.stdout if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    commits = git("log", "--format=%H", "--", *HISTORY_PROBE_PATHS).split()
    recovered: set[str] = set()
    for commit in commits:
        for path in HISTORY_PROBE_PATHS:
            blob = git("show", f"{commit}:{path}")
            for token in _CANDIDATE_RE.findall(blob):
                if hashlib.sha256(token.encode("utf-8")).hexdigest() in leaked:
                    recovered.add(token)
    return tuple(sorted(recovered))


async def scrub_database(secrets: tuple[str, ...], apply: bool) -> int:
    """Rows whose stored failure text still carries a credential. Returns the count."""
    if not secrets:
        return 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, error, details::text FROM data_refresh_runs "
            "WHERE error ~ :p OR details::text ~ :p"
        ), {"p": r"(api[-_]?key|access[-_]?token|secret|password|token)=[^\s&\"']+"})).all()

        affected = 0
        for rid, error, details in rows:
            new_error, hits1 = scrub_text(error or "", secrets)
            payload = json.loads(details) if details else {}
            new_details_json, hits2 = scrub_text(json.dumps(payload), secrets)
            if not (hits1 or hits2):
                continue
            affected += 1
            print(f"  data_refresh_runs #{rid}: "
                  f"error_replacements={hits1} details_replacements={hits2}")
            if apply:
                await db.execute(text(
                    "UPDATE data_refresh_runs SET error = :e, "
                    "details = CAST(:d AS jsonb) WHERE id = :i"
                ), {"e": new_error, "d": new_details_json, "i": rid})
        if apply:
            await db.commit()
    return affected


def scrub_logs(secrets: tuple[str, ...], apply: bool) -> int:
    affected = 0
    for path in find_log_files():
        content = path.read_text(encoding="utf-8", errors="replace")
        cleaned, hits = scrub_text(content, secrets)
        if not hits:
            continue
        affected += 1
        print(f"  {path.relative_to(BASE_DIR)}: replacements={hits}")
        if apply:
            path.write_text(cleaned, encoding="utf-8")
    return affected


def scrub_artifacts(secrets: tuple[str, ...], apply: bool, paths: list[Path]) -> int:
    """Patch/checkpoint files kept outside Git but still holding the old text."""
    affected = 0
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"  warning: {path} unreadable ({type(e).__name__}), skipped")
            continue
        cleaned, hits = scrub_text(content, secrets, allow_params=False)
        if not hits:
            continue
        affected += 1
        try:
            shown = path.relative_to(BASE_DIR)
        except ValueError:
            shown = path
        print(f"  {shown}: replacements={hits}")
        if apply:
            path.write_text(cleaned, encoding="utf-8")
    return affected


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrub leaked credentials at rest")
    parser.add_argument("--apply", action="store_true",
                        help="rewrite the log lines, rows and artifacts (default: report only)")
    parser.add_argument("--path", action="append", metavar="FILE",
                        help="extra artifact file to sweep (repeatable)")
    parser.add_argument("--no-history", action="store_true",
                        help="skip recovering published credentials from Git history")
    args = parser.parse_args(argv)

    secrets = secret_values()
    if not args.no_history:
        past = historical_compromised_values()
        secrets = tuple(sorted({*secrets, *past}, key=len, reverse=True))
    print(f"checking against {len(secrets)} configured or historically published "
          f"credential(s); values are never printed")
    print(f"mode: {'APPLY' if args.apply else 'report only (--apply to change anything)'}")

    log_files = scrub_logs(secrets, args.apply)
    artifacts = scrub_artifacts(secrets, args.apply, find_artifact_files(args.path))
    db_rows = await scrub_database(secrets, args.apply)
    await engine.dispose()

    print(f"\nlog files affected : {log_files}")
    print(f"artifacts affected: {artifacts}")
    print(f"db rows affected   : {db_rows}")
    if (log_files or artifacts or db_rows) and not args.apply:
        print("Nothing was changed. Re-run with --apply after reviewing the list.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

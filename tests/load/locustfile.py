"""
KisanMitra load test — Locust headless task set.

Targets:
  - /health             (always included; lightweight DB + model probe)
  - Configurable read endpoints via LOAD_TEST_READ_PATHS environment variable
    (comma-separated, e.g. "/health,/prices/crops-markets,/analytics/rag-health")

Pass/fail thresholds (checked by Locust's stop_test_on_allslave_quit or exit code):
  LOAD_TEST_P95_MS          — maximum acceptable p95 response time in milliseconds (default 800)
  LOAD_TEST_MAX_FAIL_RATIO  — maximum acceptable request failure ratio 0.0–1.0 (default 0.01)

Usage:
  locust --headless --locustfile tests/load/locustfile.py \
    --host http://localhost:8000 \
    --users 50 --spawn-rate 10 --run-time 2m \
    --html /tmp/locust-report.html --csv /tmp/locust-report
"""
from __future__ import annotations

import os
import statistics
from typing import TYPE_CHECKING

from locust import HttpUser, between, events, task
from locust.runners import MasterRunner

if TYPE_CHECKING:
    from locust.env import Environment

# ── Configuration from environment ────────────────────────────────────────────
_RAW_PATHS = os.environ.get("LOAD_TEST_READ_PATHS", "/health,/prices/crops-markets,/prices/districts")
READ_PATHS: list[str] = [p.strip() for p in _RAW_PATHS.split(",") if p.strip()]
# Ensure /health is always present so the test exercises the DB+model probe
if "/health" not in READ_PATHS:
    READ_PATHS.insert(0, "/health")

P95_THRESHOLD_MS = int(os.environ.get("LOAD_TEST_P95_MS", "800"))
MAX_FAIL_RATIO = float(os.environ.get("LOAD_TEST_MAX_FAIL_RATIO", "0.01"))


class KisanMitraReader(HttpUser):
    """
    Simulates read-only API clients: dashboard polling, price lookups,
    health probes. No authentication required for the public endpoints.
    """
    wait_time = between(0.5, 2.0)

    # Build weighted task list from READ_PATHS.
    # /health gets weight 1; all other paths get weight 3 (higher load on reads).
    def _make_tasks(self) -> None:
        pass

    @task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")

    @task(3)
    def read_prices(self) -> None:
        if "/prices/crops-markets" in READ_PATHS:
            self.client.get("/prices/crops-markets", name="/prices/crops-markets")
        else:
            self.client.get(READ_PATHS[-1], name=READ_PATHS[-1])

    @task(2)
    def read_dynamic_paths(self) -> None:
        # Distribute load across all configured paths
        import random
        path = random.choice(READ_PATHS)
        self.client.get(path, name=path)


# ── Pass/fail evaluation at test end ─────────────────────────────────────────
@events.quitting.add_listener
def evaluate_results(environment: "Environment", **_kwargs: object) -> None:
    """
    Fail the Locust run (exit code 1) if p95 latency or failure ratio
    exceeds the configured thresholds. This makes the CI step fail on
    a degraded API rather than always reporting green.
    """
    stats = environment.runner.stats if environment.runner else environment.stats
    total = stats.total

    failures: list[str] = []

    # p95 latency check (Locust stores response times in ms)
    p95_ms = total.get_response_time_percentile(0.95)
    if p95_ms is not None and p95_ms > P95_THRESHOLD_MS:
        failures.append(
            f"p95 latency {p95_ms:.0f} ms exceeds threshold {P95_THRESHOLD_MS} ms"
        )

    # Failure ratio check
    if total.num_requests > 0:
        fail_ratio = total.num_failures / total.num_requests
        if fail_ratio > MAX_FAIL_RATIO:
            failures.append(
                f"failure ratio {fail_ratio:.3f} ({total.num_failures}/{total.num_requests}) "
                f"exceeds threshold {MAX_FAIL_RATIO}"
            )

    if failures:
        print("\n[LOAD TEST FAILED]")
        for msg in failures:
            print(f"  ✗ {msg}")
        print(
            f"\nThresholds: p95 ≤ {P95_THRESHOLD_MS} ms, "
            f"fail ratio ≤ {MAX_FAIL_RATIO:.1%}"
        )
        environment.process_exit_code = 1
    else:
        print(
            f"\n[LOAD TEST PASSED] p95={p95_ms:.0f} ms, "
            f"failures={total.num_failures}/{total.num_requests} "
            f"({total.num_failures / max(total.num_requests, 1):.2%})"
        )

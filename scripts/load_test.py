#!/usr/bin/env python3
"""Lightweight async load/soak test against a running BlinkEngage stack.
See docs/architecture/performance.md for the M28 methodology, findings,
and how to interpret results.

No new dependency: uses ``httpx`` (already a runtime dependency) rather
than pulling in Locust/k6 for what a ~150-line asyncio script covers —
concurrency-controlled request generation against a realistic mix of
read/write endpoints, with p50/p95/p99 latency and error-rate reporting.

Usage:
    python scripts/load_test.py --base-url http://localhost:8000/api/v1 \
        --concurrency 20 --duration 30

Requires httpx: `pip install httpx` (already present in backend/.venv).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx


@dataclass
class EndpointStats:
    name: str
    latencies_ms: list[float] = field(default_factory=list)
    successes: int = 0
    failures: int = 0

    def summary(self) -> str:
        total = self.successes + self.failures
        if total == 0:
            return f"{self.name}: no requests"
        error_rate = self.failures / total * 100
        if not self.latencies_ms:
            return (
                f"{self.name}: {total} requests, {error_rate:.1f}% errors, "
                "no successful latency samples"
            )
        sorted_lat = sorted(self.latencies_ms)
        p50 = statistics.median(sorted_lat)
        p95 = sorted_lat[int(len(sorted_lat) * 0.95) - 1]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99) - 1]
        return (
            f"{self.name}: {total} requests, {error_rate:.1f}% errors, "
            f"p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms max={max(sorted_lat):.0f}ms"
        )


async def _timed_request(
    client: httpx.AsyncClient, stats: EndpointStats, method: str, url: str, **kwargs: object
) -> None:
    start = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
        elapsed_ms = (time.perf_counter() - start) * 1000
        stats.latencies_ms.append(elapsed_ms)
        if response.status_code >= 500:
            stats.failures += 1
        else:
            stats.successes += 1
    except httpx.HTTPError:
        stats.failures += 1


async def _register_and_login(client: httpx.AsyncClient) -> str:
    suffix = uuid4().hex[:8]
    payload = {
        "company_name": f"LoadTest {suffix}",
        "owner_full_name": "Load Test Owner",
        "owner_email": f"loadtest-{suffix}@example.com",
        "owner_password": "correct-horse-battery-9",
    }
    response = await client.post("/auth/register", json=payload)
    response.raise_for_status()
    token: str = response.json()["tokens"]["access_token"]
    return token


async def _seed_data(client: httpx.AsyncClient, headers: dict[str, str], count: int = 20) -> None:
    for i in range(count):
        await client.post(
            "/customers",
            json={
                "full_name": f"Load Test Customer {i}",
                "email": f"ltc{i}-{uuid4().hex[:6]}@example.com",
            },
            headers=headers,
        )


async def _worker(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    stats: dict[str, EndpointStats],
    stop_at: float,
) -> None:
    counter = 0
    while time.perf_counter() < stop_at:
        counter += 1
        await _timed_request(client, stats["list_customers"], "GET", "/customers", headers=headers)
        await _timed_request(
            client, stats["list_conversations"], "GET", "/conversations", headers=headers
        )
        await _timed_request(client, stats["get_company"], "GET", "/company", headers=headers)
        await _timed_request(
            client,
            stats["create_customer"],
            "POST",
            "/customers",
            headers=headers,
            json={"full_name": f"Concurrent Customer {counter}"},
        )


async def run(base_url: str, concurrency: int, duration: float) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        print("Registering a load-test company ...")
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        print("Seeding baseline data ...")
        await _seed_data(client, headers)

        stats = {
            name: EndpointStats(name)
            for name in ("list_customers", "list_conversations", "get_company", "create_customer")
        }

        print(f"Running {concurrency} concurrent workers for {duration:.0f}s ...")
        stop_at = time.perf_counter() + duration
        await asyncio.gather(
            *(_worker(client, headers, stats, stop_at) for _ in range(concurrency))
        )

        print("\n=== Load test results ===")
        for endpoint_stats in stats.values():
            print(endpoint_stats.summary())

        total_requests = sum(s.successes + s.failures for s in stats.values())
        print(
            f"\nTotal requests: {total_requests} over {duration:.0f}s "
            f"(~{total_requests / duration:.1f} req/s)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=float, default=30.0)
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.concurrency, args.duration))


if __name__ == "__main__":
    main()

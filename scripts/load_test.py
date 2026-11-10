"""Production Load Testing & Performance Benchmarking Harness for Snacky Studio.
Simulates realistic concurrent virtual users (traffic mix: health probes, task queries,
job creation, and rate-limit boundary testing) to benchmark RPS and latency percentiles.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import statistics
import time
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("load_test")

SAMPLE_URLS = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "mp4", "720"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "mp3", "320"),
    ("https://www.tiktok.com/@tiktok/video/7123456789", "mp4", "best"),
    ("https://www.instagram.com/p/Cxyz1234567/", "photo", "original"),
]


class LoadTestRunner:
    def __init__(
        self,
        base_url: str,
        concurrency: int = 10,
        duration_seconds: int = 15,
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.concurrency = concurrency
        self.duration_seconds = duration_seconds
        self.api_key = api_key
        self.latencies: list[float] = []
        self.status_codes: dict[int, int] = {}
        self.errors = 0
        self.total_requests = 0

    async def _worker(self, client: httpx.AsyncClient, stop_event: asyncio.Event):
        """Simulates one virtual user executing realistic multi-tenant workflows."""
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        while not stop_event.is_set():
            # Traffic mix selection:
            # 40% health/metrics probes, 35% task/history reads, 20% downloads, 5% burst rate-limit tests
            roll = random.random()
            start = time.monotonic()
            status = 0

            try:
                if roll < 0.40:
                    # Health & readiness probe
                    path = random.choice(["/api/health", "/health/ready", "/metrics"])
                    resp = await client.get(f"{self.base_url}{path}", headers=headers)
                    status = resp.status_code
                elif roll < 0.75:
                    # Task listing or download history
                    path = random.choice(["/api/tasks", "/api/history"])
                    resp = await client.get(f"{self.base_url}{path}", headers=headers)
                    status = resp.status_code
                elif roll < 0.95:
                    # Job creation
                    url, fmt, quality = random.choice(SAMPLE_URLS)
                    payload = {"url": url, "format": fmt, "quality": quality}
                    resp = await client.post(f"{self.base_url}/api/download", json=payload, headers=headers)
                    status = resp.status_code
                else:
                    # Burst query testing rate-limiting
                    resp = await client.get(f"{self.base_url}/api/tasks", headers=headers)
                    status = resp.status_code

                duration = time.monotonic() - start
                self.latencies.append(duration)
                self.status_codes[status] = self.status_codes.get(status, 0) + 1
                self.total_requests += 1

            except Exception as exc:
                self.errors += 1
                self.total_requests += 1

            # Brief human think time (10ms - 50ms)
            await asyncio.sleep(random.uniform(0.01, 0.05))

    async def run(self) -> dict[str, Any]:
        logger.info(
            "Starting load test on %s with %d virtual users for %ds...",
            self.base_url,
            self.concurrency,
            self.duration_seconds,
        )
        stop_event = asyncio.Event()

        timeout = httpx.Timeout(10.0, connect=3.0)
        limits = httpx.Limits(max_connections=self.concurrency * 2, max_keepalive_connections=self.concurrency)

        start_time = time.time()
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            workers = [
                asyncio.create_task(self._worker(client, stop_event))
                for _ in range(self.concurrency)
            ]

            await asyncio.sleep(self.duration_seconds)
            stop_event.set()
            await asyncio.gather(*workers, return_exceptions=True)

        elapsed = time.time() - start_time
        return self._generate_report(elapsed)

    def _generate_report(self, elapsed: float) -> dict[str, Any]:
        rps = self.total_requests / elapsed if elapsed > 0 else 0
        sorted_latencies = sorted(self.latencies) if self.latencies else [0.0]

        def percentile(p: float) -> float:
            if not sorted_latencies:
                return 0.0
            k = (len(sorted_latencies) - 1) * p
            f = int(k)
            c = f + 1 if f + 1 < len(sorted_latencies) else f
            d0 = sorted_latencies[f] * (c - k)
            d1 = sorted_latencies[c] * (k - f)
            return round((d0 + d1) * 1000, 2)  # milliseconds

        report = {
            "summary": {
                "duration_seconds": round(elapsed, 2),
                "concurrency": self.concurrency,
                "total_requests": self.total_requests,
                "requests_per_second": round(rps, 2),
                "error_count": self.errors,
                "status_distribution": self.status_codes,
            },
            "latency_ms": {
                "min": round(min(sorted_latencies) * 1000, 2) if sorted_latencies else 0,
                "p50_median": percentile(0.50),
                "p90": percentile(0.90),
                "p95": percentile(0.95),
                "p99": percentile(0.99),
                "max": round(max(sorted_latencies) * 1000, 2) if sorted_latencies else 0,
                "mean": round(statistics.mean(sorted_latencies) * 1000, 2) if sorted_latencies else 0,
            },
        }

        self._print_ascii_report(report)
        return report

    def _print_ascii_report(self, report: dict[str, Any]):
        s = report["summary"]
        l = report["latency_ms"]
        print("\n" + "=" * 65)
        print("          SNACKY STUDIO LOAD TEST PERFORMANCE REPORT")
        print("=" * 65)
        print(f" Target Base URL       : {self.base_url}")
        print(f" Duration              : {s['duration_seconds']}s")
        print(f" Concurrency (VUs)     : {s['concurrency']}")
        print(f" Total Requests        : {s['total_requests']}")
        print(f" Throughput            : {s['requests_per_second']} req/sec")
        print(f" Status Breakdown      : {s['status_distribution']}")
        print(f" Transport Errors      : {s['error_count']}")
        print("-" * 65)
        print(" LATENCY PERCENTILES (ms):")
        print(f"   p50 (Median)        : {l['p50_median']} ms")
        print(f"   p90                 : {l['p90']} ms")
        print(f"   p95                 : {l['p95']} ms")
        print(f"   p99                 : {l['p99']} ms")
        print(f"   Max                 : {l['max']} ms")
        print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Snacky Studio Asynchronous Load Test Harness")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Target server base URL")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Number of concurrent virtual users")
    parser.add_argument("-d", "--duration", type=int, default=10, help="Test duration in seconds")
    parser.add_argument("--api-key", default=None, help="Optional API key for authenticated testing")

    args = parser.parse_args()
    runner = LoadTestRunner(
        base_url=args.url,
        concurrency=args.concurrency,
        duration_seconds=args.duration,
        api_key=args.api_key,
    )
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()


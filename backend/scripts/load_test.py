"""Search latency test.

    python -m scripts.load_test --base-url http://localhost:8000 -n 200 -c 10
    python -m scripts.load_test --cached      # measure cache hits instead

Bypasses the result cache by default so it measures the real query path.
"""

import argparse
import asyncio
import random
import statistics
import time

import httpx

QUERIES = [
    "the clutch on Bind",
    "when my friend screamed",
    "headshot with a sniper",
    "squad wipe",
    "last circle win",
    "funny bug",
    "1v3 clutch",
    "ace in overtime",
    "rocket jump",
    "sunset over the map",
    "he's one shot",
    "victory royale",
]


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("-n", type=int, default=200, help="total requests")
    p.add_argument("-c", type=int, default=10, help="concurrency")
    p.add_argument("--cached", action="store_true", help="allow cache hits")
    p.add_argument("--game", default=None)
    args = p.parse_args()

    latencies: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(args.c)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60) as client:
        # Warm up (Modal cold starts, connection pools).
        await client.get("/search", params={"q": "warm up", "nocache": "true"})

        async def one() -> None:
            nonlocal errors
            params = {"q": random.choice(QUERIES), "limit": 20}
            if not args.cached:
                params["nocache"] = "true"
            if args.game:
                params["game"] = args.game
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await client.get("/search", params=params)
                    r.raise_for_status()
                    latencies.append((time.perf_counter() - t0) * 1000)
                except httpx.HTTPError:
                    errors += 1

        t_all = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(args.n)))
        wall = time.perf_counter() - t_all

    if not latencies:
        raise SystemExit(f"all {errors} requests failed")
    q = statistics.quantiles(latencies, n=100)
    print(f"requests={len(latencies)} errors={errors} concurrency={args.c} throughput={len(latencies) / wall:.1f} req/s")
    print(f"latency ms: p50={q[49]:.0f} p90={q[89]:.0f} p95={q[94]:.0f} p99={q[98]:.0f} max={max(latencies):.0f}")


if __name__ == "__main__":
    asyncio.run(main())

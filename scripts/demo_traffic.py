"""Send a mix of requests to a running app so the dashboard has data to show.

Usage (the app must already be running):
    python -m scripts.demo_traffic --seconds 60 --rps 20
"""

import argparse
import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

# (path, weight). Heavier weights are requested more often.
ROUTES = [
    ("/api/v1/incidents/options", 50),
    ("/api/v1/me", 20),
    ("/api/v1/incidents/assigned", 5),
    ("/health/live", 10),
    ("/health/ready", 10),
    ("/no-such-page", 5),
]


def send(client: httpx.Client, base_url: str) -> int:
    path = random.choices([r[0] for r in ROUTES], [r[1] for r in ROUTES])[0]

    try:
        return client.get(base_url + path).status_code
    except httpx.HTTPError:
        return 0  # 0 means the request did not complete at all.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--rps", type=int, default=20, help="requests per second")
    args = parser.parse_args()

    results: Counter[int] = Counter()

    with httpx.Client(timeout=10) as client, ThreadPoolExecutor(max_workers=50) as pool:
        for _ in range(args.seconds):
            started = time.monotonic()
            futures = [pool.submit(send, client, args.url) for _ in range(args.rps)]
            results.update(f.result() for f in futures)

            # Wait out the rest of the second so the rate stays steady.
            time.sleep(max(0.0, 1 - (time.monotonic() - started)))

    print(f"Sent {sum(results.values())} requests. Status codes:")
    for status, count in sorted(results.items()):
        label = "no response (is the app running?)" if status == 0 else status
        print(f"  {label}: {count}")


if __name__ == "__main__":
    main()

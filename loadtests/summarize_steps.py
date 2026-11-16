"""Turn a stepped Locust run into one table row per load level.

Usage, after a run that used `--csv loadtests/results/step1`:

    python -m loadtests.summarize_steps loadtests/results/step1

Locust writes a row of statistics every second. This script groups those rows
by the number of users and works out each level's own numbers by subtracting
running totals: how many requests were made, how many failed, and how long
they took on average.

It does NOT print percentiles (p50, p95, p99). Locust's history file reports
them for the whole run so far, not for one step, so they would hide what
happened at each level. For percentiles at one level, do a separate run at a
fixed number of users and read the "Aggregated" row of its `_stats.csv`.
"""

import csv
import sys
from collections import defaultdict

# Share of each step to ignore at the start, while users arrive and the
# system settles.
SETTLE_FRACTION = 0.3


def read_rows(prefix: str) -> list[dict]:
    with open(f"{prefix}_stats_history.csv", newline="") as file:
        return [row for row in csv.DictReader(file) if row["Name"] == "Aggregated"]


def _total_ms(row: dict) -> float:
    """Total time spent on all requests so far (average times the count)."""
    return float(row["Total Average Response Time"]) * int(row["Total Request Count"])


def summarize(rows: list[dict]) -> list[dict]:
    steps: dict[int, list[dict]] = defaultdict(list)

    for row in rows:
        users = int(row["User Count"])

        if users > 0:
            steps[users].append(row)

    table = []

    for users in sorted(steps):
        step_rows = steps[users]
        start = step_rows[int(len(step_rows) * SETTLE_FRACTION)]
        end = step_rows[-1]

        requests = int(end["Total Request Count"]) - int(start["Total Request Count"])
        failures = int(end["Total Failure Count"]) - int(start["Total Failure Count"])
        seconds = int(float(end["Timestamp"])) - int(float(start["Timestamp"]))

        table.append(
            {
                "users": users,
                "requests": requests,
                "rps": requests / seconds if seconds else 0.0,
                "mean_ms": (_total_ms(end) - _total_ms(start)) / requests
                if requests
                else 0.0,
                "failure_percent": 100 * failures / requests if requests else 0.0,
            }
        )

    return table


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m loadtests.summarize_steps <csv prefix>")

    table = summarize(read_rows(sys.argv[1]))

    print("| Users | Requests | Requests/s | Mean (ms) | Failures |")
    print("|---:|---:|---:|---:|---:|")

    for row in table:
        print(
            f"| {row['users']} | {row['requests']} | {row['rps']:.0f} "
            f"| {row['mean_ms']:.0f} | {row['failure_percent']:.1f}% |"
        )


if __name__ == "__main__":
    main()

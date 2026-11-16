"""Summarise Postgres slow-query log lines, grouped by statement.

Usage:
    docker logs resqgrid-postgres --since 15m 2>&1 | python -m scripts.slow_query_digest
"""

import collections
import re
import sys

PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} [\d:.]+ \S+ \[\d+\] ", re.M)
DURATION = re.compile(
    r"LOG:\s+duration: ([0-9.]+) ms\s+(?:execute [^:]*|statement): (.*)", re.S
)


def main() -> None:
    text = sys.stdin.read()
    stats = collections.defaultdict(lambda: [0, 0.0, 0.0, ""])
    last_key = None

    for entry in PREFIX.split(text):
        entry = entry.strip()
        match = DURATION.match(entry)
        if match:
            ms = float(match.group(1))
            sql = " ".join(match.group(2).split())[:700]
            row = stats[sql]
            row[0] += 1
            row[1] += ms
            row[2] = max(row[2], ms)
            last_key = sql
        elif entry.startswith("DETAIL:") and last_key and not stats[last_key][3]:
            stats[last_key][3] = " ".join(entry.split())[:300]

    ranked = sorted(stats.items(), key=lambda item: -item[1][1])[:10]
    for sql, (count, total, worst, params) in ranked:
        print(f"{count:5d} calls  total {total:8.0f} ms  slowest {worst:6.0f} ms")
        print(f"      {sql[:450]}")
        if params:
            print(f"      example {params}")
        print()


def read_input() -> str:
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return sys.stdin.read()


if __name__ == "__main__":
    main()

# Round 0 baseline (before any optimization)

Run date: 2026-11-12. Code version: 52eb9da

## Setup
- Machine: Windows laptop, 12th-gen Intel i7, 16 GB RAM. Docker limited to
  8 GB Ram and 12 processors in .wslconfig.
- API: Docker container `resqgrid-api`, limited to 1 CPU and 512 MB, one uvicorn
  process. Worker threads: 40 (default). Database pool: 10 connections plus 20
  overflow, 30 s wait before a timeout.
- Database: PostgreSQL 16 in Docker with 10,209 seeded users and 200,003 incidents
  (200,000 seeded plus 3 earlier records). No indexes beyond the original schema.
- Locust 2.47.0 on the same machine. Users: 70% citizens, 25% officials, 5% admins.
  Pause between actions 0.5 to 1.5 s. Access tokens are created directly, so
  there is no login traffic.
- Load shape: +50 users every 60 s, up to 800 users (16 steps, about 16 minutes).

## How to reproduce
```powershell
$env:JWT_ACCESS_TOKEN_EXPIRE_MINUTES = "240"
$env:LOAD_TEST_THINK_MIN = "0.5"
$env:LOAD_TEST_THINK_MAX = "1.5"
$env:STEP_USERS = "50"
$env:STEP_SECONDS = "60"
$env:MAX_USERS = "800"
locust -f loadtests/locustfile.py,loadtests/stress_shape.py --host http://127.0.0.1:8000 --headless --csv loadtests/results/step1 --only-summary
python -m loadtests.summarize_steps loadtests/results/step1
```

## Whole run
- 23,301 requests, 975 failed (4.18%), all HTTP 500
- Median 17 ms, average 10,468 ms, max 479,849 ms (about 8 minutes)
- p95 60,000 ms, p99 270,000 ms

## Per step
The Requests column counts only the last 70% of each step. The first 30% is
ignored while users arrive.

| Users | Requests | Requests/s | Mean (ms) | Failures |
|---:|---:|---:|---:|---:|
| 50 | 2016 | 49 | 14 | 0.0% |
| 100 | 3976 | 97 | 28 | 0.0% |
| 150 | 6002 | 146 | 28 | 0.0% |
| 200 | 1245 | 30 | 1743 | 2.7% |
| 250 | 126 | 3 | 71796 | 62.7% |
| 300 | 81 | 2 | 106496 | 98.8% |
| 350 | 154 | 4 | 110398 | 50.6% |
| 400 | 80 | 2 | 155985 | 100.0% |
| 450 | 168 | 4 | 153478 | 41.7% |
| 500 | 81 | 2 | 195101 | 98.8% |
| 550 | 80 | 2 | 223207 | 100.0% |
| 600 | 82 | 2 | 239066 | 97.6% |
| 650 | 211 | 5 | 195642 | 35.5% |
| 700 | 80 | 2 | 283665 | 100.0% |
| 750 | 80 | 2 | 305344 | 100.0% |
| 800 | 80 | 2 | 328000 | 100.0% |

## Findings
- Last healthy level: 150 users, 146 requests/s, mean latency 28 ms, 0% failures.
- Breakdown during the 200-user step: 30 requests/s, mean 1.7 s, 2.7% failures.
  From 250 users the app completes about 2 requests/s, almost all failures, with
  mean waits of about 1 to 5.5 minutes. This is a cliff, not a gradual slowdown.
- Likely cause: the database connection pool running dry (10 + 20 connections,
  30 s wait), which produces `QueuePool limit of size 10 overflow 20 reached,
  connection timed out, timeout 30.00` errors.
- About 2 requests/s in the dead zone is the same order as 40 worker threads each
  waiting the 30 s pool timeout (40 / 30 = 1.3 per second).
- Percentile columns were removed: Locust's history file reports them cumulatively
  since the start of the run, so they hide what happened at each level. Mean
  latency per step is computed from differences of running totals.
- Raw data: loadtests/results/round0/step1_*.csv (not in Git, backed up in
  Documents\resqgrid-round0-baseline.zip).

## Rounds log
| Round | Change | Last healthy level (users) | Mean at 150 users (ms) | Notes |
|---|---|---:|---:|---|
| 0 | None (baseline) | 150 | 28 | Collapse during the 200-user step |
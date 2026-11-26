# Making the API survive load: a performance case study

## Summary

Under load testing, the ResQGrid API collapsed at 200 simulated users. Throughput fell from about 150 requests per second to a few, and most requests failed after waiting 30 seconds. I traced the collapse to database connection pool exhaustion, added two database indexes (the collapse moved from 200 to 300 users), and then added a limit on concurrent requests. With the limit, the API handled 800 simulated users with zero failures. With the limit switched off, the collapse came back, which is the direct evidence that the limit is what fixed it.

| Round | Change | Result of the stepped test (50 more users every 60 s) |
|---|---|---|
| 0 | None (baseline) | Healthy to 150 users (146 req/s, 28 ms mean). Collapse at 200 users. |
| 1 | Two list indexes on `incidents` | Healthy to 250 users (237 req/s, 55 ms mean). Collapse at 300 users. |
| 2 | Limit of 25 concurrent requests | 0 failures up to 800 users. Throughput levels off at about 200 to 210 req/s, and mean latency rises gradually (33 ms at 200 users, 1.4 s at 500, 3.0 s at 800). |

## How I tested

- **Machine:** a Windows laptop (12th-generation Intel i7, 16 GB RAM). Docker had 8 GB of memory and 12 processors.
- **API:** a Docker container limited to 1 CPU and 512 MB, with one Uvicorn worker and a database pool of 10 connections plus 20 overflow.
- **Database:** PostgreSQL 16 in Docker with 10,209 seeded users and 200,003 incidents.
- **Load:** Locust 2.47.0 on the same machine. The traffic mix is 70% citizens, 25% officials and 5% admins, with a pause of 0.5 to 1.5 s between actions.
- **Method:** one change per round, then the same stepped run (50 more users every 60 s, up to 800), recorded in `loadtests/round0-baseline.md`.

## Round 0: the baseline and the collapse

The API was healthy up to 150 users. At 200 users throughput dropped to 30 requests per second with 2.7% failures. By 250 users it completed about 3 requests per second, and 62.7% of them failed. Over the whole run, 975 of 23,301 requests failed, all with HTTP 500. This was a sudden drop, not a gradual slowdown.

## Finding the cause

- **The error:** the API log showed `QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00`. The slow requests waited in multiples of 30 seconds, which is that timeout.
- **The pool at the time:** during a diagnostic run, all 30 connections were `idle in transaction` with almost none running a query. After the load stopped, the pool returned to its normal idle size, so connections were not leaking. They were being held, not used.
- **A request that never touches the database was also slow.** `GET /incidents/options` uses no database, yet it averaged several seconds during the collapse. That points to requests waiting for worker threads, not for queries.
- **Reading the code:** every route is a synchronous function, and FastAPI runs each synchronous step in a worker thread (40 by default). A request takes a database connection at its first query and keeps it until it finishes. The pool has 30 connections, so with enough requests in flight, requests holding connections wait for a free thread while threads wait for a connection. Nothing moves until the 30-second timeout fires.

I treat this as the explanation that fits all the evidence. Round 2 then tested it directly.

## Round 1: indexes

I logged every statement slower than 20 ms and summarised the log with `scripts/slow_query_digest.py`. Two query shapes took about 81% of the slow-query time: the officials' incident list and the unfiltered admin list. The code compares `lower(district)` and `lower(tehsil)`, so a plain index would not be used. I added two indexes with `CREATE INDEX CONCURRENTLY` so writes are not blocked:

- `(created_at DESC, id DESC)` for the unfiltered admin list.
- `(lower(district), lower(tehsil), created_at DESC, id DESC)` for officials' lists.

Postgres now reads the first page of each list straight from the index, with no sort (0.49 ms and 0.04 ms warm in `EXPLAIN ANALYZE`). In a 150-user comparison, the median went from 26 ms to 6 ms and the 95th percentile from 310 ms to 25 ms, and the slow-query list went from 8 shapes (about 109 s of query time in a 90 s run) to 2 (about 0.5 s). The collapse moved from 200 users to 300, but it was still a cliff, because the cause was not query speed.

## Round 2: limiting concurrent requests

I added a small middleware that allows at most 25 requests to be handled at once, which is below the pool size of 30. Extra requests wait in a queue that uses no thread and no database connection, and get a 503 with `Retry-After` if they wait more than 5 seconds. Health checks and `/metrics` are never limited. Two new metrics (`http_requests_waiting`, `http_requests_shed_total`) show the queue, and the app refuses to start if the limit is above the pool size.

The stepped test then ran to 800 users with 0 failures in 176,597 requests. To check that the limit was responsible, I ran the same traffic with it switched off:

| | Limiter on | Limiter off |
|---|---|---|
| 150 users, sudden start | 11,920 requests, 0% failed, mean 104 ms | 311 requests, 25.7% failed, mean 19.7 s |
| 250 users, sudden start | 16,369 requests, 0% failed, mean 317 ms | 70 requests, 57.1% failed, mean 38.2 s |

An earlier identical run with the limiter off had been fine at 150 users, so the collapse is triggered by a burst of requests, not by a fixed number of users. The gradual ramp of the stepped test avoids that trigger.

## What these results do not show

- **One run per configuration.** There are no repeated runs or confidence intervals, and some differences (for example the 150-user mean of 104 ms with the limiter on, against 28 ms in the stepped run) are probably laptop noise that I did not resolve.
- **The load generator shares the laptop** with the API and the database, so they compete for CPU.
- **The traffic is synthetic.** The user mix and the pauses are assumptions.
- **The cause is supported by evidence and by the on/off test**, but I did not instrument the thread pool to watch the deadlock directly.
- **The limiter does not add capacity.** On one CPU the API tops out at about 200 to 210 requests per second. Beyond that, responses get slower but nothing breaks.

## What I would do next

1. Check whether the API container's CPU sits near 100% during a 250-user run. If it does, the limit is CPU, and the fix is capacity, not code.
2. Run two workers or a larger CPU limit. That needs Redis for shared rate limits (memory-based limits are per process) and Prometheus multiprocess mode, because metrics are per process today.
3. Add alert rules for `http_requests_shed_total` and a sustained high `http_requests_waiting`.
4. Consider caching only if profiling shows repeated reads are a real cost. After the indexes, the database is no longer the bottleneck.

## Reproduce it

The load-testing commands are in the "Load testing" section of the README, and the results of every round are in `loadtests/round0-baseline.md`.

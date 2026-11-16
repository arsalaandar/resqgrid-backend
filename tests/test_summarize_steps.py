from loadtests.summarize_steps import summarize


def row(timestamp, users, count, average_ms, failures):
    return {
        "Timestamp": str(timestamp),
        "User Count": str(users),
        "Total Request Count": str(count),
        "Total Average Response Time": str(average_ms),
        "Total Failure Count": str(failures),
    }


def test_each_step_uses_only_its_own_requests_and_time():
    # 10 rows per step, one per second. Totals only ever grow, as in Locust.
    # Step 1 (10 users): 100 requests in the settled part, all 10 ms.
    # Step 2 (20 users): 100 more requests that took 100 ms each, 10 failed.
    rows = []
    count, total_ms, failures = 0, 0.0, 0

    for second in range(10):
        count, total_ms = count + 10, total_ms + 10 * 10
        rows.append(row(1000 + second, 10, count, total_ms / count, failures))

    for second in range(10):
        count, total_ms, failures = count + 10, total_ms + 10 * 100, failures + 1
        rows.append(row(1010 + second, 20, count, total_ms / count, failures))

    first, second_step = summarize(rows)

    assert first["users"] == 10
    assert round(first["mean_ms"]) == 10
    assert second_step["users"] == 20
    assert round(second_step["mean_ms"]) == 100
    assert round(second_step["rps"]) == 10
    assert round(second_step["failure_percent"]) == 10


def test_rows_with_no_users_are_ignored():
    assert summarize([row(1000, 0, 0, 0.0, 0)]) == []

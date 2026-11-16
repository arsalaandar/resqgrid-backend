"""Load-test scenarios for ResQGrid.

Run the app first (for example with `docker compose --profile app up -d`),
seed the database (`python -m scripts.seed_load_test_data --confirm`), then:

    # Web interface at http://localhost:8089
    locust -f loadtests/locustfile.py --host http://127.0.0.1:8000

    # No interface: 100 users, 10 new users per second, for 2 minutes
    locust -f loadtests/locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 100 -r 10 -t 2m --csv loadtests/results/run1

Logging in is rate limited (5 per minute per IP), and a load generator sends
everything from one address. So instead of logging in, this file creates
access tokens directly for the seeded users. Those tokens last only
JWT_ACCESS_TOKEN_EXPIRE_MINUTES (15 by default), so for longer runs set a
larger value in the shell that starts Locust, for example 240.

Settings (environment variables):
    LOAD_TEST_POOL        users per role to load from the database (default 500)
    LOAD_TEST_THINK_MIN   shortest pause between actions, seconds (default 3)
    LOAD_TEST_THINK_MAX   longest pause between actions, seconds (default 8)
    LOAD_TEST_P95_MS      fail the run if overall p95 is slower than this (500)
"""

import os
import random
from datetime import UTC, datetime, timedelta

from locust import HttpUser, between, events, task
from sqlalchemy import select

from app.core.incident_options import (
    DAMAGE_SITUATIONS,
    DISTRICT_TEHSILS,
    INCIDENT_CATEGORIES,
    INCIDENT_SEVERITY_LEVELS,
)
from app.core.roles import Role
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.models.user import User
from scripts.seed_load_test_data import SEED_PHONE_PREFIX

POOL_SIZE = int(os.getenv("LOAD_TEST_POOL", "500"))
THINK_MIN = float(os.getenv("LOAD_TEST_THINK_MIN", "3"))
THINK_MAX = float(os.getenv("LOAD_TEST_THINK_MAX", "8"))
P95_LIMIT_MS = float(os.getenv("LOAD_TEST_P95_MS", "500"))
MAX_FAILURE_RATIO = 0.01

# Filled in when the test starts: lists of (user_id, access_token).
POOLS: dict[str, list[tuple[int, str]]] = {"citizen": [], "official": [], "admin": []}

JURISDICTIONS = [
    (district, tehsil)
    for district, tehsils in DISTRICT_TEHSILS.items()
    for tehsil in tehsils
]


def _load_pool(session, role: Role, limit: int) -> list[tuple[int, str]]:
    users = session.execute(
        select(User.id, User.token_version)
        .where(User.phone.like(f"{SEED_PHONE_PREFIX}%"), User.role == role.value)
        .order_by(User.id)
        .limit(limit)
    ).all()

    return [(uid, create_access_token(uid, version)) for uid, version in users]


@events.test_start.add_listener
def load_users(environment, **kwargs):
    with SessionLocal() as session:
        POOLS["citizen"] = _load_pool(session, Role.CITIZEN, POOL_SIZE)
        POOLS["official"] = _load_pool(session, Role.OFFICIAL, POOL_SIZE)
        POOLS["admin"] = _load_pool(session, Role.ADMIN, POOL_SIZE)

    print({role: len(users) for role, users in POOLS.items()})

    if not all(POOLS.values()):
        raise SystemExit(
            "No seeded users found. Run: "
            "python -m scripts.seed_load_test_data --confirm"
        )


@events.quitting.add_listener
def check_thresholds(environment, **kwargs):
    """Make the run fail when it misses the targets, so a script can notice."""
    total = environment.stats.total

    if not total.num_requests:
        return

    p95 = total.get_response_time_percentile(0.95)

    if total.fail_ratio > MAX_FAILURE_RATIO:
        print(f"FAILED: {total.fail_ratio:.1%} of requests failed")
        environment.process_exit_code = 1
    elif p95 > P95_LIMIT_MS:
        print(f"FAILED: p95 is {p95:.0f} ms, the target is {P95_LIMIT_MS:.0f} ms")
        environment.process_exit_code = 1


class SeededUser(HttpUser):
    """Base class: one simulated person using a seeded account."""

    abstract = True
    role = ""
    wait_time = between(THINK_MIN, THINK_MAX)

    def on_start(self):
        self.user_id, token = random.choice(POOLS[self.role])
        self.client.headers["Authorization"] = f"Bearer {token}"

    def fetch(self, path, name, params=None):
        """GET a page and count anything other than 200 as a failure."""
        with self.client.get(
            path, params=params, name=name, catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

            return response


class Citizen(SeededUser):
    """Most traffic: people reading their own reports and occasionally filing one."""

    weight = 70
    role = "citizen"

    def on_start(self):
        super().on_start()
        self.own_incident_ids: list[int] = []

    @task(3)
    def form_options(self):
        self.fetch("/api/v1/incidents/options", "GET /incidents/options")

    @task(2)
    def my_profile(self):
        self.fetch("/api/v1/me", "GET /me")

    @task(4)
    def my_incidents(self):
        response = self.fetch(
            "/api/v1/incidents/my", "GET /incidents/my", {"limit": 20}
        )

        if response.status_code == 200:
            self.own_incident_ids = [item["id"] for item in response.json()]

    @task(2)
    def one_of_my_incidents(self):
        if self.own_incident_ids:
            incident_id = random.choice(self.own_incident_ids)
            self.fetch(f"/api/v1/incidents/{incident_id}", "GET /incidents/[id]")

    @task(1)
    def report_incident(self):
        district, tehsil = random.choice(JURISDICTIONS)
        payload = {
            "incident_category": random.choice(INCIDENT_CATEGORIES),
            "is_drill": False,
            "incident_datetime": (
                datetime.now(UTC) - timedelta(minutes=random.randint(5, 600))
            ).isoformat(),
            "district": district,
            "tehsil": tehsil,
            "description": "Load test report, please ignore.",
            "latitude": random.uniform(32.3, 34.9),
            "longitude": random.uniform(73.9, 76.0),
            "damage_situation": random.choice(DAMAGE_SITUATIONS),
            "severity_level": random.choice(INCIDENT_SEVERITY_LEVELS),
            "additional_remarks": "Generated by the load test.",
        }

        with self.client.post(
            "/api/v1/incidents",
            json=payload,
            name="POST /incidents",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")


class Official(SeededUser):
    """Field officials checking incidents in their own district and tehsil."""

    weight = 25
    role = "official"

    def on_start(self):
        super().on_start()
        self.seen_ids: list[int] = []

    @task(5)
    def assigned_first_page(self):
        response = self.fetch(
            "/api/v1/incidents/assigned",
            "GET /incidents/assigned (page 1)",
            {"limit": 20},
        )

        if response.status_code == 200:
            self.seen_ids = [item["id"] for item in response.json()]

    @task(1)
    def assigned_deep_page(self):
        self.fetch(
            "/api/v1/incidents/assigned",
            "GET /incidents/assigned (deep page)",
            {"limit": 20, "offset": random.randint(100, 2000)},
        )

    @task(2)
    def open_an_incident(self):
        if self.seen_ids:
            incident_id = random.choice(self.seen_ids)
            self.fetch(f"/api/v1/incidents/{incident_id}", "GET /incidents/[id]")

    @task(1)
    def my_profile(self):
        self.fetch("/api/v1/me", "GET /me")


class Admin(SeededUser):
    """A few admins running the heavy filtered lists."""

    weight = 5
    role = "admin"

    @task(3)
    def by_district(self):
        district = random.choice(list(DISTRICT_TEHSILS))
        self.fetch(
            "/api/v1/admin/incidents",
            "GET /admin/incidents (district)",
            {"district": district, "limit": 20},
        )

    @task(2)
    def by_category_and_date(self):
        since = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        self.fetch(
            "/api/v1/admin/incidents",
            "GET /admin/incidents (category, date)",
            {
                "category": random.choice(INCIDENT_CATEGORIES),
                "date_from": since,
                "limit": 20,
            },
        )

    @task(1)
    def everything(self):
        self.fetch(
            "/api/v1/admin/incidents",
            "GET /admin/incidents (no filter)",
            {"limit": 20},
        )

    @task(1)
    def deep_page(self):
        self.fetch(
            "/api/v1/admin/incidents",
            "GET /admin/incidents (deep page)",
            {"limit": 20, "offset": random.randint(1000, 20000)},
        )

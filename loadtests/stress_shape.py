"""A stepped load shape: add users in stages and hold each stage for a while.

Use it together with the scenarios in locustfile.py:

    locust -f loadtests/locustfile.py,loadtests/stress_shape.py \
        --host http://127.0.0.1:8000 --headless --csv loadtests/results/step1

Every STEP_SECONDS the number of users grows by STEP_USERS, until MAX_USERS.
Holding each level steady lets you read one clean row per level, and the
level where response times start to climb is where the system saturates.

Settings (environment variables):
    STEP_USERS      users added at each step (default 50)
    STEP_SECONDS    how long each step lasts (default 60)
    MAX_USERS       stop after this many users (default 1000)
"""

import os

from locust import LoadTestShape

STEP_USERS = int(os.getenv("STEP_USERS", "50"))
STEP_SECONDS = int(os.getenv("STEP_SECONDS", "60"))
MAX_USERS = int(os.getenv("MAX_USERS", "1000"))


class StepLoad(LoadTestShape):
    def tick(self):
        step = int(self.get_run_time() // STEP_SECONDS) + 1
        users = step * STEP_USERS

        if users > MAX_USERS:
            return None  # None ends the test

        # The second value is how fast to add users while moving to a new step.
        return users, STEP_USERS

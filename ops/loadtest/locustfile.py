"""Read-heavy load profile of a signed-in team using the dashboard (LOAD_* env from run-local.sh).

Each simulated user is a member browsing: dashboard, product list pages, product detail,
offers, trends, sellers, changes and alerts. Think time 1-3 s per action.
"""

from __future__ import annotations

import os
import random
import time

import jwt
from locust import HttpUser, between, task

ORG = os.environ["LOAD_ORG_ID"]
USER = os.environ["LOAD_USER_ID"]
SECRET = os.environ["LOAD_JWT_SECRET"]
ISSUER = os.environ["LOAD_JWT_ISSUER"]


def _token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": USER, "email": f"load-{USER[:8]}@example.com", "aud": "authenticated",
         "iss": ISSUER, "role": "authenticated", "iat": now, "exp": now + 3600},
        SECRET,
        algorithm="HS256",
    )  # fmt: skip


class TeamMember(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.client.headers.update({"Authorization": f"Bearer {_token()}", "X-Organization-Id": ORG})
        items = self.client.get("/api/v1/products?page_size=100", name="products list").json()["items"]
        self.products = [p["id"] for p in items]

    @task(4)
    def dashboard(self) -> None:
        self.client.get("/api/v1/dashboard/summary", name="dashboard summary")
        self.client.get("/api/v1/alerts/summary", name="alerts summary")

    @task(4)
    def product_list(self) -> None:
        page = random.randint(1, 4)
        sort = random.choice(["created_at", "unique_seller_count", "lowest_observed_price"])
        self.client.get(f"/api/v1/products?page={page}&page_size=25&sort={sort}", name="products list")

    @task(3)
    def product_detail(self) -> None:
        pid = random.choice(self.products)
        self.client.get(f"/api/v1/products/{pid}", name="product detail")
        self.client.get(f"/api/v1/products/{pid}/offers", name="product offers")
        self.client.get(f"/api/v1/products/{pid}/trends", name="product trends")

    @task(2)
    def sellers(self) -> None:
        self.client.get("/api/v1/sellers?page_size=25", name="sellers list")

    @task(1)
    def changes(self) -> None:
        self.client.get("/api/v1/changes?page_size=50", name="change feed")
        self.client.get("/api/v1/alerts?active=true", name="alerts list")

"""Seeds a load-test organization: N products, all scanned through the (MOCK) worker.

Usage: python seed.py <api-url> <jwt-secret> <issuer> <products>  -> prints org id
Runs against a throwaway local stack only (run-local.sh).
"""

from __future__ import annotations

import sys
import time
import uuid

import httpx
import jwt


def token(secret: str, issuer: str, user: uuid.UUID, email: str) -> str:
    now = int(time.time())
    claims = {"sub": str(user), "email": email, "aud": "authenticated", "iss": issuer,
              "role": "authenticated", "iat": now, "exp": now + 4 * 3600}  # fmt: skip
    return jwt.encode(claims, secret, algorithm="HS256")


def main() -> None:
    api, secret, issuer, count = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    user = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token(secret, issuer, user, f'load-{user.hex[:8]}@example.com')}"}
    with httpx.Client(base_url=api, headers=headers, timeout=60) as c:
        org = c.post("/organizations", json={"name": "Load Test Co"}).raise_for_status().json()["id"]
        h = {"X-Organization-Id": org}
        csv_rows = "ASIN,Product name,Brand\n" + "".join(
            f"B0LOAD{i:04d},Load product {i},Brand {i % 7}\n" for i in range(count)
        )
        batch = c.post("/uploads", headers=h, files={"file": ("load.csv", csv_rows, "text/csv")})
        batch_id = batch.raise_for_status().json()["id"]
        for _ in range(120):
            state = c.get(f"/uploads/{batch_id}", headers=h).json()
            if state["status"] == "preview_ready":
                break
            time.sleep(0.5)
        c.post(f"/uploads/{batch_id}/commit", headers=h).raise_for_status()
        job = c.post("/scan-jobs", headers=h, json={"all_monitored": True}).raise_for_status().json()
        for _ in range(600):
            j = c.get(f"/scan-jobs/{job['id']}", headers=h).json()
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(1)
        print(org, user, j["status"], j["completed_items"], file=sys.stderr)
        print(f"{org} {user}")


if __name__ == "__main__":
    main()

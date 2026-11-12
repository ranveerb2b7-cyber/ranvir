# Load testing

`ops/loadtest/run-local.sh` starts a throwaway stack: a fresh PostgreSQL database, Redis, a Celery worker, and the API with `LOAD_API_WORKERS` uvicorn processes. It seeds `LOAD_PRODUCTS` products through the real upload and scan path (MOCK connector), then runs locust (`ops/loadtest/locustfile.py`).

The traffic mix is read-heavy dashboard use: dashboard, product list with sorting, product detail with offers and trends, sellers, change feed and alerts, with 1–3 s think time per simulated user. Results are checked against the targets below; the script exits non-zero if they're missed.

## Targets (per environment, at the planned size)
| Target | Value |
|---|---|
| p95 latency, read API | ≤ 500 ms |
| Error rate | < 1% |
| Throughput | ≥ 30 req/s at 50 active users (normal), ≥ 100 req/s at 300 users (peak) |

## Results, 2026-11-12, local machine
Setup: 4 vCPU shared by PostgreSQL, Redis, the worker, locust and 2 API processes; 100 products, 80 of them with offer data (MOCK).

| Profile | Requests | Throughput | Median | p95 | p99 | Errors | Result |
|---|---|---|---|---|---|---|---|
| 50 users, 90 s | 3,986 | 44.7 req/s | 12 ms | 28 ms | 86 ms | 0 | PASSED |
| 300 users, 60 s (near saturation) | 10,925 | 184.8 req/s | 140 ms | 470 ms | 770 ms | 0 | PASSED (just) |

In the 300-user run, the slowest routes were the sellers list and the dashboard summary (p95 about 510 ms).

**Caveats:**
- These are local numbers on one small shared machine. Repeat against **staging**, where the API runs on separate Fargate tasks with RDS, before launch.
- Scan throughput is bounded by Amazon's SP-API rate limits per seller account, not by our servers. It needs measuring in M7 with real credentials.
- **Not measured:** write-heavy load (uploads, scans, reports) and very large organizations (10k+ products).

## Run it
```bash
./ops/loadtest/run-local.sh
LOAD_USERS=300 LOAD_DURATION=60s LOAD_TARGET_RPS=100 ./ops/loadtest/run-local.sh
```
Against staging, run locust directly: `--host https://<api-host>`, with a test organization's ids and a valid token. The per-IP limit (`RATE_LIMIT_IP_PER_MINUTE`) applies there, so use several source IPs or raise it temporarily on staging only.

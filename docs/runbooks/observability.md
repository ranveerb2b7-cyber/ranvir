# Observability

## Signals
- **Logs:**
  - JSON to stdout, collected in CloudWatch Logs (`/sellerscope/<env>/<service>`; 30 days staging, 180 production for CERT-In).
  - Every API log line carries `request_id`, which is also returned as the `X-Request-ID` header, so a customer's error can be traced to its log lines.
  - `LOG_LEVEL=DEBUG` is refused in staging/production.
- **Metrics:** `GET /metrics` (Prometheus text format).
  - It requires `Authorization: Bearer <METRICS_TOKEN>` and is blocked at the load balancer, so scrape it from inside the VPC (e.g. an ADOT collector or Grafana Agent sidecar).
- **Errors:** set `SENTRY_DSN` to send unhandled exceptions from the API and workers to Sentry.
  - Request bodies and personal data are never sent (`send_default_pii=False`, `max_request_body_size="never"`).
  - Tracing is off unless `SENTRY_TRACES_SAMPLE_RATE` is above 0.
- **Infrastructure:** CloudWatch alarms (Terraform `monitoring.tf`), ECS Container Insights, RDS Performance Insights.

## Metrics
| Metric | Meaning |
|---|---|
| `sellerscope_http_requests_total{method,route,status}` | Requests per route **template** (no ids in labels) |
| `sellerscope_http_request_duration_seconds{method,route}` | Latency histogram |
| `sellerscope_queue_length{queue}` | Messages waiting per Celery queue |
| `sellerscope_scan_items_pending` / `_processing` | Scan backlog |
| `sellerscope_oldest_pending_scan_item_s` | Age of the oldest due scan item (workers stuck?) |
| `sellerscope_scan_results_last_hour` / `sellerscope_scan_errors_last_hour` | Scan throughput and failures |
| `sellerscope_alert_deliveries_pending` / `_failed` | Alert emails waiting / gave up |
| `sellerscope_reports_active` / `sellerscope_reports_failed_last_day` | Report exports in progress / failed |
| `sellerscope_metrics_scrape_errors_total{source}` | The database or Redis couldn't be read during a scrape |

The backlog and failure gauges come from `ops_metrics()` (migration 0010), a SECURITY DEFINER function that returns **counts only** across all organizations: no ids, names or per-tenant numbers.

## Suggested alert rules (PromQL)
```
# Workers stuck: due scans waiting more than 15 minutes
sellerscope_oldest_pending_scan_item_s > 900
# Scan failure rate above 20% over the last hour (connector or Amazon problem)
sellerscope_scan_errors_last_hour / clamp_min(sellerscope_scan_results_last_hour, 1) > 0.2
# Alert emails giving up (SMTP/SES problem)
increase(sellerscope_alert_deliveries_failed[1h]) > 0
# Error rate
sum(rate(sellerscope_http_requests_total{status=~"5.."}[5m])) / sum(rate(sellerscope_http_requests_total[5m])) > 0.02
# p95 latency per route
histogram_quantile(0.95, sum by (le, route) (rate(sellerscope_http_request_duration_seconds_bucket[5m]))) > 1
```

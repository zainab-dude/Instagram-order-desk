# A3 progress log

Times are UTC on 2026-11-14.

1. Read A3.pdf and the existing files (compose, prometheus.yml, filebeat.yml, app/main.py, app/metrics.py,
   app/logging_config.py, grpc_server/server.py, the scripts and the packager).
2. App: added `app/replica.py` (REPLICA_ID, delay file), `app/active_requests.py` (ASGI middleware, gauge
   `http_server_active_requests`, injected delay) and one `app.add_middleware(...)` line in `app/main.py`.
   The gRPC server now uses the same delay helper instead of `GRPC_DEMO_DELAY_MS`. The JSON log formatter adds
   `replica` when `REPLICA_ID` is set. Result: `pytest`, 24 passed.
3. Envoy: `scripts/make_envoy_config.py` (modes a-only/rr/weighted/least, `--health`), image `envoyproxy/envoy:v1.34.1`.
   All six variants pass `envoy --mode validate`. The only warnings say `dns_refresh_rate` and
   `dns_failure_refresh_rate` are deprecated; they still work.
4. Compose: six replica services from YAML anchors, plus Envoy. Fixed replica IPs on a `backend` network
   (172.28.10.0/24) so a restarted replica keeps its address. `docker compose config` is valid.
   `up -d --build --remove-orphans` starts every container healthy.
5. Smoke test through Envoy: HTTP 200, `x-served-by: A`, `x-request-id` preserved. gRPC created order 678 on A.
   The Envoy access log shows `replica":"A"`. The `%UPSTREAM_METADATA(replica_info:replica)%` operator works
   in the access log and in a response header.
6. Filebeat problem: Envoy events were rejected by Elasticsearch with a 400 error
   (`object mapping for [interface] ... found a concrete value`), because the ECS template maps `interface` as
   an object. Fixed by renaming the field to `envoy_interface`. Re-tested: 60 Envoy events and 180 replica
   events for 60 gRPC calls.
7. Prometheus: 8 targets up (3 fastapi-app and 3 grpc-service, each with a `replica` label, plus envoy and
   node-exporter).
8. Grafana: `a3-load-balancing` provisioned (19 panels). A copy is in `docs/a3/dashboard.json`.
9. Failure dry run (30 s, 10 rps, not used as evidence): B ejected 7.3 s after `stop` returned and healthy
   again 4.0 s after `start` returned. The client got 25 x 503.
10. Full experiment run: `scripts/run_experiments.ps1`, 13:50-14:13 UTC, log `results/run_experiments.log`.
    All 12 runs completed, and the script restored the normal state (rr, delays 0, B started).
11. Collector fixes, then all 12 runs re-collected from Prometheus and Elasticsearch (data retained):
    (a) a counter series that first appears during a run (B and C had never served CreateOrder before c-rr-grpc)
    is now counted from 0, which fixed c-rr-grpc going from 34.5/32.6/32.9 to 400/400/400;
    (b) the collector now waits longer for Filebeat. Envoy log counts now equal the number of requests sent.
12. Time-range check: Envoy's stdout logger flushes in batches, so the last 78 lines of c-rr-http had a Docker
    `@timestamp` about 6 s after the run. The window is now run end + 15 s. Envoy logs, Prometheus and the client
    agree exactly (c-rr-http 400/400/400; d2-least-delayB-grpc 504/189/507).
13. Log examples saved: `docs/a3/log-example-http.json` (B) and `docs/a3/log-example-grpc.json` (C, a replay of
    order 682, which call 1 created on B).
14. Final checks: pytest 24 passed. All containers up and healthy. Through Envoy: `grpc_traffic.py` gives
    5 OK / 2 INVALID_ARGUMENT / 2 FAILED_PRECONDITION / 1 NOT_FOUND, `grpc_concurrent.py` runs, POST
    /api/orders returns 201 and the UI returns 200. `grpc_traffic.py` and `grpc_concurrent.py` needed a
    `sys.path` line, because running them by file path never found the `app` package (unrelated to A3).
    `package_submission.py` produces `submission/assignment3.zip` (357 files, exclusions PASS).

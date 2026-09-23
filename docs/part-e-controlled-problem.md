# Part E: Controlled order-latency experiment

This experiment tests the existing order path without changing business rules. It delays every fifth `POST /api/orders` by approximately 500 ms, then removes the delay and repeats the same workload. Results and predictions are recorded separately. Do not present a prediction as a measurement.

## Test-only controls and safety

The mechanism is [app/experiment_fault.py](../app/experiment_fault.py), called inside the HTTP timing middleware in [app/main.py](../app/main.py). It uses `await asyncio.sleep(0.5)`, so the event loop can serve other requests while the selected request waits. The measured HTTP duration includes this wait.

Activation requires **both**:

1. `PART_E_TEST_MODE=controlled-local-only` when the app process starts. The normal Compose file does not set it.
2. `/app/experiment-control/latency.txt` containing exactly `ENABLE_500MS_EVERY_5TH`, with a modification time no more than 300 seconds old.

The second file is supplied only through the explicit [experiment Compose override](../docker-compose.experiment.yml). It is read-only inside the container. The checked-in host file contains `DISABLED`. Missing/unreadable files, another token or an expired token disable injection. No client header or HTTP endpoint can enable it. Ordinary `docker compose up` does not load this specially named override.

The counter applies to arrivals at the HTTP middleware, including invalid order-creation requests, but only while enabled. Other routes and methods do not count. An order request seen while disabled resets the cadence to zero. There is one counter per app process: use this project's single Uvicorn worker and no unrelated order traffic during the experiment. In-flight requests already sleeping finish their current wait when the file is disabled.

The runner disables the file before setup, after traffic and in `finally`, including ordinary exceptions and Ctrl+C. Abrupt process termination cannot execute `finally`, so the five-minute expiry is an additional bound. Final teardown recreates the app with the base Compose file, removing the startup opt-in and control mount. Do not deploy the experiment override as production configuration.

Test products and orders are explicitly labelled. Cleanup cancels only the orders created by the runner and restores their reserved stock. It leaves those cancelled records and test product fixtures as an audit trail; it does not delete any user data. The fault itself writes no business state. There is no app restart between the three measured phases, so phase comparisons do not depend on counter resets.

## Repeatable method and exact commands

Run these commands from the repository root in PowerShell. The traffic runner uses only Python's standard library, targets fixed localhost addresses, and requires acknowledgement of test data. Each phase creates a fresh equivalent product, warms up with one order, waits 35 seconds, sends **90 measured orders at scheduled one-second intervals**, waits 35 seconds for final scrapes/shipping, and cancels its own 91 orders outside the measurement window. All measured orders contain one unit priced at 1, with sufficient fixture stock. Only fixture IDs and evidence/request-ID phase labels differ.

Requests are sequential but scheduled relative to a fixed start, not by sleeping one second after each response. A response below one second fits the offered rate of one request/second. If a response takes longer, subsequent starts can fall behind; `schedule_lag_seconds` records this rather than pretending the target rate was achieved. Requests have a ten-second timeout. The script preserves individual latencies, statuses, order IDs and timestamps.

### PHASE A — NORMAL

```powershell
Set-Content experiments/control/latency.txt DISABLED
docker compose -f docker-compose.yml -f docker-compose.experiment.yml up -d --build app
docker compose up -d prometheus node-exporter grafana elasticsearch filebeat kibana
docker compose ps
python scripts/part_e_workload.py --phase normal --run parte-20260922 --ack-test-data
```

Use a new `--run` name on a later repetition. Existing phase evidence directories are never overwritten. Read `normal/client-summary.json`, `normal/prometheus.json`, `normal/targets.json` and `normal/elasticsearch.json` before writing predictions. `metrics-before.txt` and `metrics-after.txt` preserve exact app counter deltas.

### PHASE B — PREDICTION

Before enabling latency, create `experiments/results/<run>/predictions.md` with baseline-informed predictions for mean latency, p95, request rate, errors, CPU and logs. The actual frozen prediction file for this run is linked in the results section below. The fault runner refuses to start without this file and records its SHA-256 hash and lock time in `fault/prediction-lock.json`. It never edits the prediction. Retain this original even if actual results differ.

### PHASE C — FAULT

```powershell
python scripts/part_e_workload.py --phase fault --run parte-20260922 --ack-test-data
```

The same runner writes the enable token immediately before the measured requests. Inspect the existing Grafana dashboard or Explore using the order-specific queries below. Search Kibana for the fault request IDs and `test-only order latency injected` message. The injection message is WARNING with `duration_ms: 500` inside the JSON message; that field is the requested delay, not a measurement of the actual wait. The paired `request completed` message contains the measured server duration.

### PHASE D — ANALYSIS

Compare the saved normal and fault results against the unchanged prediction. Separate client latency (round trip and client overhead), server middleware latency, and histogram-estimated p95. A WARNING injection log is an experiment marker, not an HTTP error. Do not infer CPU causation from one shared-host sample.

### PHASE E — RECOVERY

```powershell
Set-Content experiments/control/latency.txt DISABLED
python scripts/part_e_workload.py --phase recovery --run parte-20260922 --ack-test-data
.\.venv\Scripts\python.exe scripts/part_e_report.py parte-20260922
python scripts/part_e_verify.py parte-20260922
Set-Content experiments/control/latency.txt DISABLED
docker compose -f docker-compose.yml up -d --no-deps --force-recreate app
docker compose exec -T app python -c "import os; print('PART_E_TEST_MODE:', os.getenv('PART_E_TEST_MODE', 'UNSET'))"
```

Recreating with the base file is final teardown, **after** recovery measurements are saved. It resets process counters; never substitute post-teardown raw counters for the saved recovery results.

If the runner is interrupted, write `DISABLED` immediately. Inspect its `cleanup.json`; if a cleanup request failed, cancel only the recorded test order IDs using `PATCH /api/orders/<id>/status` with `{"status":"CANCELLED"}`. A hard kill may interrupt evidence writing and cleanup; inspect `requests.json` and the labelled test fixture before resuming. Never rerun an interrupted phase into the same evidence directory.

## Queries and measurement windows

The workload lasts 90 seconds. Prometheus runs every 15 seconds. For a phase ending at `end`, the runner evaluates each query at **end + 15 seconds**, with a **120-second** lookback (approximately start − 15 seconds to end + 15 seconds). It waits another 35 seconds after traffic before retrieving results so the ending samples are available. Setup/warmup and cleanup are outside that window. Each phase's `manifest.json` saves exact UTC values; set absolute ranges when comparing screenshots.

Prometheus `rate`/`increase` use sampled counters and extrapolation. The rate below averages over the 120-second analysis window, which contains 90 seconds of traffic plus idle margins; it is not expected to equal the client's one-request/second offered rate. Scrape alignment can make phase estimates differ slightly even for the same count. Exact request counts and server means also come from raw before/after counter differences.

Use these PromQL expressions exactly; the runner saves the raw responses with the query text:

```promql
# Mean order request duration, seconds
sum(increase(http_request_duration_seconds_sum{method="POST",route="/api/orders"}[120s]))
/
sum(increase(http_request_duration_seconds_count{method="POST",route="/api/orders"}[120s]))

# Order-specific p95, seconds (bucket estimate)
histogram_quantile(0.95, sum by (le) (increase(http_request_duration_seconds_bucket{method="POST",route="/api/orders"}[120s])))

# Average completed order request rate over the analysis window
sum(rate(http_requests_total{method="POST",route="/api/orders"}[120s]))

# HTTP error percentage; absent error series means zero
100 * (sum(increase(http_requests_total{method="POST",route="/api/orders",status_code=~"4..|5.."}[120s])) or vector(0))
/ clamp_min(sum(increase(http_requests_total{method="POST",route="/api/orders"}[120s])), 1)

# App process CPU, in used CPU cores
rate(process_cpu_seconds_total{job="fastapi-app"}[120s])

# Node Exporter's visible Linux environment CPU percentage
100 * (1 - avg(rate(node_cpu_seconds_total{job="node-exporter",mode="idle"}[120s])))

# Scrape health
up{job=~"fastapi-app|node-exporter"}
```

The existing Grafana **Response latency and p95** panel aggregates all routes. Health and metric scrapes can dilute an order-only delay, so record the order-filtered p95 in Explore as well as any existing panel screenshot. Convert seconds to milliseconds by multiplying by 1000. The client p95 uses the nearest-rank rule, rank `ceil(0.95 * 90) = 86`; it is not histogram interpolation.

Kibana data view: `observable-orders-v3-*`. Set its absolute time range to the phase's workload start/end. Replace the phase name below for normal and recovery:

```kql
request_id : parte-parte-20260922-fault-*
```

```kql
request_id : parte-parte-20260922-fault-* and message : "test-only order latency injected"
```

```kql
request_id : "parte-parte-20260922-fault-005"
```

```kql
request_id : parte-parte-20260922-fault-* and message : "request completed"
```

The repeated `parte` is intentional: the request prefix is `parte-` and the saved run name is `parte-20260922`. Filebeat retains the JSON text in `message`; `duration_ms` is inside that string, not a separately mapped top-level numeric field. Expand the document/message to read it. `request_id`, `severity`, `order_id` and `service.name` are extracted searchable fields. Elasticsearch query bodies and returned sources are saved per phase in the evidence directory.

## Observed results

Run directory: [parte-20260922](../experiments/results/parte-20260922/). [Frozen predictions](../experiments/results/parte-20260922/predictions.md) were locked at **2026-09-22 12:54:04.962653 UTC**, before fault traffic began at 12:54:40.037853 UTC. SHA-256: `c4134fed299a252bdafbc6c66684d68f45e98578c49a742369cc51c9af3c9fb4`. [Phase D analysis](../experiments/results/parte-20260922/analysis-before-recovery.md) was written before recovery began.

All phase manifests record the same workload SHA-256: `8b0f1e7a3040c33189bf20effdaa6d329caef8b2cf91941f0a8b9d15e2101701`. Test fixture IDs differ, but request counts, payload structure, quantity, stock, price, pacing, warmup and scrape waits are identical. No app restart occurred between phases.

### Exact time ranges

All times below are **2026-09-22 UTC**. Add five hours for Asia/Karachi. Use workload ranges for request-prefix log searches. For the tabulated Prometheus values, use an instant query evaluated at the analysis-window end; a rolling panel at another time will legitimately return different values.

| Phase | Workload start | Workload end | 120-second analysis window / query evaluation at right endpoint |
|---|---|---|---|
| NORMAL | 12:50:47.101461 | 12:52:17.101700 | 12:50:32.101700 → 12:52:32.101700 |
| FAULT | 12:54:40.037853 | 12:56:10.038115 | 12:54:25.038115 → 12:56:25.038115 |
| RECOVERY | 12:58:13.113153 | 12:59:43.113366 | 12:57:58.113366 → 12:59:58.113366 |

### Measured numbers

These values come from [summary.json](../experiments/results/parte-20260922/summary.json), with full precision preserved in the phase files. All 90 measured orders succeeded in every phase. Each 90-second workload contained **six samples for each scrape target**, with `up=1` throughout the sampled points; see [verification.json](../experiments/results/parte-20260922/verification.json).

| Measurement | NORMAL | FAULT | RECOVERY |
|---|---:|---:|---:|
| Sent / HTTP 201 / errors | 90 / 90 / 0 | 90 / 90 / 0 | 90 / 90 / 0 |
| Client mean, ms | 35.52 | 135.31 | 34.89 |
| Client nearest-rank p95, ms | 47.42 | 542.95 | 48.82 |
| Client maximum, ms | 49.48 | 555.64 | 67.75 |
| Client achieved requests/s | 0.999997 | 0.999997 | 0.999998 |
| Maximum schedule lag, ms | 2.25 | 1.30 | 24.89 |
| Exact server request-count delta | 90 | 90 | 90 |
| Exact server mean, ms | 17.81 | 119.65 | 18.37 |
| Prometheus mean, seconds | 0.017869 | 0.119653 | 0.018373 |
| Prometheus histogram p95, seconds | 0.024250 | 0.687500 | 0.024574 |
| Prometheus 120-second rate, requests/s | 0.823694 | 0.857208 | 0.857208 |
| Prometheus HTTP errors, percent | 0 | 0 | 0 |
| App process CPU, used cores | 0.005334 | 0.005810 | 0.005429 |
| Visible Linux node CPU, percent | 1.9907 | 2.2385 | 2.0294 |
| Indexed measured documents | 180 | 198 | 180 |
| Request-completion logs | 90 | 90 | 90 |
| Injection WARNING markers | 0 | 18 | 0 |
| Successful test-order cancellations, warmup included | 91 / 91 | 91 / 91 | 91 / 91 |

### Predictions compared with actual results

| Frozen prediction | Actual comparison |
|---|---|
| Mean should rise by about 100 ms | Client mean rose **99.79 ms**; server mean rose **101.84 ms**. This matches the intended 20% × 500 ms wait within normal variation. |
| Client p95 around 530–560 ms | Measured **542.95 ms**, within that interval. |
| Histogram p95 may be 687.5 ms | Measured **687.5 ms**. With 80% below 0.5 s and the delayed 20% in the 0.5–0.75 s bucket, interpolation estimates the 95th percentile at 0.6875 s. It does not mean a measured request actually took that long. |
| Rate stays near 1 request/s | All phases achieved approximately **1 client request/s**. The roughly 500 ms delay fits the one-second schedule. Differences in the sampled 120-second rate are not a throughput improvement caused by delay. |
| No new HTTP errors or stock rejections | **90/90 HTTP 201** in each phase and **0% measured HTTP errors**. The injection WARNING is separate from request outcome. |
| No large CPU spike from sleep | App CPU remained about **0.0053–0.0058 cores**; node CPU about **2%**. The small differences do not establish causation on a shared host. |
| 18 injection markers, exactly every fifth request | All **18** IDs matched 005, 010, ..., 090; Elasticsearch returned the expected **198** fault events. |
| Recovery returns near baseline with no markers | Client mean **34.89 ms**, p95 **48.82 ms**, and **0** injection markers, versus normal 35.52/47.42 ms. Recovery maximum and scheduling lag were higher than normal; these modest outliers do not resemble the repeated half-second fault pattern. |

The technical cause is a wait inside the HTTP measurement interval before normal order handling. It adds wall-clock duration while yielding the event loop, without intentionally changing stock rules, response codes or CPU work. It affected 18 of 90 orders. At this offered load it did not cause a growing queue, timeout or failed sale. Those outcomes at higher traffic were not tested.

For the Instagram seller, roughly one in five submissions feels about half a second slower even though the order succeeds. That inconsistency can reduce confidence and invite repeated clicks; duplicate submissions were not tested, so no duplicate-order result is claimed. The recovery results show that removing the wait restores normal responsiveness under this same workload.

### Recovery, validation and remaining manual evidence

The [read-only verification script](../scripts/part_e_verify.py) passed all checks: identical workload hashes, unchanged prediction hash, exact cadence, 90 measured server requests per phase, all expected indexed documents, six healthy scrapes per target per phase, and cleanup. Test products **8, 9 and 10** each ended with **0 reserved / 91 available** units. All **273** test orders, including three warmups, were cancelled; their records remain labelled as experiment data.

Final teardown used the base Compose configuration. [Recorded final state](../experiments/results/parte-20260922/final-disabled-state.txt):

```text
PART_E_TEST_MODE: UNSET
armed: False
control_mount_exists: False
```

The host control file also says `DISABLED`, `/health` returned `ok`, and captured Filebeat logs contained no `Cannot index`, `status=400` or `dropping event` messages during the experiment interval. The full application test suite passed **13 tests** (two pre-existing dependency deprecation warnings). The three new tests cover default-off behavior even with an enabled file, cadence/route scoping/disable/expiry, and a real 500 ms delay included in the histogram while orders still succeed.

**Backend experiment and recovery: VERIFIED. Grafana visual observation/screenshots: NOT COLLECTED. Kibana Discover observation/screenshots: NOT COLLECTED.** Browser inventory returned no available browser. Grafana health and the Kibana `observable-orders-v3-*` data view with `@timestamp` were checked through HTTP, but those checks are not substitutes for observing the UI. Elasticsearch log queries were actually run and saved. Collect the historical screenshots below manually; no need to re-enable the fault just to query saved data.

Actual fault request `parte-parte-20260922-fault-005` has these three Elasticsearch events in the [saved returned documents](../experiments/results/parte-20260922/fault/example-request-005.json):

```json
{"duration_ms":500,"message":"test-only order latency injected","request_id":"parte-parte-20260922-fault-005","service":{"name":"instagram-order-desk"},"severity":"WARNING","timestamp":"2026-09-22T12:54:44.047207+00:00"}
{"message":"order created","order_id":120,"request_id":"parte-parte-20260922-fault-005","service":{"name":"instagram-order-desk"},"severity":"INFO","timestamp":"2026-09-22T12:54:44.562820+00:00"}
{"duration_ms":519.71,"message":"request completed","method":"POST","path":"/api/orders","request_id":"parte-parte-20260922-fault-005","service":{"name":"instagram-order-desk"},"severity":"INFO","status_code":201,"timestamp":"2026-09-22T12:54:44.563229+00:00"}
```

This is a successful order with a measured server duration of **519.71 ms**, not a rejected order. The 500 in the first event is the injection setting. The underlying Elasticsearch `_source.message` contains each JSON line as a string; the block above shows those decoded message values.

## EXPERIMENT EVIDENCE CHECKLIST

For each phase, save the following screenshots with the phase name and absolute time range visible. UI screenshots remain manual unless explicitly verified in the results section.

| Evidence | NORMAL | FAULT | RECOVERY |
|---|---|---|---|
| Configuration | Control file says DISABLED | Explicit opt-in and active token during traffic | DISABLED; final startup gate UNSET after teardown |
| Grafana latency | Order-filtered mean and p95 in Explore; existing latency panel | Same queries/panel, same range length and units | Same queries/panel after multiple scrapes |
| Grafana throughput/errors | Order request rate and HTTP error percentage | Same panels/queries | Same panels/queries |
| CPU | App process CPU and Node Exporter CPU with labels | Same queries, distinguish sleep from CPU work | Same queries |
| Prometheus targets | App and Node Exporter UP | Both UP | Both UP |
| Kibana Discover | Request-prefix search; expand request-completion duration | Expand request 005 showing injection, completion duration and successful order; injection count search | Request-prefix search; normal completion duration and zero injection markers |
| Workload output | Client summary and cleanup success | Same | Same |

Record these numbers separately for **NORMAL**, **FAULT**, **RECOVERY**: start/end UTC; number sent/successful/failed; client mean/p95/max milliseconds; achieved client requests/second and maximum schedule lag; exact server request count and mean; Prometheus mean/p95 seconds, 120-second request rate and error percentage; process CPU cores and node CPU percentage; indexed event count, request-completion count and injection count; successful cleanup count. Preserve raw files, not only screenshots. Use `NOT COLLECTED` for missing values rather than substituting predictions.

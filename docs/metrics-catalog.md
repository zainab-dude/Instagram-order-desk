# Metrics catalog

All eight application/business metric definitions are in [app/metrics.py](../app/metrics.py). Recording sites below refer to functions in [app/main.py](../app/main.py). Dashboard expressions are from [observable-orders.json](../grafana/dashboards/observable-orders.json). When using Prometheus directly, substitute `5m` for `$__rate_interval`, for example `rate(metric[5m])`.

## Application and business metrics

| Metric | Purpose / type / unit | Application labels | Where/how recorded | Grafana query | Chart meaning |
|---|---|---|---|---|---|
| `http_requests_total` | Traffic and failed responses; Counter; requests | `method`, normalized `route`, `status_code` | `record_http_metrics`: increments after each response; uncaught exceptions now increment status 500 before rethrowing | `sum by (route) (rate(http_requests_total[$__rate_interval]))` | Requests per second by route; HTTP error panel separately computes 4xx/5xx percentage |
| `http_request_duration_seconds` | Response latency; Histogram; seconds | `method`, normalized `route` | `record_http_metrics`: observes elapsed `perf_counter()` duration, including the controlled wait and uncaught failures | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[$__rate_interval])))` | Estimated p95 across requests observed in the rate window; average companion query is sum rate divided by count rate |
| `orders_created_total` | Accepted orders; Counter; orders | None | `add_order`: `.inc()` after `Store.create_order` commits | `orders_created_total`; rate panel: `rate(orders_created_total[$__rate_interval])` | Current process total and creation speed; not SQLite lifetime total |
| `orders_completed_total` | Fulfilled orders; Counter; orders | None | `update_order_status`: increment after successful transition to COMPLETED | `orders_completed_total` | Successful completions since process start |
| `orders_cancelled_total` | Cancelled orders; Counter; orders | None | `update_order_status`: increment after successful transition to CANCELLED | `orders_cancelled_total` | Cancellations since process start |
| `orders_rejected_total` | Business-rule rejection; Counter; attempts | None | `add_order` catches `BusinessRuleError` and increments; schema-validation 422 is instead covered by HTTP metrics | `orders_rejected_total` | Rejected creation attempts such as insufficient stock |
| `pending_orders` | Seller backlog; Gauge; orders | None | `update_pending_orders(store)` calls `.set(store.count_orders("PENDING"))` at startup, successful creation and status change | `pending_orders` | Current pending orders in SQLite; rises/falls and is reconstructed at startup |
| `order_processing_seconds` | Time to completion/cancellation; Summary; seconds | `terminal_status` (COMPLETED/CANCELLED) | `update_order_status`: `.observe(processing_seconds(order))` on successful terminal transition | `sum by (terminal_status) (rate(order_processing_seconds_sum[$__rate_interval])) / sum by (terminal_status) (rate(order_processing_seconds_count[$__rate_interval]))` | Mean lifecycle duration for orders reaching each terminal status within the window; not HTTP latency |

The HTTP error chart is:

```promql
100 * (sum(rate(http_requests_total{status_code=~"4..|5.."}[$__rate_interval])) or vector(0)) / clamp_min(sum(rate(http_requests_total[$__rate_interval])), 1e-9)
```

The average HTTP latency chart is:

```promql
sum(rate(http_request_duration_seconds_sum[$__rate_interval])) / sum(rate(http_request_duration_seconds_count[$__rate_interval]))
```

Counters accumulate until process restart; `rate` handles resets and reports per-second change. A Gauge is a current state. Histograms maintain cumulative bucket counts (additional `le` label), a sum and a count. A Summary here maintains a sum and count without client-side quantiles. Python Summary does not provide p95; the Histogram does. No terminal events means the Summary average is undefined, so generate terminal events before expecting a panel value.

Grafana computes `$__rate_interval` using datasource/range/resolution settings; it is not necessarily the entire dashboard range. Inspect the expanded query. The audit deliberately replaced it with **5m** for every recorded backend query. Part E instead used an explicitly recorded **120-second** window. A histogram p95 is interpolated within buckets, unlike the client experiment's exact nearest-rank percentile.

Lifecycle duration uses SQLite's UTC creation timestamp (second precision), so short synthetic lifecycles can include up to roughly one second of timestamp rounding. The business meaning is time from creation to a terminal state, not just the duration of the status-changing HTTP request.

IDs belong in logs: `request_id`, `order_id`, customer references and arbitrary URL parameters are not labels on production custom metrics. Dynamic routes normalize numeric IDs, and unknown paths become `unmatched`. Prometheus adds `job` and `instance` on ingestion.

## Infrastructure metrics

Node Exporter supplies these from Linux counters/filesystems, not our Python code. [prometheus.yml](../prometheus.yml) scrapes `node-exporter:9100` every 15 seconds. The named environment is **Docker Desktop Linux/WSL2**, as visible through the exporter namespace and `/host:ro` mount. The network interface can be container/namespace-specific; do not claim total Windows traffic.

| Metrics | Purpose / type / unit | Relevant source labels | Grafana expression / interpretation |
|---|---|---|---|
| `node_cpu_seconds_total` | CPU time; Counter; seconds | `cpu`, `mode` | `100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{job="node-exporter",mode="idle"}[$__rate_interval])))`: percentage busy across visible cores |
| `node_memory_MemAvailable_bytes`, `node_memory_MemTotal_bytes` | Memory; Gauges; bytes | Target labels | `100 * (1 - node_memory_MemAvailable_bytes{job="node-exporter"} / node_memory_MemTotal_bytes{job="node-exporter"})`: percentage unavailable for new work |
| `node_filesystem_avail_bytes`, `node_filesystem_size_bytes` | Filesystem capacity; Gauges; bytes | `device`, `fstype`, `mountpoint` | `100 * (1 - node_filesystem_avail_bytes{job="node-exporter",fstype="ext4",mountpoint="/mnt/docker-desktop-disk"} / node_filesystem_size_bytes{job="node-exporter",fstype="ext4",mountpoint="/mnt/docker-desktop-disk"})`: space used on the verified Docker Desktop disk |
| `node_network_receive_bytes_total`, `node_network_transmit_bytes_total` | Traffic volume; Counters; bytes | `device` | `sum by (device) (rate(node_network_receive_bytes_total{job="node-exporter",device!~"lo"}[$__rate_interval]))` and the corresponding transmit expression: bytes/second per non-loopback interface |

Node Exporter exposes many additional families by default. They are not all dashboard requirements or custom application metrics. The catalog above covers the infrastructure signals explicitly used by this project.

## Automatic client-library metrics and isolated demo

These were also observed in [live exposition](audit-evidence/metrics-live.txt); they are collected by the Python client automatically, not incremented by business routes:

| Family | Type / unit / labels | Meaning and query |
|---|---|---|
| `process_cpu_seconds_total` | Counter; CPU seconds; no app labels | Process collector reads process CPU; Part E uses `rate(process_cpu_seconds_total{job="fastapi-app"}[120s])` in used cores |
| `process_virtual_memory_bytes`, `process_resident_memory_bytes` | Gauges; bytes; none | Virtual/resident memory; direct queries by metric name; no dedicated project panel |
| `process_start_time_seconds` | Gauge; Unix seconds; none | Process start timestamp; direct query; no dedicated panel |
| `process_open_fds`, `process_max_fds` | Gauges; file descriptors; none | Open/maximum descriptors; direct query; no dedicated panel |
| `python_info` | Gauge value 1; information; version/implementation labels | Runtime version info; direct query; no dedicated panel |
| `python_gc_objects_collected_total`, `python_gc_objects_uncollectable_total`, `python_gc_collections_total` | Counters; objects/collections; `generation` | GC callbacks maintain totals; query `rate(<metric>[5m])`; no dedicated panel |
| Counter/Histogram/Summary `_created` companions | Gauges; Unix seconds; inherit family's labels | Library records creation time; not business counts; no dedicated panel |
| `demo_requests_total` | Counter; requests; `request_id` in first version, none in second | Separate local exporter only; increments once per accepted synthetic request. `count(demo_requests_total)` in test Prometheus measures series count |

## Actual audit observation and project-specific exploration

At **2026-09-23 08:08:16 UTC**, [saved query results](audit-evidence/live-observability.json) returned: created 60, completed 30, cancelled 30, rejected 6, pending 16 (including pre-existing orders); mean HTTP latency 0.013542 s; p95 0.024756 s; Summary means COMPLETED 1.545785 s and CANCELLED 1.522652 s. These are real responses using a 5-minute rate window, not invented dashboard screenshots.

Project-specific exploration pairs pending backlog with time to terminal status: a rising pending count means unfinished seller work, while long completion lifecycles suggest fulfilment delay even if HTTP latency is low. The synthetic run exercised both terminal outcomes and yielded comparable means; it does not measure real human fulfilment time. **The student must personally explain this choice, its limitation and what they explored, and credit assistance.** Technical evidence does not establish personal authorship or understanding.

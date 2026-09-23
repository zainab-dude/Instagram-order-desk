# Observable Instagram Order & Inventory Management System

## Problem, intended users and solution

Small Instagram sellers often receive orders in direct messages and track stock manually. This can cause overselling, missed orders and uncertainty about fulfilment. This local order desk lets a seller record a non-sensitive reference, reserve inventory and follow an order through packing, shipping and completion.

FastAPI handles validation and business rules; SQLite transactions store products and orders; a browser interface provides the seller workflow. The system supports products, variants, prices, stock updates, multi-item orders through the API, stock validation, cancellation and fulfilment transitions. It does not connect to Instagram, send messages, process payments or provide production authentication. Use synthetic references, not customer names, contact details or copied messages.

Read the [final requirement audit](docs/final-assignment-audit.md) and [short A–E report](docs/assignment-report.md). The report includes the current dashboard and target screenshots; saved backend results and any remaining visual limitations are identified clearly.

## Architecture

```mermaid
flowchart LR
  Browser[Seller Browser] <-->|HTTP :8000| App[FastAPI]
  App <-->|local file I/O| DB[(SQLite / app-data)]
  App -->|metrics response| Prom[Prometheus :9090]
  Node[Node Exporter :9100] -->|metrics response| Prom
  Prom -.->|GET /metrics every 15s| App
  Prom -.->|GET /metrics every 15s| Node
  Prom -->|query results| Graf[Grafana :3000]
  Graf -.->|PromQL over HTTP| Prom
  App -->|JSON stdout| Docker[Docker log files]
  Docker -->|file reads| Beat[Filebeat]
  Beat -->|HTTP bulk :9200| ES[(Elasticsearch)]
  ES -->|search results| Kib[Kibana :5601]
  Kib -.->|HTTP search| ES
```

Solid response arrows show data flow; dotted arrows show pull requests. [Part D](docs/part-d-system-design.md) explains responsibilities, storage, design choices, component failures and one actual metric/log journey. Node Exporter measures the **Docker Desktop Linux/WSL2 environment visible to its container**, not all native Windows activity or FastAPI-only resource usage.

## Prerequisites and installation

- Docker Desktop running in Linux-container mode; on Windows its WSL2 backend must be available.
- Docker Compose v2-compatible commands (`docker compose`) and internet access for initial downloads.
- Free ports 8000, 9090, 3000, 9200 and 5601; isolated cardinality tests also use 8010 and 9091.
- Python 3.10+ for scripts/tests. Audit environment: host Python 3.14; app container Python 3.12.
- Enough Docker memory for the stack; Elasticsearch alone has a configured 512 MiB JVM heap.

PowerShell commands below run from the project root. No virtual-environment activation is required:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Wait for health checks. Filebeat and Node Exporter have no Compose health checks: verify the Filebeat output connection and Prometheus target respectively. Tables are created automatically. This is a local HTTP teaching deployment with Elasticsearch security disabled; it is not configured for public hosting.

For application-only local execution, first stop any container using port 8000:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Local execution uses `data/orders.db`. Docker uses `/app/data/orders.db` in `app-data`; these are separate databases. Use full Compose for Docker/Filebeat observability.

## Service URLs and access

| Service | URL | Use |
|---|---|---|
| Seller interface | http://localhost:8000/ | Inventory and orders |
| API documentation | http://localhost:8000/docs | Interactive endpoint reference |
| Health / metrics | http://localhost:8000/health and http://localhost:8000/metrics | Health JSON and Prometheus text |
| Prometheus | http://localhost:9090/query | PromQL; target status at `/targets` |
| Grafana | http://localhost:3000/ | **Observable Orders → Observable Instagram Orders** dashboard |
| Elasticsearch | http://localhost:9200/ | HTTP API |
| Kibana | http://localhost:5601/ | Discover log search |
| Node Exporter | `http://node-exporter:9100/metrics` inside Compose | Port not published to host |
| Cardinality exporter / Prometheus | http://localhost:8010/metrics and http://localhost:9091/query | Separate explicitly started test project |

Grafana datasource/dashboard files are provisioned from `grafana/`. A fresh volume uses initial login `admin` / `admin` and asks for a password change. An existing volume retains its password: use your existing credentials. The audit did not reset or bypass authentication. Direct dashboard: `http://localhost:3000/d/observable-orders/observable-instagram-orders`.

Kibana's current environment contains **Observable Orders Logs**, data view ID `observable-orders-v3`, pattern `observable-orders-v3-*`, time field `@timestamp`. **On a fresh volume**, generate application traffic, then use **Stack Management → Data Views → Create data view** with that pattern and time field. Compose does not automatically create the data view. Use [saved KQL queries](docs/kibana-queries.kql) in Discover.

## Use the application

1. Add a product with a name, optional variant, nonnegative price and stock.
2. Submit an order with a non-sensitive reference and positive quantity. Insufficient stock is rejected without creating an order.
3. New orders are **PENDING** and reserve inventory. Available stock is physical stock minus reservations.
4. Follow **PENDING → PACKED → SHIPPED → COMPLETED**. Packing deducts physical stock and releases reservations. Invalid skips are rejected.
5. Cancel PENDING orders to release reservations; cancelling PACKED/SHIPPED restores deducted stock. COMPLETED and CANCELLED are final.
6. Update physical stock, keeping it at least as large as current reservations. The UI's sold count is derived from PACKED, SHIPPED and COMPLETED orders.

Routes: GET/POST `/api/products`, PATCH `/api/products/{id}/stock`, GET/POST `/api/orders`, PATCH `/api/orders/{id}/status`. The API accepts multiple order items; the browser form currently selects one item per submission.

## Normal traffic, Prometheus and Grafana

```powershell
Set-Content experiments/control/latency.txt DISABLED
docker compose -f docker-compose.yml up -d --no-deps app
docker compose exec -T app python -c "from app.experiment_fault import OrderLatencyFault; print('fault armed:', OrderLatencyFault().armed)"
python scripts/normal_traffic.py --count 60 --interval 1
```

The normal runner creates its own labelled fixture, sends 60 accepted orders, alternates completion/cancellation, and deliberately makes six insufficient-stock attempts. It runs for over a minute, allowing several 15-second scrapes, then restocks only its fixture. Completed/cancelled test records remain. Results go to `docs/audit-evidence/normal-<UTC timestamp>/`. It never activates a fault.

In Prometheus check `up{job="fastapi-app"}` and `up{job="node-exporter"}` equal 1. Try:

```promql
orders_created_total
pending_orders
sum by (route) (rate(http_requests_total[5m]))
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
sum by (terminal_status) (rate(order_processing_seconds_sum[5m])) / sum by (terminal_status) (rate(order_processing_seconds_count[5m]))
```

Run these as separate expressions. [The metric catalog](docs/metrics-catalog.md) gives every custom metric's purpose, type, unit, labels, recording code, Grafana expression and chart interpretation. The dashboard includes Counter, Gauge, Histogram and **Order lifecycle average (Summary)** panels. Python Summary supplies sum/count rather than quantiles; the Histogram supplies p95. Grafana's `$__rate_interval` depends on range/resolution; inspect its expanded query for the exact window. Choose a historical absolute range for saved experiments, not today's “Last 15 minutes”.

## Logs and Kibana

The application emits JSON with timestamp, object-shaped `service.name`, severity, message and request ID, plus relevant IDs, transitions and durations. It does not intentionally log request bodies, customer references, product names, secrets or full exception messages. Do not put personal data in `X-Request-ID`.

Filebeat unwraps Docker logs, attaches metadata, filters `container.name=observable-orders-app`, decodes into temporary `json`, copies searchable fields and drops that temporary object. Uvicorn access lines from the same container are also admitted and can have JSON-decoding-error fields. The existing `message` remains JSON text: the current copy processor does not replace it. Application `timestamp` stays inside that text; top-level `@timestamp` is Docker capture time.

```powershell
docker compose logs --no-color --tail 50 app
docker compose logs --no-color --tail 50 filebeat
docker compose exec -T filebeat filebeat test config --strict.perms=false
docker compose exec -T filebeat filebeat test output --strict.perms=false
```

Select **Observable Orders Logs** in Discover and enter one query at a time:

```kql
request_id : "pipeline-proof-20260922171843"
order_id : 20
severity : "WARNING" and message : "order rejected"
severity : "ERROR"
service.name : "instagram-order-desk"
```

The saved proof occurred **2026-09-22 12:18:43 UTC / 17:18:43 Asia/Karachi**. For fresh traffic use its saved request prefix. `request_id` is a keyword already; do not append `.keyword`. Historical indexing failures were caused by scalar `service` conflicting with its object mapping; the current formatter emits `service: {name: ...}`. Do not create another pipeline version to work around an unexplained error.

## Storage, retention and restarts

| Data | Persistent location | Behavior |
|---|---|---|
| Orders/products | `app-data:/app/data` | Survives container replacement; volume deletion removes it |
| Metric history | `prometheus-data:/prometheus` | Survives replacement; main Compose does not override Prometheus's default retention |
| Grafana settings | `grafana-data:/var/lib/grafana` | Datasource/dashboard also provisioned from files |
| Indexed logs and Kibana saved objects | `elasticsearch-data:/usr/share/elasticsearch/data` | No age-deletion policy observed for v3; indexed logs stay until deleted or storage is removed |
| Filebeat offsets | `filebeat-data-v3:/usr/share/filebeat/data` | Remembers harvesting position; not a log archive |
| Kibana local runtime data | `kibana-data:/usr/share/kibana/data` | Data views/dashboard saved objects primarily live in Elasticsearch |
| Docker raw logs | Engine `/var/lib/docker/containers` | Same-container restart preserves files; removal/recreation can remove them. Audit found `json-file` with no rotation options |

Named volumes are inside Docker's Linux storage, outside this source folder; names normally have project prefix `assig1_`. No automatic Docker size/age rotation is configured for the inspected app container. No v3 Elasticsearch ILM or data-stream retention policy was observed. Therefore there is no configured age at which indexed application logs are automatically deleted. Filebeat retries transient output failures, but permanent mapping errors can drop events. Its registry cannot recover removed source files. Indexed copies are independent of raw Docker logs. Persistence is not a backup or high-availability guarantee.

## Latency experiment

[Part E](docs/part-e-controlled-problem.md) contains the actual normal/fault/recovery results, immutable prediction file, time ranges, PromQL and KQL. The fault needs explicit experiment startup configuration AND a fresh local token, and expires after five minutes. Ordinary Compose does not enable it.

Use a new run name, keep the workload unchanged and freeze predictions before the fault:

```powershell
Set-Content experiments/control/latency.txt DISABLED
docker compose -f docker-compose.yml -f docker-compose.experiment.yml up -d --build app
python scripts/part_e_workload.py --phase normal --run my-new-run --ack-test-data
# NOW write experiments/results/my-new-run/predictions.md from baseline results.
python scripts/part_e_workload.py --phase fault --run my-new-run --ack-test-data
# Record comparison/analysis before recovery.
python scripts/part_e_workload.py --phase recovery --run my-new-run --ack-test-data
.\.venv\Scripts\python.exe scripts/part_e_report.py my-new-run
python scripts/part_e_verify.py my-new-run
Set-Content experiments/control/latency.txt DISABLED
docker compose -f docker-compose.yml up -d --no-deps --force-recreate app
```

No unrelated order traffic should run during measurement. Do not restart the app between measured phases. The runner disables the token in `finally` and cancels its own test orders; final recreation removes the startup opt-in only after recovery evidence is saved.

## Cardinality experiment

This uses its own exporter, registry, network and Prometheus. Exactly 100 distinct IDs are sent per version. Only the exporter restarts between versions, preserving test history. [The report](docs/cardinality-experiment.md) records **100 → 1** series, historical evidence and screenshot steps.

```powershell
$env:CARDINALITY_MODE='request-id'
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml up -d --build --force-recreate exporter
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml up -d prometheus
python experiments/cardinality/run.py --mode request-id --run my-cardinality-run
$env:CARDINALITY_MODE='no-label'
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml up -d --no-deps --force-recreate exporter
python experiments/cardinality/run.py --mode no-label --run my-cardinality-run
python experiments/cardinality/verify.py my-cardinality-run
Remove-Item Env:CARDINALITY_MODE
```

Use `count(demo_requests_total)` in **test Prometheus on 9091** after a successful scrape. `sum(demo_requests_total)` is 100 in both versions. Do not increase the cap or attempt a crash. Removing labels does not erase stored historical samples.

## Tests and configuration checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
docker compose run --rm --no-deps --volume ./tests:/app/tests:ro app python -m pytest -q -p no:cacheprovider
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.experiment.yml config --quiet
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml config --quiet
docker compose exec -T prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec -T filebeat filebeat test config --strict.perms=false
docker compose exec -T filebeat filebeat test output --strict.perms=false
python experiments/cardinality/verify.py cardinality-20260923
```

If Node is installed, run `node tests/test_ui.cjs`. The audit executed the same JavaScript regression using Kibana's bundled Node, without installing packages. It checks generated markup, not a rendered browser. After normal traffic, `python scripts/audit_observability.py` captures service health, all dashboard queries with a 5-minute window and actual Elasticsearch searches. A protected Grafana API returning 401 is recorded as such, not bypassed.

## Stop and safely clean up

```powershell
Set-Content experiments/control/latency.txt DISABLED
docker compose stop
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml stop
```

`stop` preserves containers/volumes. `start` restarts existing containers with their existing environment; recreate the app with the base Compose file if an experiment configuration may remain. `docker compose down` removes containers/network and keeps named volumes, but raw container logs may disappear. The separate project's equivalent uses `-p cardinality-demo -f experiments/cardinality/compose.yml down`.

For an intentional complete reset **only after saving evidence/backups**, adding `-v` to the appropriate `down` command deletes that project's declared volumes. This destroys orders and monitoring history and is **not necessary for submission cleanup**. Never use global Docker prune to prepare this assignment. Removing local `data/orders.db` affects only the non-Docker database.

## Safe submission packaging

Do not zip the entire workspace. Downloaded `.venv` packages and runtime databases are present; `.gitignore` does not filter normal ZIP tools. This workspace has no `.git` metadata, so tracked-file checks are unavailable.

```powershell
Set-Content experiments/control/latency.txt DISABLED
python scripts/package_submission.py
```

Submit `submission/assignment1.zip`, not the parent directory. The packager uses explicit source/evidence roots and file types, excludes dependency trees, caches, databases, secrets files, archives and volume dumps, and reopens the ZIP to validate exclusions and integrity. `submission/manifest.json` records included paths, sizes and SHA-256 values. Raw JSON/text experiment evidence is intentionally included; downloaded packages and Docker volumes are not. No working data is deleted.

Add screenshots under `docs/screenshots/`, review [credits and assistance disclosure](docs/credits.md), and regenerate the ZIP after updates. The report uses Markdown/Mermaid; view it in a renderer supporting Mermaid or export to the instructor's required format. Submission channel/deadline and identification requirements were not supplied in the original specification.

## Troubleshooting

| Problem | Check/action |
|---|---|
| Docker engine pipe missing | Start Docker Desktop, verify Linux/WSL2 mode, run `docker compose ps` |
| Port in use | Stop the duplicate process/container; do not run two apps on 8000 |
| Elastic services starting | Inspect `docker compose logs --tail 50 elasticsearch kibana`; allow startup time and enough memory |
| Grafana login fails | Use credentials retained in `grafana-data`; defaults apply only to a fresh volume |
| Empty rate/Summary panel | Generate traffic and terminal events, wait multiple scrapes and select the right time range. No terminal events means the average is undefined |
| Summary panel missing | Confirm dashboard JSON has panel 14; wait for provisioning or restart Grafana |
| Disk chart empty on another host | Inspect `node_filesystem_size_bytes` labels. The supplied panel uses the verified Docker Desktop ext4 mount `/mnt/docker-desktop-disk`, not a universal path |
| No Kibana data view | Create `observable-orders-v3-*` with `@timestamp` after traffic |
| Historical event missing | Use its exact date/time range and `request_id`, not `request_id.keyword` |
| Docker logs but no ES document | Validate Filebeat output and indexing errors; check `container.name` filtering and object-shaped `service` |
| Uvicorn JSON parse error | Access lines are plain text; structured app events are separate JSON lines |
| Unexpected fault latency | Write DISABLED and recreate app with base Compose; verify `OrderLatencyFault().armed` is false |
| Cardinality metric absent on 9090 | Query isolated Prometheus on 9091 after its scrape |
| Experiment directory exists | Use a new run name; preserve old evidence/predictions |
| Pytest temporary-directory denial | Use a fresh writable `--basetemp` directory or grant the test process temp access |

Audit warnings include two host dependency deprecations and a bundled Grafana `table` plugin duplicate-registration message. Health and dashboard provisioning succeeded; rendered UI behavior still needs the manual check in the audit. These warnings are not falsely reported as either test failures or proof of UI success.

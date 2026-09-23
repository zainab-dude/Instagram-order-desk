# Milestone 10: Bounded cardinality experiment

**Observed result: 100 current `demo_requests_total` series with a `request_id` label; 1 current series after removing that label.** Exactly 100 successful synthetic requests were sent per version, using the same IDs `cardinality-001` through `cardinality-100`. No million-request workload or attempt to crash Prometheus was performed.

## Isolation and implementation

Everything is under [experiments/cardinality](../experiments/cardinality/). The production application, its metrics definitions, main Compose file and main Prometheus configuration were not changed for this milestone.

- [exporter.py](../experiments/cardinality/exporter.py) is a separate HTTP test application with its own `CollectorRegistry`. It does not create real orders or open SQLite. It accepts at most 100 distinct valid request IDs per process and rejects duplicates. GET health checks and scrapes do not increment the counter.
- [compose.yml](../experiments/cardinality/compose.yml) starts the explicit `cardinality-demo` project, separate network and `cardinality-demo_cardinality-data` volume. It reuses the repository Dockerfile for Python dependencies but runs the demo exporter instead of FastAPI.
- Only loopback ports **8010** (exporter) and **9091** (test Prometheus) are published. The ordinary Prometheus on 9090 is not used.
- [prometheus.yml](../experiments/cardinality/prometheus.yml) scrapes `exporter:8010/metrics` every **5 seconds** with job `cardinality-demo`. Test data retention is configured to **7 days**. No production scrape job is added.
- [run.py](../experiments/cardinality/run.py) checks the mode and that zero requests have been accepted, sends exactly 100 requests without retries, saves all responses and exposition, and waits for a successful scrape newer than request completion plus the actual expected count. It fails instead of claiming success if that evidence is unavailable within 45 seconds.

The first mode constructs and updates:

```python
counter = Counter("demo_requests_total", "Accepted local demo requests.",
                  ["request_id"], registry=registry)
counter.labels(request_id=rid).inc()
```

The second mode constructs the metric with no application labels and updates:

```python
counter = Counter("demo_requests_total", "Accepted local demo requests.",
                  [], registry=registry)
counter.inc()
```

Both definitions are explicit branches in the same test file. Restarting only the exporter selects the second definition and clears its in-memory counter/registry. Prometheus is not restarted or erased between versions; target `job` and `instance` remain the same.

## What was actually observed

All timestamps below are **2026-09-23 UTC**; add five hours for Asia/Karachi.

| Evidence | First version: request ID label | Second version: no request ID label |
|---|---|---|
| Request completion time | 07:53:01.722977 | 07:53:20.791266 |
| Successful scrape time | 07:53:04.199754238 | 07:53:24.200270557 |
| Query evaluation time | 07:53:04.806 | 07:53:24.895 |
| Accepted requests | 100 | 100 |
| `count(demo_requests_total)` | **100** | **1** |
| `sum(demo_requests_total)` | **100** | **100** |
| Individual counter values | 100 series, each value 1 | 1 series, value 100 |
| Target health | UP; no scrape error | UP; no scrape error |

Raw evidence: [first count](../experiments/cardinality/results/cardinality-20260923/request-id/count.json), [second count](../experiments/cardinality/results/cardinality-20260923/no-label/count.json), and [verification](../experiments/cardinality/results/cardinality-20260923/verification.json). Each phase folder also contains `requests.json`, `metrics.txt`, `series.json`, `sum.json`, `targets.json` and `manifest.json`.

The actual count response values were `[1790149984.806, "100"]` and `[1790150004.895, "1"]`. The difference is series count, not number of requests: both versions counted the same 100 requests.

First-version exposition included these distinct lines (excerpt from the saved file):

```text
demo_requests_total{request_id="cardinality-001"} 1.0
demo_requests_total{request_id="cardinality-002"} 1.0
```

Second-version exposition was:

```text
demo_requests_total 100.0
```

Prometheus adds `job="cardinality-demo"` and `instance="exporter:8010"` to both versions. Removing the application label does not remove these scrape labels. The Python client also exposes `demo_requests_created`; the required query counts only the exact `demo_requests_total` metric, not every metric in the exporter or Prometheus.

This run sent the 100 requests as a bounded burst and recorded the post-scrape result. It demonstrates 100 distinct series versus one; it does not claim measurements at intermediate counts of 10 or 50.

## Why the number of series grows

A **time series** is a sequence of timestamped values identified by a metric name and the complete set of label values. **Cardinality** here means the number of distinct such series for the selected metric. Changing `request_id` changes that identity even if every value is `1`. Repeated scrapes append samples to each series; they do not create a new identity just because time passed. [Prometheus data model](https://prometheus.io/docs/concepts/data_model/).

In this single-target experiment, 100 distinct ID values produced 100 label sets and therefore 100 `demo_requests_total` series. With the label removed, all 100 requests incremented the same series. Other varying labels or additional targets can create further combinations, so “one series” is specific to this test's single target.

Each series needs bookkeeping and samples. More label sets mean more exporter-side counter objects, Prometheus in-memory series/index state, stored samples, scrape payload, ingestion work and query processing. A broad aggregation must examine more series. High cardinality can therefore increase memory, storage and processing costs even when the final dashboard shows just one summed number. This experiment measured series counts, not RAM bytes, disk bytes or query slowdowns. [Prometheus instrumentation guidance](https://prometheus.io/docs/practices/instrumentation/).

At **one million unique requests**, retaining a unique `request_id` child for each request would create roughly **one million `demo_requests_total` series** on one target. Removing the label would leave one series with counter value one million. This is an extrapolation, not an observed load test. In this implementation labelled children remain exposed until restart, so scrapes would repeatedly sample previously created children too; new requests keep growing the set. Companion metrics and other label dimensions can add cost. There is no universal bytes-per-series figure established by this run.

Request IDs belong in this application's **logs** for event correlation: one ID can connect a submitted request, its order event and its completion message. Metrics should answer aggregate questions using bounded dimensions such as method, normalized route and status code. A separate metric series per request adds little value to those aggregates. Logs still cost storage and indexing work, but they preserve event-level detail without turning every ID into a persistent metric label combination.

## Why history did not disappear

Changing the exporter changes what future scrapes see; it does not rewrite already stored samples. When a subsequent successful scrape omits the old label sets, Prometheus marks those series stale, so they cease appearing in current instant queries. Historical queries can still access the earlier samples while retained. A transition can briefly show older data before a fresh scrape/staleness handling completes, which is why the runner waits for actual evidence. [Prometheus staleness behavior](https://prometheus.io/docs/prometheus/latest/querying/basics/#staleness).

We verified this after version two:

- A historical `count(demo_requests_total)` evaluated at **1790149984.806** still returned **100**: [historical-count.json](../experiments/cardinality/results/cardinality-20260923/no-label/historical-count.json).
- The series API over the before/after interval returned **101 distinct label sets**: the 100 old labelled series plus the new unlabelled series: [retained-series.json](../experiments/cardinality/results/cardinality-20260923/no-label/retained-series.json).
- The second version's current instant count was **1**, not 101. Historical inventory and current active query results answer different questions.

The test's persistent TSDB volume was preserved. Stopping/restarting the exporter or Prometheus does not delete that volume. Configured retention eventually removes old stored data; a label change is not a deletion command. No history was deliberately deleted in this experiment.

## CARDINALITY EVIDENCE CHECKLIST

### Exact commands for repeating the experiment

Run from the repository root in PowerShell. Use a **new run name** when repeating: the script refuses to overwrite evidence. These commands recreate only the test exporter and leave the main application stack untouched. Keep test Prometheus running between versions.

```powershell
# First version: explicit local project, request_id label
$env:CARDINALITY_MODE='request-id'
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml up -d --build --force-recreate exporter
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml up -d prometheus
python experiments/cardinality/run.py --mode request-id --run cardinality-NEW

# Second version: restart exporter, remove request_id, preserve the same TSDB
$env:CARDINALITY_MODE='no-label'
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml up -d --no-deps --force-recreate exporter
python experiments/cardinality/run.py --mode no-label --run cardinality-NEW
python experiments/cardinality/verify.py cardinality-NEW
Remove-Item Env:CARDINALITY_MODE
```

The performed run name was `cardinality-20260923`. These request-generation commands deliberately send no more than 100 requests per version. Do not loop the generator or increase the cap for the report.

For saved evidence validation without generating requests:

```powershell
python experiments/cardinality/verify.py cardinality-20260923
```

### Exact PromQL and screenshots

Open the **test** Prometheus at `http://localhost:9091/query` and Targets at `http://localhost:9091/targets`. Browser automation was unavailable, so **screenshots are NOT COLLECTED**; the HTTP query results above are verified. Collect these manually:

1. **Before:** Table view showing this historical query returns **100**:

   ```promql
   count(demo_requests_total @ 1790149984.806)
   ```

2. **Before labels:** Table view showing multiple request IDs, each with counter value **1**:

   ```promql
   demo_requests_total @ 1790149984.806
   ```

3. **After:** Table view showing **1**, followed by the no-request-ID series with value **100**:

   ```promql
   count(demo_requests_total @ 1790150004.895)
   demo_requests_total @ 1790150004.895
   ```

   Run these as separate queries. The following totals should both show **100**:

   ```promql
   sum(demo_requests_total @ 1790149984.806)
   sum(demo_requests_total @ 1790150004.895)
   ```

4. **Current comparison while the test exporter runs:**

   ```promql
   count(demo_requests_total)
   up{job="cardinality-demo"}
   ```

   In the verified second-version state these are **1** and **1**. If the exporter has been stopped, do not substitute a later empty current result for the historical measurement.

5. **Transition graph:** Graph `count(demo_requests_total)` over **2026-09-23 07:52:55–07:53:35 UTC** (12:52:55–12:53:35 Asia/Karachi), with a step of about 1 second. Include timestamps and query in the screenshot; any restart gap is part of the evidence.

6. **Scrape proof:** Targets showing `cardinality-demo`, `exporter:8010`, health UP, and five-second interval. Preserve both phase `targets.json` files because a current screenshot alone cannot prove the past scrape times.

7. **History proof:** Show the before query still returning 100 after the change, alongside the saved series API inventory of **101** retained label sets. Keep both `requests.json` files showing exactly 100 accepted distinct IDs and `verification.json` with all checks true.

All requested numbers have been collected. Only screenshots remain manual. The test services are left running in **no-label** mode for inspection; production metrics have not been changed. To stop the test services after collecting screenshots, without deleting evidence/history:

```powershell
docker compose -p cardinality-demo -f experiments/cardinality/compose.yml stop
```

Later, start only the test Prometheus with `docker compose -p cardinality-demo -f experiments/cardinality/compose.yml start prometheus` to inspect retained historical data without restarting a labelled exporter. Do not remove the test volume before finishing the report.

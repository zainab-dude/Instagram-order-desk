# Final report cross-check against Assignment 1

Source: [original assignment PDF](../Assignment-1.pdf), checked using its [page-labelled extraction](audit-evidence/assignment-extracted.txt). Deliverable: [A–E report](assignment-report.md). This is a report/evidence cross-check, not a new execution of the application or experiments. Measurements come from the linked saved results. Current Grafana, Prometheus, and Kibana overview screenshots are stored in [screenshots](screenshots/).

**Covered** means the report supplies the explanation and available supporting evidence. **Partial** means the implementation or backend evidence exists but a specific visual or personal-observation requirement is not fully represented. The [runtime audit](final-assignment-audit.md) gives the fuller test-by-test classification.

| Assignment requirement | Report location and support | Cross-check |
|---|---|---|
| A: State a problem | Part A: stock availability and fulfilment for small sellers | Covered |
| State intended users and solution | Part A: seller browser/FastAPI/SQLite | Covered |
| Build a working solution | Part A: saved tests and 60-order normal workload, scoped honestly | Covered |
| Explain functionality and how to try it | Part A: lifecycle, startup, URLs, normal traffic; README details | Covered |
| B: Set up Prometheus | Part B: scrape sources, interval, storage and access | Covered; saved target/query evidence |
| Set up Grafana | Part B: provisioned dashboard and access | Setup supported; display evidence needed |
| Application metrics, including response times/failures | Part B: HTTP Histogram/Counter and queries | Covered |
| Business metrics, such as orders/cancellations | Part B: created/completed/cancelled/rejected/backlog | Covered |
| All four metric types and data in Grafana | Part B: Counter/Gauge/Histogram/Summary table and queries | Types/data supported; four-type screenshots needed |
| p95 or p99 and time window | Part B: actual p95, 5m audit vs Grafana variable window; Part E: 120s | Covered; screenshot grouped above |
| Python Summary average, Histogram percentile | Part B: lifecycle sum/count mean versus HTTP histogram p95 | Covered |
| Metric table: purpose, type, unit, labels, where/how recorded | Part B: six-column application table, infrastructure table | Covered |
| Grafana query and chart explanation | Part B: actual dashboard expressions and meanings | Covered |
| Important app/business behavior beyond classroom examples | Part B: stock rejection, backlog and lifecycle | Covered |
| At least one metric/chart explored yourself | Part B: backlog/lifecycle comparison with actual results | Student's own exploration evidence needed |
| Node Exporter CPU/memory/disk/network collected by Prometheus | Part B: metrics/types/source labels/queries and observed values | Covered |
| Display infrastructure in Grafana; name machine | Part B: Docker Desktop Linux/WSL2 scope, not all Windows | Machine named; four infrastructure screenshots needed |
| C: App JSON → Docker → Filebeat → Elasticsearch → Kibana | Parts C/D: actual event and transformations | Through Elasticsearch supported; Kibana display needed |
| What, why and where logged | Part C: formatter and application recording sites | Covered |
| Filebeat collection and searchable fields | Part C: outer unwrap, metadata/filter, decode/copy/drop | Covered |
| Where logs live, persistence and deletion | Part C: Docker, registry, ES volume, no configured age deletion | Covered |
| Search request/error in Kibana | Part C: data view, UTC range, request/order/severity/rejection KQL | Queries/backend hits supported; Discover evidence needed |
| Time/service/severity/message/request ID | Part C: original JSON and selected actual stored fields | Covered |
| Original log, stored fields and working search | Part C: sample, source link and exact successful ES counts | Final Kibana screenshot needed |
| Explain plain-text parsing if used | Part C: Uvicorn access lines distinguished from structured business logs | Covered; no structured parsing claim for access text |
| Never log secrets/personal data | Part C: intended field exclusions, regression evidence and ID restriction | Covered within tested policy; no universal privacy guarantee claimed |
| D: Architecture with app/dependencies/monitoring | Part D: Mermaid diagram | Covered; render diagram in final submission format |
| Arrows and component responsibilities/communication | Part D: initiator direction, HTTP ports, file reads/writes | Covered |
| Data storage and design choices | Part D: component table and actual persistent volumes | Covered |
| What happens when each component stops | Part D: failure effects for browser/app/DB/Docker/collectors/stores/UIs | Covered as design reasoning, not fabricated outage tests |
| Explain tools/choices and note unknowns | Part D: choices, deployment limits and personal-unknowns placeholder | Personal understanding/unknowns statement needed |
| Follow metric: code → collection/storage → Grafana | Part D: source increment, actual 5.0/5, query/panel | Final matched panel screenshot needed |
| Follow log: code → parsing/storage → Kibana | Parts C/D: order 20 and its actual format changes/query | Final Discover screenshot needed |
| Values, queries and format changes | Parts B/C/D: concrete samples and transformations | Covered |
| E1: Repeatable normal test | Part E: 90 requests, one-second scheduling, saved normal results | Covered |
| Predictions before fault | Part E: original frozen file, lock timestamp and predictions | Covered; not rewritten after results |
| Introduce problem; show actual metrics/log changes | Part E: observed table and actual delayed request | Backend results supported; comparison chart/search screenshots needed |
| Explain technical cause and user impact | Part E: 20% × 500ms, bucket interpolation, seller wait | Covered; no invented failed sales |
| Remove problem, repeat workload and show recovery | Part E: recovery figures, removed gate and cleanup | Covered; recovery screenshot grouped above |
| Commands/time ranges/queries/results | Part E: command sequence, UTC intervals, evaluation times, PromQL/KQL | Covered; detailed reproducibility procedure linked |
| Several scrapes in each phase | Part E: six healthy scrapes per target per phase | Covered by saved verifier evidence |
| Local reversible fault | Part E: two activation gates, expiry, disable and base-config teardown | Covered |
| E2: Local test counter with request_id, stop at 100 unique IDs | Part E: separate registry/project/Prometheus and bounded workload | Covered |
| Show series growth using count | Part E: post-scrape count 100; no invented intermediate measurements | Covered; screenshot placeholder included |
| Remove label, restart, repeat, compare after scrape | Part E: commands and timestamped comparison 100 → 1 | Covered |
| Explain larger-scale cost and why IDs belong in logs | Part E: memory/storage/query cost; million-ID extrapolation labelled | Covered |
| Do not crash Prometheus | Part E: bounded workload and healthy scrapes | Covered; no destructive stress claim |
| Old history does not disappear immediately | Part E: stale current series, retained count 100, inventory 101, retention | Covered |
| Submit code/config/dashboard/Kibana queries | Repository, dashboard JSON and `docs/kibana-queries.kql` | Present; source/evidence packager excludes runtime data |
| README start/use/test/safe cleanup | Linked README | Present |
| Short A–E report with metric list/diagram/explanations/results | Report has exactly the five requested top-level headings | Present; evidence placeholders remain |
| Credit reused code/sources/assistance under course policy | Report links `credits.md` and flags personal review | Policy/source review needed |
| Exclude downloaded dependencies/data volumes | `scripts/package_submission.py`, ignore files and previous archive validation | Use generated package, not whole-folder ZIP |

Logstash is optional; slides are not required. The specification supplies no final submission date/channel, so none is invented. Food-order examples are illustrations, not additional required features.

## Remaining evidence to supply

1. **Grafana:** actual Counter, Gauge, Histogram/p95, Summary and CPU/memory/disk/network panels with time ranges and expanded queries; a matched Orders created metric-journey observation.
2. **Kibana:** proof request/order and rejected-order Discover results, expanded fields, selected data view and time range.
3. **Latency experiment:** normal/fault/recovery charts and log searches for the recorded UTC windows, including the actual delayed request. Preserve the original prediction file.
4. **Cardinality:** test-Prometheus count 100/1, sums 100, labels, target health and retained historical result screenshots before retention expires.
5. **Personal contribution:** describe the exploration you actually performed, any concepts still unclear, and confirm sources/assistance disclosure under course policy.

Insert the evidence at the report's placeholders, render Mermaid in the required submission format, and regenerate the source package if submitting it. Existing backend measurements need not be fabricated or replaced merely because screenshots are missing.

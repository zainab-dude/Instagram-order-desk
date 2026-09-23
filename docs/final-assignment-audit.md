# Final Assignment 1 audit

Audit date: **2026-09-23**. Source: the complete three-page [original assignment](../Assignment-1.pdf), reread via [page-labelled text extraction](audit-evidence/assignment-extracted.txt). This checklist splits the specification into explicit, testable requirements; counts below are checklist counts, not the proposed marks. Examples in the handout are illustrative, not additional mandatory features. Logstash and slides are not required.

Status meanings:

- **✅ COMPLETE AND VERIFIED** — actual test/output, recorded experiment, or inspected document satisfies the requirement. A source file alone is not runtime proof.
- **⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE** — implementation/technical material exists, but required displayed results or the student's own explanation remain unverified.
- **❌ MISSING / INCORRECT** — requirement absent or demonstrably wrong. Defects discovered and fixed below are not silently counted as pre-existing success.

## A — Project: 4/4 verified

| ID | Original requirement | Status | Evidence / limits |
|---|---|---|---|
| A1 | Choose and state a problem | ✅ COMPLETE AND VERIFIED | README and report identify manual order tracking and overselling; application directly enforces inventory constraints |
| A2 | State intended users and solution | ✅ COMPLETE AND VERIFIED | Small Instagram sellers; browser/FastAPI/SQLite order desk; scope and non-goals explicitly documented |
| A3 | Build a working solution | ✅ COMPLETE AND VERIFIED | 15 Python tests; live normal traffic accepted 60 orders, completed 30, cancelled 30 and rejected six insufficient-stock attempts; HTTP home/health succeeded. Browser rendering is not claimed |
| A4 | Explain functionality and how to try it | ✅ COMPLETE AND VERIFIED | Rewritten README has prerequisites, install/start commands, URLs, lifecycle rules, APIs and a normal traffic runner that was actually executed |

## B — Metrics: 9/12 verified

| ID | Original requirement | Status | Evidence / remaining action |
|---|---|---|---|
| B1 | Set up Prometheus | ✅ COMPLETE AND VERIFIED | Main config passes promtool; both targets UP; live queries returned data |
| B2 | Set up Grafana | ✅ COMPLETE AND VERIFIED | Grafana health/database OK; provisioning logs show dashboard provisioning finished; datasource/dashboard files inspected. This verifies setup, not display |
| B3 | Track application metrics, including response times and failed requests | ✅ COMPLETE AND VERIFIED | HTTP Histogram/Counter queried live; 4xx traffic observed; added regression proves uncaught 500 increments request and duration metrics |
| B4 | Track business metrics | ✅ COMPLETE AND VERIFIED | Created/completed/cancelled/rejected counters and pending gauge exercised by tests and live traffic |
| B5 | Use all four metric types AND show their data in Grafana | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Counter/Gauge/Histogram/Summary data exists. Missing Summary panel was fixed; its real query returned averages. Capture rendered panels for all four types |
| B6 | Show p95 or p99 and explain window; Python Summary average + Histogram percentiles | ✅ COMPLETE AND VERIFIED | Backend p95 observed 0.024756 s at the audit's explicit 5m window; Part E p95 observations also saved. Catalog explains variable Grafana window, Summary average and histogram interpolation. Grafana screenshot is tracked in B5 |
| B7 | Metric table: purpose, type, unit, labels, recording location/how | ✅ COMPLETE AND VERIFIED | [Metric catalog](metrics-catalog.md) covers every custom family and the infrastructure signals; definitions checked against code and live exposition |
| B8 | Grafana query and chart explanation for metrics | ✅ COMPLETE AND VERIFIED | Catalog matches dashboard expressions; all 16 expressions across 14 panels returned data via Prometheus in the saved audit |
| B9 | Cover important application/business behavior beyond generic examples | ✅ COMPLETE AND VERIFIED | Stock-related rejection, pending backlog, cancellation/completion and lifecycle Summary cover seller-specific behavior; normal traffic exercised them |
| B10 | At least one metric/chart explored yourself | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Backlog vs terminal lifecycle exploration is documented with real observations. Student must explain their own exploration and credit assistance; code cannot establish personal understanding/authorship |
| B11 | Node Exporter CPU, memory, disk and network collected by Prometheus | ✅ COMPLETE AND VERIFIED | All four kinds returned nonempty live query results; target UP; effective disk labels recorded |
| B12 | Display infrastructure in Grafana and name measured machine | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Dashboard/query data exists; Docker Desktop Linux/WSL2 scope clearly named. Capture all four rendered infrastructure panels |

## C — Logs: 6/8 verified

| ID | Original requirement | Status | Evidence / remaining action |
|---|---|---|---|
| C1 | Set up Filebeat → Elasticsearch → Kibana pipeline | ✅ COMPLETE AND VERIFIED | Filebeat config/output test passes; fresh JSON events indexed; Elasticsearch and Kibana healthy; data view exists. Search UI proof tracked separately |
| C2 | Explain what is logged, why and where in code | ✅ COMPLETE AND VERIFIED | Report/README identify business outcomes, requests, failures, formatter/context and recording functions |
| C3 | Explain collection and transformation into searchable fields | ✅ COMPLETE AND VERIFIED | Part D compares original Docker wrapper, processor configuration and actual stored `_source`; accurately notes retained JSON message and discarded temporary object |
| C4 | Explain storage, restart survival and deletion of old logs | ✅ COMPLETE AND VERIFIED | Docker inspection: json-file with no rotation options; ES settings/lifecycle show no configured v3 age retention. README distinguishes container log loss, registry offsets, persistent indexed data, saved objects and volume deletion |
| C5 | Explain and demonstrate searching for a request/error in Kibana | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | KQL and time ranges supplied; backend searches and data view verified. Open Discover and capture actual request/rejected-order results |
| C6 | Include time, service, severity, message and request ID where relevant | ✅ COMPLETE AND VERIFIED | Actual app JSON and ES documents include required information; logger/request-ID tests pass |
| C7 | Show original log, stored fields and a working search; explain plain-text parsing if used | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Original and stored documents plus successful ES searches are saved. Final Kibana search screenshot remains missing. Uvicorn plain-text handling is explained, not misrepresented as parsed application JSON |
| C8 | Never log secrets/personal data | ✅ COMPLETE AND VERIFIED | Intended structured fields exclude bodies, customer references/names and exception text; tests prove sensitive reference/exception strings are absent. Users are instructed not to place personal data in correlation IDs. This is scoped verification of the implemented logging policy, not a guarantee about arbitrary user-supplied IDs |

## D — System design: 4/7 verified

| ID | Original requirement | Status | Evidence / remaining action |
|---|---|---|---|
| D1 | Diagram includes app, dependencies and monitoring tools | ✅ COMPLETE AND VERIFIED | Detailed Mermaid architecture includes browser, app, SQLite, Prometheus, Grafana, Node Exporter, Docker logs, Filebeat, Elasticsearch, Kibana and volumes |
| D2 | Arrows/notes explain roles and communication | ✅ COMPLETE AND VERIFIED | Pull requests distinguished from data responses; HTTP ports, SQLite file I/O and log harvesting annotated |
| D3 | Explain data storage and design choices | ✅ COMPLETE AND VERIFIED | Per-component table and volume table; SQLite business source of truth versus telemetry stores |
| D4 | Explain failure of each component | ✅ COMPLETE AND VERIFIED | Part D describes app/database/engine/collector/storage/UI failures and recovery limits |
| D5 | Be able to explain tools/choices; note what is not understood | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Explanations, limitations and instructor Q&A provided; student's personal understanding must be demonstrated, not inferred from generated prose |
| D6 | Follow one metric from code through storage to Grafana display, with values/queries | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Source, increment, exposition 5.0, Prometheus result 5, query and panel definition recorded; displayed panel not observed |
| D7 | Follow one log through parsing/storage to Kibana, showing values/query/format changes | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Full order-20 journey documented and backend verified; final Discover display remains manual |

## E — Experiments: 11/12 verified

| ID | Original requirement | Status | Evidence / remaining action |
|---|---|---|---|
| E1 | Repeatable test and normal behavior | ✅ COMPLETE AND VERIFIED | Saved 90-request baseline; same script hash in all three phases |
| E2 | Predict metrics/log changes before fault | ✅ COMPLETE AND VERIFIED | Frozen prediction file and pre-fault lock timestamp/hash; re-verification confirms unchanged |
| E3 | Introduce problem and show actual changes, comparing response charts/logs | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | Mean/p95, counters, CPU and real indexed injection/completion events verified. Historical Grafana and Discover screenshots not collected |
| E4 | Explain technical cause and user effect | ✅ COMPLETE AND VERIFIED | 20% × 500 ms predicts ~100 ms mean increase; observed +99.79 ms. Seller waits explained without inventing failed sales |
| E5 | Remove fault, repeat same workload and demonstrate recovery | ✅ COMPLETE AND VERIFIED | Recovery 34.89 ms client mean, 48.82 ms p95, zero injection markers, 90 successes; default gate off and cleanup verified |
| E6 | Commands, time ranges, queries/results and several scrapes per stage | ✅ COMPLETE AND VERIFIED | Part E has exact UTC windows and queries; six healthy samples per target per phase rechecked against retained Prometheus data |
| E7 | Local and reversible fault | ✅ COMPLETE AND VERIFIED | Dual opt-in, expiry, finally-disable and base-config teardown; no production activation by default; tests validate gate/cadence/expiry |
| E8 | Local test counter with request_id; stop at 100 unique IDs | ✅ COMPLETE AND VERIFIED | Separate exporter/registry/Prometheus; saved transcript exactly 100 distinct IDs; server rejects duplicates/out-of-range IDs |
| E9 | Demonstrate series growth with count | ✅ COMPLETE AND VERIFIED | Actual post-scrape count 100, not inferred from source |
| E10 | Remove label, restart test app, repeat and compare after scrape | ✅ COMPLETE AND VERIFIED | Same 100 IDs, new exporter mode, same TSDB; post-scrape count 1; sums 100 in both versions |
| E11 | Explain large-scale costs and why IDs belong in logs | ✅ COMPLETE AND VERIFIED | Time-series/cardinality definitions, memory/storage/processing, million-ID extrapolation and event correlation explained; no million-request run claimed |
| E12 | Do not crash Prometheus; explain retained history | ✅ COMPLETE AND VERIFIED | Bounded run, healthy scrapes, historical count still 100 and retained inventory 101; no history deletion |

## Submission requirements (separate from A–E counts)

| Requirement | Status | Evidence / action |
|---|---|---|
| Code/configuration including Grafana dashboards and Kibana queries | ✅ COMPLETE AND VERIFIED | Source/config files plus `docs/kibana-queries.kql`, all included by packager |
| README covering start, use, test and safe cleanup | ✅ COMPLETE AND VERIFIED | Rewritten current operating guide; actual startup/traffic/test/config commands executed where noted |
| Short A–E report with metric list, diagrams, explanations and results | ✅ COMPLETE AND VERIFIED | `docs/assignment-report.md`, metric catalog and linked detailed evidence; it discloses outstanding UI evidence |
| Credit reused code, sources and assistance under course policy | ⚠️ IMPLEMENTED BUT NEEDS MANUAL EVIDENCE | `docs/credits.md` explicitly records Codex assistance and references. Student must add any other actual reuse and confirm required policy wording |
| Exclude downloaded dependencies and data volumes | ✅ COMPLETE AND VERIFIED | Source/evidence allowlist ZIP, excluded dependency/cache/database/archive trees, archive integrity check, per-file manifest; named runtime volumes are outside workspace. Do not submit a hand-made ZIP of the entire folder |

## Bugs and omissions fixed during this audit

1. **Summary had no Grafana panel** — added panel 14 with lifecycle sum/count rate average, explanations and seconds units. Query returned real COMPLETED/CANCELLED values. Display still needs screenshot.
2. **Uncaught 500s bypassed HTTP metrics** — now record failure count and latency before rethrowing; ERROR log includes safe status/duration. Regression test verifies counting and excludes sensitive exception text.
3. **Absent HTTP error series produced an empty error chart** — numerator now falls back to zero. Once request series have enough scrape samples, the denominator clamp handles a zero request rate. Before sufficient samples exist the chart can still be empty.
4. **Stale cancellation could restore packed stock twice** — status update now checks the previously read status and rolls back inventory mutations if another transition won. Deterministic competing-transition regression passes.
5. **User-controlled text was inserted as HTML** — escape product/variant/reference/item names in rendered markup. JavaScript VM test checks all affected display regions and retained controls. This is not a browser screenshot.
6. **README was contradictory/outdated** — corrected lifecycle stock semantics, service access, fresh Kibana data-view setup, actual message shape, saved-object storage and retention. Added metric catalog, short report, credits, normal traffic instructions and safe packaging.

No new end-user product feature, pipeline version, metric label on production requests, or destructive cleanup was introduced. Missing optional Grafana provisioning directories were supplied as empty documented directories; the bundled duplicate `table` plugin message is reported rather than falsely “fixed” by changing unrelated software versions.

## Automated and runtime validation

| Check | Actual outcome |
|---|---|
| Full host Python suite | **15 passed**, two dependency deprecation warnings; [output](audit-evidence/pytest.txt) |
| Full deployed-image Python suite | **15 passed**, same two warnings, in a temporary Python 3.12 app container with read-only tests; [record](audit-evidence/container-tests.txt) |
| UI markup regression using Kibana Node v20.15.1 | **PASS**; [output](audit-evidence/ui-test.txt). Initial source-transfer wrapper failed; corrected wrapper passed |
| Host and app-container `pip check` | **No broken requirements found** |
| Base, latency override and cardinality Compose config | All parsed successfully |
| Main and isolated Prometheus `promtool check config` | Both passed |
| Live metrics `promtool check metrics` | Passed inside Linux. An initial PowerShell pipe changed newlines to CRLF and caused a parser error; the direct Linux pipeline passed without changing app exposition |
| Filebeat `test config` / `test output` | Config OK; DNS/connect/server OK, ES 8.15.3; expected warning that local HTTP has TLS disabled |
| Grafana | Database health OK and dashboard provisioning completed. Unauthenticated dashboard API returned **401**; no login reset/bypass. UI not verified |
| Node Exporter | Target UP; CPU/memory/disk/network results returned |
| Elasticsearch/Kibana | ES responds; Kibana reports available; v3 data view exists; original/fresh request searches succeeded |
| Latency saved evidence | All verifier checks true, including original prediction hash, scrapes, cadence and restored fixture stock |
| Cardinality saved evidence | All 10 verifier checks true |
| Submission | ZIP integrity/exclusion checks and manifest generated; no virtual environment, dependency cache, database, Docker volume or volume backup included |

[Live service/query/search capture](audit-evidence/live-observability.json) was taken at **2026-09-23 08:08:16 UTC**. It records 16 successful expressions across 14 dashboard panels, not Grafana-rendered images. [Compose status](audit-evidence/compose-status.txt), [Docker log options](audit-evidence/docker-log-config.json), [Elasticsearch volume](audit-evidence/elasticsearch-volume.json), and [Grafana logs](audit-evidence/grafana-provisioning.log) provide supporting evidence.

Warnings/limits: no browser available; Grafana dashboard API requires authentication; host dependency deprecations; bundled Grafana duplicate `table` registration warning. These are disclosed, not converted into invented successes. Current tests and saved experiments are not load/scalability/security certification. The final source ZIP is reproducible and safe to prepare without deleting useful evidence or local runtime data.

## FINAL ASSIGNMENT AUDIT

- Part A: **4/4 requirements verified**
- Part B: **9/12 requirements verified**
- Part C: **6/8 requirements verified**
- Part D: **4/7 requirements verified**
- Part E: **11/12 requirements verified**

Across A–E: **34/43 verified, 9 awaiting manual evidence, 0 remaining identified missing/incorrect implementations** after the fixes above. Manual evidence requirements can share screenshots; they are counted separately because the specification uses them in different sections.

## Final manual TODO list

1. **Capture the working interfaces.** In Grafana, sign in with your retained credentials and capture Counter, Gauge, Histogram/p95, Summary and all four infrastructure panels. Use the current normal-traffic window or rerun the normal traffic script, wait scrapes, and include expanded query/window information. In Kibana Discover, show the proof request/order and a rejected-order search, expand a stored document, and include the data view/time range. Also give the seller UI a brief smoke check after the escaping fix. Do not label these verified until you see the actual results.
2. **Capture experiment charts and searches.** Use the exact historical normal/fault/recovery ranges and KQL in Part E; collect before/during/after latency, throughput/error/CPU panels and injection/completion logs. In test Prometheus on 9091, capture the cardinality report's fixed-time count queries (100 → 1), sum 100, labels, target health and retained-history evidence. Backend numbers already exist; do not rerun or alter frozen predictions merely to get screenshots.
3. **Review and own the explanation.** Explain the project's backlog/lifecycle exploration in your own words, rehearse the Part D Q&A, and retain honest limits. Review `docs/credits.md` against your course policy, add any other real sources/reuse and any required name/ID. No assistant can verify your personal understanding or undisclosed policy requirements.
4. **Finalize submission.** Put screenshots in `docs/screenshots/`, link them from the report, render Mermaid diagrams correctly, and use the instructor's required report format. Run `python scripts/package_submission.py` again and inspect `submission/manifest.json`; submit only the generated ZIP (and any separately requested report) through the announced channel by the announced deadline.

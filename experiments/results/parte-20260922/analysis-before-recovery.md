# PHASE D — Analysis recorded before RECOVERY

NORMAL and FAULT are complete; RECOVERY has not been started. The PHASE B predictions are unchanged.

Client mean increased from 35.5203 ms to 135.3134 ms: +99.7931 ms, close to the predicted +100 ms. Exact server mean increased from 17.8098 to 119.6530 ms (+101.8432 ms). Client p95 increased from 47.4209 to 542.9530 ms, inside the predicted 530–560 ms interval. Prometheus p95 rose from 24.25 to 687.5 ms, exactly the predicted coarse-histogram interpolation, not a claim that an individual p95 request took 687.5 ms.

Both phases returned 90 HTTP 201 responses, zero errors, and about one client request per second. Maximum start lag was 2.2546 ms normal and 1.3048 ms fault, so the scheduled workload was maintained. The 120-second Prometheus rates differed (0.823694 vs 0.857208 requests/s); sampling and extrapolation differ from the exact 90-request, 90-second client count. This is not evidence that adding delay improved throughput.

App process CPU stayed low (0.00533364 to 0.00580997 CPU cores). Visible node CPU changed from 1.99067% to 2.23846%. This supports the absence of a large CPU spike; a single trial on a shared Docker Desktop host does not isolate small CPU differences.

Elasticsearch returned 180 normal documents and 198 fault documents. The fault documents include 18 injection markers on precisely requests 005, 010, ..., 090, plus 90 order-created and 90 completion events. The normal phase had zero injection markers. All 91 test orders per phase (warmup included) were successfully cancelled after measurement.

Technical cause: the async half-second wait is inside the request timing interval and before business handling, so one fifth of requests gains approximately 500 ms of wall-clock latency. The event loop is yielded, and each delayed response still fits the one-second request schedule and ten-second timeout. Validation and stock rules are unchanged.

Seller effect: one in five submissions feels about half a second slower and inconsistent, but this experiment did not produce failed orders or reduced completion throughput. At higher offered load, concurrent users or different client timeouts, results could differ; this trial did not test those conditions.

Grafana/Kibana visual observation is NOT VERIFIED because browser inventory was empty. Grafana health and the Kibana data view were checked through HTTP. All latency/log claims above use saved client, application, Prometheus and Elasticsearch evidence, not screenshots. Manual visual evidence remains required.

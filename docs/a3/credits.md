# Assignment 3: credits and reused work

## Reused work
- My own Assignment 1 and Assignment 2 code (FastAPI order desk, gRPC `OrderService`, Prometheus,
  Grafana, Filebeat, Elasticsearch, Kibana). Assignment 3 extends it.

## Documentation consulted
- Envoy documentation, v1.34:
  - Load balancers: round robin, weighted round robin, least request (power of two/N choices, `choice_count`).
  - Health checking: HTTP health checks, `interval`, `timeout`, `unhealthy_threshold`, `healthy_threshold`,
    `no_traffic_interval`, `health_check_config.port_value`, health-check event sink (`event_logger`).
  - HTTP connection manager: `generate_request_id`, `preserve_external_request_id`,
    `always_set_request_id_in_response`; HTTP/2 (`codec_type: HTTP2`) for gRPC.
  - Upstream HTTP protocol options (`explicit_http_config.http2_protocol_options`).
  - Access logging: command operators (`%REQ()%`, `%RESPONSE_CODE%`, `%GRPC_STATUS%`, `%RESPONSE_FLAGS%`,
    `%DURATION%`, `%UPSTREAM_HOST%`, `%UPSTREAM_CLUSTER%`, `%UPSTREAM_METADATA()%`), JSON format.
  - Admin interface: `/clusters`, `/ready`, `/stats/prometheus`.
- Prometheus documentation: `static_configs` target labels, `rate`, `increase`, `histogram_quantile`, HTTP API.
- Filebeat documentation: `add_fields` with `when` conditions, `copy_fields`, `drop_event`.
- Docker Compose documentation: YAML anchors and extension fields (`x-`), static `ipv4_address`, `start_interval`.

## AI assistance
- Claude Code (Anthropic) helped implement the A3 changes under my direction: the Compose replicas, the Envoy
  config generator, the Prometheus and Filebeat changes, the HTTP active-request middleware and delay control,
  the fixed-rate client, the evidence collection scripts, the Grafana dashboard and drafts of the README and
  report. It also ran the experiments. Every number in the report comes from files in `results/`, which hold
  the raw Prometheus and Elasticsearch responses. I reviewed the design decisions and the results.

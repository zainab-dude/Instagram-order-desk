"""Generate envoy/envoy.yaml for Assignment 3 (pure Python, no dependencies).

Usage:
    python scripts/make_envoy_config.py a-only|rr|weighted|least [--health]
    docker compose restart envoy

Modes:
    a-only    HTTP and gRPC go to replica A only (B and C are not Envoy destinations)
    rr        equal-weight round robin over A, B, C
    weighted  round robin with weights A:B:C = 2:1:1
    least     least request (power-of-choices with choice_count 3) over A, B, C
    --health  add active health checks (interval 2s, timeout 1s, unhealthy 3, healthy 2)
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLICAS = ("A", "B", "C")
HEALTH = {"interval": "2s", "timeout": "1s", "unhealthy_threshold": 3, "healthy_threshold": 2}

# Fields of each Envoy JSON access-log line (one line per HTTP request or gRPC call).
ACCESS_LOG_FIELDS = {
    "timestamp": "%START_TIME(%Y-%m-%dT%H:%M:%S.%3fZ)%",
    "service": {"name": "envoy"},
    "request_id": "%REQ(X-REQUEST-ID)%",
    "trace_id": "%REQ(X-REQUEST-ID)%",
    "method": "%REQ(:METHOD)%",
    "path": "%REQ(:PATH)%",
    "response_code": "%RESPONSE_CODE%",
    "grpc_status": "%GRPC_STATUS%",
    "response_flags": "%RESPONSE_FLAGS%",
    "duration_ms": "%DURATION%",
    "upstream_host": "%UPSTREAM_HOST%",
    "upstream_cluster": "%UPSTREAM_CLUSTER%",
    "replica": "%UPSTREAM_METADATA(replica_info:replica)%",
}


def endpoint(kind: str, replica: str, weight: int, health: bool) -> dict:
    host = f"{kind}-{replica.lower()}"
    port = 8000 if kind == "app" else 50051
    ep = {"address": {"socket_address": {"address": host, "port_value": port}}, "hostname": host}
    if health and kind == "grpc":
        ep["health_check_config"] = {"port_value": 8002}  # gRPC replica's metrics port
    return {
        "endpoint": ep,
        "metadata": {"filter_metadata": {"replica_info": {"replica": replica}}},
        "load_balancing_weight": weight,
    }


def health_check(path: str, http1: bool) -> dict:
    check = {"path": path}
    if http1:
        check["codec_client_type"] = "HTTP1"
    return {
        **HEALTH,
        "no_traffic_interval": HEALTH["interval"],
        "http_health_check": check,
        "always_log_health_check_failures": True,
        "event_logger": [{
            "name": "envoy.health_check.event_sink.file",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.health_check.event_sinks.file.v3.HealthCheckEventFileSink",
                "event_log_path": "/dev/stdout",
            },
        }],
    }


def cluster(name: str, kind: str, mode: str, health: bool) -> dict:
    replicas = ("A",) if mode == "a-only" else REPLICAS
    weights = {"A": 2, "B": 1, "C": 1} if mode == "weighted" else {r: 1 for r in REPLICAS}
    c = {
        "name": name,
        "type": "STRICT_DNS",
        "connect_timeout": "1s",
        "dns_lookup_family": "V4_ONLY",
        # Long refresh: membership changes come from health checks, not from DNS.
        "dns_refresh_rate": "300s",
        "dns_failure_refresh_rate": {"base_interval": "1s", "max_interval": "5s"},
        "lb_policy": "LEAST_REQUEST" if mode == "least" else "ROUND_ROBIN",
        "load_assignment": {
            "cluster_name": name,
            "endpoints": [{"lb_endpoints": [endpoint(kind, r, weights[r], health) for r in replicas]}],
        },
    }
    if mode == "least":
        c["least_request_lb_config"] = {"choice_count": 3}
    if kind == "grpc":
        c["typed_extension_protocol_options"] = {
            "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": {
                "@type": "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions",
                "explicit_http_config": {"http2_protocol_options": {}},
            }
        }
    if health:
        c["health_checks"] = [health_check("/health", False) if kind == "app" else health_check("/metrics", True)]
    return c


def listener(name: str, port: int, interface: str, cluster_name: str) -> dict:
    fields = {**ACCESS_LOG_FIELDS, "interface": interface}
    route = {"match": {"prefix": "/"}, "route": {"cluster": cluster_name, "timeout": "15s"}}
    if interface == "grpc":
        route["match"]["grpc"] = {}
    hcm = {
        "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
        "stat_prefix": f"{interface}_ingress",
        "codec_type": "HTTP1" if interface == "http" else "HTTP2",
        "generate_request_id": True,
        "preserve_external_request_id": True,
        "always_set_request_id_in_response": True,
        "route_config": {
            "name": f"{interface}_route",
            "virtual_hosts": [{"name": interface, "domains": ["*"], "routes": [route]}],
            # Lets the test client count per-replica shares from responses as a third source.
            "response_headers_to_add": [{"header": {"key": "x-served-by",
                                                     "value": "%UPSTREAM_METADATA(replica_info:replica)%"}}],
        },
        "http_filters": [{
            "name": "envoy.filters.http.router",
            "typed_config": {"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"},
        }],
        "access_log": [{
            "name": "envoy.access_loggers.stdout",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog",
                "log_format": {"json_format": fields},
            },
        }],
    }
    if interface == "grpc":
        hcm["http2_protocol_options"] = {}
    return {
        "name": name,
        "address": {"socket_address": {"address": "0.0.0.0", "port_value": port}},
        "filter_chains": [{"filters": [{"name": "envoy.filters.network.http_connection_manager", "typed_config": hcm}]}],
    }


def build(mode: str, health: bool) -> dict:
    return {
        "admin": {"address": {"socket_address": {"address": "0.0.0.0", "port_value": 9901}}},
        "static_resources": {
            "listeners": [
                listener("http_listener", 8000, "http", "http_cluster"),
                listener("grpc_listener", 50051, "grpc", "grpc_cluster"),
            ],
            "clusters": [
                cluster("http_cluster", "app", mode, health),
                cluster("grpc_cluster", "grpc", mode, health),
            ],
        },
    }


def to_yaml(value, indent: int = 0) -> str:
    """Minimal YAML emitter; scalars are JSON-encoded, which is valid YAML."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for key, item in value.items():
            k = json.dumps(key) if key.startswith("@") else key
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{k}:\n{to_yaml(item, indent + 1)}")
            else:
                lines.append(f"{pad}{k}: {to_yaml(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            body = to_yaml(item, indent + 1) if isinstance(item, (dict, list)) and item else to_yaml(item)
            if isinstance(item, (dict, list)) and item:
                body = body.lstrip()
            lines.append(f"{pad}- {body}")
        return "\n".join(lines)
    return json.dumps(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["a-only", "rr", "weighted", "least"])
    parser.add_argument("--health", action="store_true", help="enable active health checks")
    parser.add_argument("--out", default=str(ROOT / "envoy" / "envoy.yaml"))
    args = parser.parse_args()
    header = (f"# GENERATED by scripts/make_envoy_config.py {args.mode}{' --health' if args.health else ''}\n"
              "# Do not edit by hand; re-run the script and `docker compose restart envoy`.\n")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + to_yaml(build(args.mode, args.health)) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out} (mode={args.mode}, health={args.health})")


if __name__ == "__main__":
    main()

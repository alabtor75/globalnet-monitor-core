Collector Architecture – GlobalNet Monitor (GNM)

Author: Soufianne Nassibi
Role: Technical Lead – Linux Systems & Large-Scale Monitoring Architect
Website: https://soufianne-nassibi.com

Live Demo: https://gnmradar.ovh/

License: GNU GPL v3.0 (Collector component only)

1. Purpose

The Collector is the execution core of GlobalNet Monitor.

It performs deterministic active checks against configured infrastructure targets and writes structured telemetry into the database layer.

The Collector:

Does not expose HTTP endpoints

Does not perform visualization

Does not implement alerting

Does not perform aggregation

It is a pure execution engine.

2. Execution Model

The Collector operates in cycles.

Each cycle performs:

Configuration loading

Host and service loading

Probe identity resolution

Concurrent execution of checks

Failure classification

Database insertion

Sleep until next interval

Execution frequency is controlled via:

collector.interval_sec

3. Threading & Concurrency

The Collector uses:

ThreadPoolExecutor

Characteristics:

I/O-bound concurrency

One future per service

Blocking operations (DNS, TCP, HTTP, TLS)

Max workers configurable

Configuration:
collector:
  max_workers: 20


Concurrency = min(max_workers, number_of_services)

4. Supported Check Types
Type	Description
ping	ICMP round-trip latency
http	HTTP status & latency
dns	DNS A-record resolution
tcp	TCP port connectivity
ssl_cert	TLS certificate expiration
json_api	HTTP JSON validation

Each check returns:

(status, latency_ms, meta)

5. Status Classification Logic

GNM uses deterministic classification.

Code	Meaning
0	OK
1	WARN
2	CRIT
Hard Failures

Examples:

Connection refused

Timeout

DNS resolution failure

TLS handshake failure

Two-Strike Mechanism

First hard failure → WARN
Second consecutive hard failure → CRIT

This prevents transient spikes from generating critical state.

Counters are:

In-memory

Per service_id

Reset on restart

6. Probe Identity & Region Awareness

Collector determines probe identity via:

Environment variables

Cached geo-IP resolution

Fallback to config region

Stored in meta_json:

probe_region

probe_country

probe_city

probe_public_ip

probe_source

7. Database Interaction

Collector uses:

Connection pooling (DBUtils PooledDB)

Autocommit mode

Retry logic (tenacity)

Exponential backoff

Insert model:

One INSERT per measurement
Append-only
No UPDATE operations

8. Logging Architecture

Logging includes:

Console output

Rotating file logs (10MB, 5 backups)

Structured format

Execution tracing

Log levels:

DEBUG

INFO

WARNING

ERROR

CRITICAL

9. Prometheus (Optional)

Prometheus support is optional.

Activated via:

GNM_PROMETHEUS=1


Exports:

gnm_checks_total

gnm_check_duration_seconds

gnm_cycle_duration_seconds

gnm_collector_uptime_seconds

Disabled by default.

10. Graceful Shutdown

Signals handled:

SIGINT

SIGTERM

Behavior:

Finish current cycle

Stop scheduling

Close cleanly

11. Configuration Dependencies

Required files:

config.yaml

hosts.json

services.json

Collector will fail startup if missing.

12. Failure Scenarios

Collector tolerates:

Individual service failure

Database transient errors (retry)

DNS timeout

HTTP timeout

Collector exits only on:

Fatal configuration error

Persistent DB failure

Unhandled exception

13. Architectural Constraints

Collector does not:

Persist streak counters

Implement alerting

Provide RBAC

Support SNMP traps

Perform log ingestion

It is intentionally minimal and deterministic.

14. Scaling Model

Horizontal scaling:

Multiple collectors

Shared database

Region differentiation

No distributed coordination required.

15. Architectural Positioning

Collector is:

A deterministic active check engine

A backend monitoring executor

A structured telemetry producer

A modular monitoring component

It is not:

A SaaS platform

A complete monitoring suite

An event processing system

Author

Soufianne Nassibi
Technical Lead – Linux Systems & Monitoring Architect

https://soufianne-nassibi.com

https://gnmradar.ovh

© Soufianne Nassibi – GlobalNet Monitor (GNM)

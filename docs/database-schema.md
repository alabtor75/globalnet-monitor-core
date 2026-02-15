Database Schema – GlobalNet Monitor (GNM)

Author: Soufianne Nassibi
Role: Technical Lead – Linux Systems & Large-Scale Monitoring Architect
Website: https://soufianne-nassibi.com

Live Demo: https://gnmradar.ovh/

License: GNU GPL v3.0 (Collector & API components only)

1. Overview

The GlobalNet Monitor (GNM) database layer is responsible for structured telemetry persistence.

GNM follows a deterministic storage model:

One row per executed check

Explicit status classification

Structured JSON metadata

Time-series optimized indexing

The database does not implement:

Alerting logic

Aggregation materialization

Metrics rollups

Event correlation

It stores raw monitoring measurements.

2. Storage Engine Requirements

Supported:

MySQL 5.7+

MariaDB 10.3+

Recommended:

InnoDB storage engine

utf8mb4 charset

UTC timezone

3. Core Table: measurements

This is the only required table for the GNM core engine.

SQL Definition
CREATE TABLE IF NOT EXISTS measurements (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    ts DATETIME NOT NULL,

    region VARCHAR(32) NOT NULL,

    project_id INT NULL,

    target_id VARCHAR(128) NOT NULL,

    host_id VARCHAR(128) NULL,

    type VARCHAR(32) NOT NULL,

    status TINYINT NOT NULL COMMENT '0=OK, 1=WARN, 2=CRIT',

    latency_ms INT NOT NULL,

    meta_json JSON NULL,

    INDEX idx_ts (ts),
    INDEX idx_project (project_id),
    INDEX idx_target (target_id),
    INDEX idx_region (region)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

4. Column Definitions
id

Auto-increment primary key.

Used internally for ordering and uniqueness.

ts

Timestamp in UTC.

Represents the exact execution time of the check.

Used for:

Time-series queries

Historical analysis

Window filtering

region

Probe identifier.

Defines from which geographic region the check was executed.

Used for:

Multi-probe federation

Regional SLA analysis

Geo-comparative monitoring

project_id

Optional logical grouping identifier.

Used for:

Multi-project segmentation

Environment separation

Tenant grouping (basic)

Nullable by design.

target_id

Logical monitoring target identifier.

Represents the monitored entity.

Examples:

api-service-1

edge-router-eu-01

website-prod

host_id

Infrastructure-level identifier.

Maps to an entry in hosts.json.

Allows decoupling between:

Logical target

Physical host

Nullable for non-host-based checks.

type

Monitoring check type.

Possible values:

ping

http

dns

tcp

ssl_cert

json_api

status

Status classification:

Value	Meaning
0	OK
1	WARN
2	CRIT

CRIT is reserved for confirmed hard failures.

latency_ms

Execution duration in milliseconds.

Represents:

ICMP RTT

HTTP response time

DNS resolution duration

TCP connect duration

SSL handshake duration

JSON API validation duration

meta_json

Structured JSON field.

Contains:

Error messages

HTTP status codes

SSL expiration data

DNS records

Slow-level classification

Probe metadata

Debug context

Designed for flexible inspection without schema changes.

5. Index Strategy
idx_ts

Optimizes:

Time window queries

Timeseries extraction

Historical filtering

idx_target

Optimizes:

Latest status per target

Per-target history queries

idx_region

Optimizes:

Multi-probe regional queries

Geo filtering

idx_project

Optimizes:

Project segmentation queries

Environment isolation

6. Data Model Characteristics

The GNM data model is:

Append-only

Stateless

Non-destructive

Deterministic

Each row is immutable after insertion.

No update operations are required by the Collector.

7. Data Retention Strategy

Retention is not enforced at schema level.

Recommended approaches:

Scheduled DELETE with time-based filtering

MySQL partitioning by date

External archiving

Example cleanup:

DELETE FROM measurements
WHERE ts < NOW() - INTERVAL 90 DAY;

8. Optional Advanced Optimizations

For high-scale deployments:

Composite Index
CREATE INDEX idx_target_ts ON measurements (target_id, ts DESC);


Optimizes latest-per-target queries.

Partitioning by Date (Advanced)
PARTITION BY RANGE (TO_DAYS(ts)) (
    PARTITION p2025q1 VALUES LESS THAN (TO_DAYS('2025-04-01')),
    PARTITION p2025q2 VALUES LESS THAN (TO_DAYS('2025-07-01'))
);


Recommended only for large datasets.

9. Schema Scope

This schema is intentionally minimal.

It does not include:

Targets table

Hosts table

Users

Authentication

Alerts

SLAs

GNM focuses strictly on telemetry persistence.

10. Architectural Positioning

The database layer is:

A structured telemetry store

A time-series relational model

A deterministic measurement archive

A backend monitoring persistence engine

It is not a metrics warehouse.
It is not an event processing system.
It is not an observability platform.

It is a monitoring execution datastore.

Author

Soufianne Nassibi
Technical Lead – Linux Systems & Monitoring Architect

https://soufianne-nassibi.com

https://gnmradar.ovh

© Soufianne Nassibi – GlobalNet Monitor (GNM)

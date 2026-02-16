# GlobalNet Monitor (GNM) – Monitoring Engine Core

Author: Soufianne Nassibi  
Technical Lead – Linux Systems & Large-Scale Monitoring Architect  
Website: https://soufianne-nassibi.com  
License: GNU GPL v3.0 (Collector & API layers only)

---

## Project Overview

GlobalNet Monitor (GNM) is a lightweight, infrastructure-agnostic monitoring engine designed for active network supervision at scale.

This repository publishes:

- The Collector engine
- The reference API layer
- The database schema

Both the Collector and API components are licensed under GNU GPL v3.0.

The production dashboard, deployment automation, and commercial extensions are not part of this open-source repository.

---

## Strategic Positioning

GNM is not intended to replace enterprise monitoring solutions.

It demonstrates:

- Distributed monitoring architecture design
- Active-check execution logic
- Resilient failure classification (2-strikes model)
- Structured telemetry persistence
- Region-aware probing (geo-IP detection)
- Backend-driven monitoring architecture

The project reflects real-world experience operating large-scale monitoring infrastructures across thousands of devices and services.

It is a technical showcase of architecture thinking, execution engine design, and monitoring data modeling.

---

## Architecture Model

GNM follows a decoupled monitoring architecture:

1. Collector (active checks engine)
2. Database (structured measurements storage)
3. API layer (data aggregation and exposure)
4. Dashboard (external, optional)

This repository includes layers 1 and 3.

Visualization is intentionally decoupled.

---

## Collector Engine

The Collector performs:

- ICMP (Ping)
- HTTP
- DNS
- TCP
- SSL certificate validation
- JSON API checks

Core principles:

- CRIT only for confirmed hard-down
- WARN for degraded conditions
- Anti false-positive logic (2-strikes confirmation)
- Concurrent execution via thread pool
- Geo-aware probe identification
- Structured JSON metadata storage

It is designed to be simple, predictable, and backend-centric.

---

## API Layer

The API exposes monitoring data for:

- Health endpoints
- Last status per target
- Aggregated metrics
- Time-series extraction
- Region filtering

The API is also GPL v3 licensed.

The frontend layer is intentionally excluded from open-source scope.

---

## Database Schema

Reference MySQL schema:

```sql
CREATE TABLE measurements (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME NOT NULL,
    region VARCHAR(32) NOT NULL,
    project_id INT NULL,
    target_id VARCHAR(128) NOT NULL,
    host_id VARCHAR(128) NULL,
    type VARCHAR(32) NOT NULL,
    status TINYINT NOT NULL,
    latency_ms INT NOT NULL,
    meta_json JSON NULL,
    INDEX idx_ts (ts),
    INDEX idx_project (project_id),
    INDEX idx_target (target_id),
    INDEX idx_region (region)
    
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
Status codes:

0 = OK

1 = WARN (degraded)

2 = CRIT (confirmed failure)

Configuration Model
Required configuration files:

config.yaml

hosts.json

services.json

These are environment-specific and not included in the repository.

Example structure:

region: "EU"

db:
  host: "localhost"
  port: 3306
  user: "gnm_user"
  password: "password"
  database: "gnm"

collector:
  interval_sec: 30
  ping_timeout_sec: 10
  http_timeout_sec: 10
  dns_timeout_sec: 10
  tcp_timeout_sec: 10
  max_workers: 20
License Scope
The following components are licensed under GNU GPL v3.0:

Collector engine

API layer

The following components are NOT covered by this repository:

Production configuration

Deployment scripts

Dashboard UI

Enterprise extensions

Commercial integrations

This separation is intentional.

Why This Project Exists
GNM was designed to:

Demonstrate monitoring engine architecture

Showcase backend observability design

Provide a minimal but robust monitoring core

Remain independent from vendor lock-in

Maintain full control over execution logic

It is a backend-first monitoring system.

Technical Keywords
network monitoring
active checks
distributed monitoring
infrastructure observability
MySQL telemetry storage
Python monitoring engine
concurrent health checks
SSL certificate monitoring
ICMP latency measurement
DNS resolution checks
backend-driven monitoring
monitoring architecture design
infrastructure supervision
geo-aware probing
monitoring API design
## Monitoring Engine

## Monitoring API

## MySQL Telemetry Model

## Observability Architecture

---

## Live Instance (Demo)

Public demonstration instance:  
https://gnmradar.ovh/

This repository contains the core engine (collector + API).  
The dashboard/UI layer is implementation-specific.

---

## Documentation

Detailed documentation is available in the [`/docs`](/alabtor75/globalnet-monitor-core/tree/main/docs) directory:

- **[Installation Guide](docs/INSTALL.md)** - Setup and deployment
- **[Configuration Guide](docs/CONFIG.md)** - Configuration files and options
- **[API Documentation](docs/API.md)** - REST API endpoints
- **[Architecture](docs/ARCHITECTURE.md)** - System design and components
- **[Examples](docs/EXAMPLES.md)** - Configuration examples

---

## Author

Soufianne Nassibi  
Technical Lead – Linux Systems & Monitoring Architect  
https://soufianne-nassibi.com  
https://gnmradar.ovh/

# Configuration Reference – GlobalNet Monitor (GNM)

Author: Soufianne Nassibi  
Role: Technical Lead – Linux Systems & Large-Scale Monitoring Architect  
Website: https://soufianne-nassibi.com  
Live Demo: https://gnmradar.ovh/  
License: GNU GPL v3.0 (Collector & API components only)

---

## 1. Overview

GlobalNet Monitor relies on external configuration files.

These files are environment-specific and are not distributed with production credentials.

The Collector requires:

- config.yaml
- hosts.json
- services.json

The API requires:

- config.yaml (database access)

---

# 2. config.yaml

Main system configuration file.

## 2.1 Structure

```yaml
region: "EU"

db:
  host: "localhost"
  port: 3306
  user: "gnm_user"
  password: "secure_password"
  database: "gnm"
  pool_mincached: 2
  pool_maxcached: 5
  pool_maxconnections: 10

collector:
  interval_sec: 60
  max_workers: 20

  ping_timeout_sec: 5
  http_timeout_sec: 10
  dns_timeout_sec: 5
  tcp_timeout_sec: 5

  thresholds:
    ping_warn_ms: 500
    ping_very_slow_ms: 1500

    http_warn_ms: 3000
    http_very_slow_ms: 8000

    dns_warn_ms: 1500

    tcp_warn_ms: 1500
    tcp_very_slow_ms: 4000

    json_warn_ms: 3000
    json_very_slow_ms: 8000
2.2 Parameter Definitions
region
Fallback region if geo-detection fails.

Type: String
Example: "EU", "NA", "AF"

db section
Defines database connectivity and pooling behavior.

Parameter	Description
host	MySQL server hostname
port	MySQL port
user	Database user
password	Database password
database	Database name
pool_mincached	Minimum pooled connections
pool_maxcached	Maximum idle connections
pool_maxconnections	Maximum total connections
collector section
Parameter	Description
interval_sec	Cycle interval
max_workers	Maximum concurrent threads
*_timeout_sec	Timeout per check type
thresholds	Latency degradation classification
2.3 Validation Rules
interval_sec >= 10 recommended

max_workers >= 1

timeout values must be positive integers

DB credentials must be valid

3. hosts.json
Defines monitored infrastructure hosts.

3.1 Structure
[
  {
    "host_id": "web01",
    "address": "example.com"
  },
  {
    "host_id": "db01",
    "address": "192.168.1.10"
  }
]
3.2 Field Definitions
Field	Description
host_id	Unique logical identifier
address	Hostname or IP address
Constraints:

host_id must be unique

address must be resolvable for applicable checks

4. services.json
Defines monitoring services.

4.1 Structure
[
  {
    "service_id": "web01_ping",
    "host_id": "web01",
    "type": "ping",
    "enabled": true,
    "project_id": 1
  },
  {
    "service_id": "web01_https",
    "host_id": "web01",
    "type": "http",
    "params": {
      "url": "https://example.com"
    }
  }
]
4.2 Required Fields
Field	Required	Description
service_id	Yes	Unique service identifier
host_id	Yes	Reference to hosts.json
type	Yes	Check type
enabled	No	Default true
project_id	No	Logical grouping
4.3 Supported Check Types
ping

http

dns

tcp

ssl_cert

json_api

Each type may require additional params.

5. Configuration Best Practices
Keep credentials outside version control

Validate JSON syntax before restart

Use staging environment before production

Keep service_id stable for time-series continuity

6. Startup Failure Conditions
Collector will refuse startup if:

config.yaml missing

hosts.json missing

services.json missing

Invalid JSON format

DB connection fails

© Soufianne Nassibi – GlobalNet Monitor (GNM)

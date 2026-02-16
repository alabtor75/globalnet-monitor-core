
---

#  `dashboard-design-guide.md`

```markdown
# Dashboard Design Guide – GlobalNet Monitor (GNM)

Author: Soufianne Nassibi  
Role: Technical Lead – Linux Systems & Large-Scale Monitoring Architect  
Website: https://soufianne-nassibi.com  
Live Demo: https://gnmradar.ovh/  
License: GNU GPL v3.0 (Collector & API components only)

---

# 1. Overview

GlobalNet Monitor does not include a built-in dashboard.

Visualization is intentionally decoupled.

Any external UI framework may consume the API.

Examples:

- React
- Vue
- Angular
- Static HTML + JavaScript
- Grafana (via custom adapter)

---

# 2. API Consumption Model

The dashboard consumes REST endpoints.

Typical endpoints:

- /health
- /api/last
- /api/timeseries
- /api/meta/targets

The API is stateless.

---

# 3. Recommended Dashboard Architecture

Frontend → REST API → MySQL

Dashboard must never access the database directly.

---

# 4. Core UI Components

## 4.1 Global Status Overview

Use `/api/last`

Display:

- service_id
- host_id
- status
- latency_ms
- region

Color mapping:

| Status | Color |
|--------|-------|
| 0 | Green |
| 1 | Orange |
| 2 | Red |

---

## 4.2 Per-Target Detail View

Use `/api/timeseries`

Display:

- Latency graph
- Status history
- Region filter

Recommended:

- Rolling 24h window
- Zoomable chart

---

## 4.3 Region Filtering

Use region query parameter.

Allows:

- Multi-probe differentiation
- Geo analysis
- Regional SLA computation

---

# 5. Refresh Strategy

Recommended:

- 10–30 seconds refresh for last status
- 60 seconds refresh for meta endpoints
- Lazy load for timeseries

Avoid excessive polling.

---

# 6. Pagination Handling

For `/api/last`:

Use:

- limit
- offset

Do not request excessive limits.

---

# 7. Performance Considerations

- Cache meta endpoints
- Avoid polling large timeseries continuously
- Use incremental time windows

---

# 8. Status Interpretation

Dashboard should treat:

- WARN as degraded
- CRIT as confirmed failure
- meta_json for detailed diagnostics

Do not reclassify status client-side.

---

# 9. Multi-Probe Visualization

If multiple collectors write to DB:

- Use region column
- Group by region
- Display probe location

---

# 10. Security Recommendations

- Place API behind reverse proxy
- Enable HTTPS
- Add rate limiting
- Restrict CORS if needed

---

# 11. Design Philosophy

GNM dashboard should:

- Remain thin
- Avoid business logic
- Rely on API classification
- Present deterministic state

---

# 12. Extension Possibilities

- SLA calculation layer
- Availability percentage view
- Incident timeline
- Alert manager integration
- Multi-project segregation

---

© Soufianne Nassibi – GlobalNet Monitor (GNM)

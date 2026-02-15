#!/usr/bin/env python3
# GNMRADAR / GlobalNet Monitor (GNM)
# Copyright (C) 2026 Soufianne Nassibi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
GNMRADAR Core – API Backend (Monolith v1)

Author: Soufianne Nassibi
Website: https://soufianne-nassibi.com
Contact: contact@soufianne-nassibi.com
License: GPL-3.0

FastAPI backend aligned with Internet-centric / probe-based collector.

Key principles:
- measurements.region = probe (real viewpoint)
- meta endpoints are descriptive only
- runtime aggregation respects: CRIT = hard down only
"""



from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymysql
import yaml
from dbutils.pooled_db import PooledDB
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

# Prometheus
from prometheus_fastapi_instrumentator import Instrumentator


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

LOG_LEVEL = os.getenv("GNM_API_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gnm_api")


# --------------------------------------------------------------------------- #
# Paths / Config
# --------------------------------------------------------------------------- #

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"
HOSTS_PATH = ROOT_DIR / "config" / "hosts.json"
SERVICES_PATH = ROOT_DIR / "config" / "services.json"
TARGETS_GEO_PATH = ROOT_DIR / "config" / "targets_geo.json"

CFG: Optional[Dict[str, Any]] = None


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_cfg() -> Dict[str, Any]:
    """
    Lazy config load with proper HTTP errors (useful in containers / startup race).
    """
    global CFG
    if CFG is None:
        try:
            CFG = load_config()
        except FileNotFoundError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Invalid config: {e}")
    return CFG


# --------------------------------------------------------------------------- #
# TTL cache helpers (thread-safe)
# --------------------------------------------------------------------------- #

def ttl_cache(ttl_seconds: int):
    """
    Simple TTL cache decorator.
    Thread-safe.
    Suitable for caching file loads (hosts/services/targets_geo).
    """
    def deco(fn):
        lock = threading.Lock()
        state = {"expires": 0.0, "value": None}

        def wrapped():
            now = time.time()
            with lock:
                if now < state["expires"] and state["value"] is not None:
                    return state["value"]
                v = fn()
                state["value"] = v
                state["expires"] = now + ttl_seconds
                return v
        return wrapped
    return deco


@ttl_cache(ttl_seconds=60)
def load_hosts_cached() -> Dict[str, Dict[str, Any]]:
    if not HOSTS_PATH.exists():
        return {}
    with HOSTS_PATH.open(encoding="utf-8") as fh:
        hosts_list = json.load(fh)
    return {h["host_id"]: h for h in hosts_list if h.get("host_id")}


@ttl_cache(ttl_seconds=60)
def load_services_cached() -> List[Dict[str, Any]]:
    if not SERVICES_PATH.exists():
        return []
    with SERVICES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@ttl_cache(ttl_seconds=60)
def load_targets_geo_cached() -> List[Dict[str, Any]]:
    if not TARGETS_GEO_PATH.exists():
        return []
    with TARGETS_GEO_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# DB Pool (DBUtils)
# --------------------------------------------------------------------------- #

DB_POOL: Optional[PooledDB] = None


def init_db_pool() -> None:
    """
    Initialize DB connection pool at startup.
    Requirements:
    - min 5-10 active cached connections
    - max 20 connections
    - handle dead connections
    """
    global DB_POOL
    cfg = get_cfg()
    db_cfg = cfg.get("db") or {}
    if not isinstance(db_cfg, dict):
        raise RuntimeError("Missing 'db' section in config.yaml")

    # Pool sizing
    min_cached = int(db_cfg.get("pool_mincached", 5))
    max_cached = int(db_cfg.get("pool_maxcached", 10))
    max_conn = int(db_cfg.get("pool_maxconnections", 20))

    # Timeouts (5s requested)
    connect_timeout = int(db_cfg.get("connect_timeout", 5))
    read_timeout = int(db_cfg.get("read_timeout", 5))
    write_timeout = int(db_cfg.get("write_timeout", 5))

    logger.info(
        "Initializing DB pool mincached=%s maxcached=%s maxconnections=%s",
        min_cached, max_cached, max_conn
    )

    DB_POOL = PooledDB(
        creator=pymysql,
        mincached=min_cached,
        maxcached=max_cached,
        maxconnections=max_conn,
        blocking=True,  # if pool exhausted, wait (better than random failures)
        ping=1,         # check connection before using (auto-reconnect)
        host=db_cfg["host"],
        port=int(db_cfg["port"]),
        user=db_cfg["user"],
        password=db_cfg["password"],
        database=db_cfg["database"],
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        write_timeout=write_timeout,
    )


def get_db_conn():
    """
    FastAPI dependency: yields a pooled connection.
    Uses MAX_EXECUTION_TIME session setting (5s) for SELECT queries (MySQL >= 5.7 / MariaDB may vary).
    """
    if DB_POOL is None:
        # if startup didn't run (edge case), try init
        init_db_pool()

    assert DB_POOL is not None
    conn = DB_POOL.connection()
    try:
        # Per-connection/session query timeout (best-effort).
        # If not supported, it will fail silently.
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION MAX_EXECUTION_TIME=5000")
        except Exception:
            pass

        yield conn
    finally:
        # With DBUtils, close() returns connection to pool.
        try:
            conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class LastMeasurement(BaseModel):
    target_id: str
    host_id: Optional[str]
    type: str
    status: int
    latency_ms: int
    ts: dt.datetime
    region: str
    meta: Optional[Dict[str, Any]] = None


class LastByTarget(LastMeasurement):
    pass


class TimeSeriesPoint(BaseModel):
    ts: dt.datetime
    status: int
    latency_ms: int


class TargetMeta(BaseModel):
    id: str
    type: str
    host_id: Optional[str]
    host_address: Optional[str]
    enabled: bool = True


class TargetGeo(BaseModel):
    id: str        # host_id
    name: Optional[str]
    lat: float
    lng: float
    status: int
    latency_ms: int


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def parse_meta_json(rows: List[Dict[str, Any]], field: str = "meta") -> List[Dict[str, Any]]:
    """
    Parses JSON meta field safely (prevents crashes on invalid json).
    """
    for r in rows:
        raw = r.get(field)
        if not raw:
            continue
        if isinstance(raw, dict):
            continue
        try:
            r[field] = json.loads(raw)
        except Exception:
            r[field] = {"_meta_parse_error": True}
    return rows


def build_host_services_index(services: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    idx: Dict[str, List[str]] = {}
    for s in services:
        if not s.get("enabled", True):
            continue
        hid = s.get("host_id")
        sid = s.get("service_id")
        if hid and sid:
            idx.setdefault(hid, []).append(sid)
    return idx


def fetch_last_by_service_ids(conn, service_ids: List[str], region: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch last measurement (status, latency) for each service_id.
    Single query (no N+1).
    """
    if not service_ids:
        return {}

    placeholders = ", ".join(["%s"] * len(service_ids))
    params: List[Any] = service_ids[:]

    where_region = ""
    if region:
        where_region = "AND region = %s"
        params.append(region)

    sql = f"""
        SELECT m1.target_id, m1.status, m1.latency_ms
        FROM measurements m1
        JOIN (
            SELECT target_id, MAX(ts) AS max_ts
            FROM measurements
            WHERE target_id IN ({placeholders})
            {where_region}
            GROUP BY target_id
        ) sub ON m1.target_id = sub.target_id AND m1.ts = sub.max_ts
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[r["target_id"]] = {
            "status": int(r["status"]),
            "latency_ms": int(r["latency_ms"]),
        }
    return out


def aggregate_host_health(service_ids: List[str], last_by_service: Dict[str, Dict[str, Any]]) -> Tuple[int, int]:
    """
    CRIT si au moins 1 service CRIT
    WARN si aucun CRIT mais au moins 1 WARN
    OK sinon
    """
    statuses: List[int] = []
    lats: List[int] = []

    for sid in service_ids:
        last = last_by_service.get(sid)
        if not last:
            continue

        st = last["status"]
        statuses.append(st)

        if st > 0:
            lat = int(last.get("latency_ms", 0))
            if lat > 0:
                lats.append(lat)

    if not statuses:
        return 0, 0

    if 2 in statuses:
        return 2, max(lats) if lats else 0
    if 1 in statuses:
        return 1, max(lats) if lats else 0
    return 0, 0


# --------------------------------------------------------------------------- #
# Rate limiting (slowapi)
# --------------------------------------------------------------------------- #

limiter = Limiter(key_func=get_remote_address)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

app = FastAPI(title="GlobalNet Monitor API", version="0.5")
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # slowapi injects proper headers
    raise HTTPException(status_code=429, detail="rate limit exceeded")


@app.on_event("startup")
def on_startup():
    # DB pool
    init_db_pool()

    # Prometheus
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    logger.info("API startup completed")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@app.get("/api/last", response_model=List[LastMeasurement])
@limiter.limit("60/minute")
def get_last_measurements(
    region: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=1_000_000),
    conn=Depends(get_db_conn),
):
    params: List[Any] = []
    where = ""

    if region:
        where = "WHERE region = %s"
        params.append(region)

    sql = f"""
        SELECT target_id, host_id, type, status, latency_ms, ts, region, meta_json AS meta
        FROM measurements
        {where}
        ORDER BY ts DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    parse_meta_json(rows, field="meta")
    return rows


@app.get("/api/last-by-target", response_model=List[LastByTarget])
@limiter.limit("60/minute")
def get_last_by_target(
    region: Optional[str] = Query(None),
    conn=Depends(get_db_conn),
):
    params: List[Any] = []
    where = ""

    if region:
        where = "WHERE region = %s"
        params.append(region)

    sql = f"""
        SELECT m1.target_id, m1.host_id, m1.type, m1.status,
               m1.latency_ms, m1.ts, m1.region, m1.meta_json AS meta
        FROM measurements m1
        JOIN (
            SELECT target_id, MAX(ts) AS max_ts
            FROM measurements
            {where}
            GROUP BY target_id
        ) sub ON m1.target_id = sub.target_id AND m1.ts = sub.max_ts
        ORDER BY m1.target_id ASC
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    parse_meta_json(rows, field="meta")
    return rows


@app.get("/api/timeseries", response_model=List[TimeSeriesPoint])
@limiter.limit("60/minute")
def get_timeseries(
    target_id: str,
    minutes: int = Query(60, ge=1, le=1440),
    region: Optional[str] = Query(None),
    conn=Depends(get_db_conn),
):
    end_ts = dt.datetime.utcnow()
    start_ts = end_ts - dt.timedelta(minutes=minutes)

    params: List[Any] = [target_id, start_ts, end_ts]
    where_region = ""

    if region:
        where_region = "AND region = %s"
        params.append(region)

    sql = f"""
        SELECT ts, status, latency_ms
        FROM measurements
        WHERE target_id = %s
          AND ts BETWEEN %s AND %s
          {where_region}
        ORDER BY ts ASC
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return rows


@app.get("/api/meta/targets", response_model=List[TargetMeta])
@limiter.limit("60/minute")
def get_targets_meta():
    # TTL cache 60s
    services = load_services_cached()
    hosts = load_hosts_cached()
    out: List[TargetMeta] = []

    for s in services:
        sid = s.get("service_id")
        if not sid:
            continue

        host_id = s.get("host_id")
        host = hosts.get(host_id) if host_id else None

        out.append(
            TargetMeta(
                id=sid,
                type=s.get("type", "unknown"),
                host_id=host_id,
                host_address=host.get("address") if host else None,
                enabled=s.get("enabled", True),
            )
        )
    return out


@app.get("/api/meta/targets-geo", response_model=List[TargetGeo])
@limiter.limit("10/minute")  # costly endpoint
def get_targets_geo(
    region: Optional[str] = Query(None),
    limit_hosts: int = Query(200, ge=1, le=500),
    conn=Depends(get_db_conn),
):
    geo_raw = load_targets_geo_cached()
    if not geo_raw:
        return []

    # Limit number of hosts for safety
    geo_raw = geo_raw[:limit_hosts]

    services = load_services_cached()
    hosts = load_hosts_cached()
    host_services = build_host_services_index(services)

    # Only fetch service_ids for the hosts present in geo_raw (avoid huge IN lists)
    selected_host_ids: List[str] = []
    for item in geo_raw:
        hid = item.get("host_id") or item.get("id")
        if hid:
            selected_host_ids.append(hid)

    all_service_ids: List[str] = []
    for hid in selected_host_ids:
        all_service_ids.extend(host_services.get(hid, []))

    last_by_service = fetch_last_by_service_ids(conn, all_service_ids, region)

    out: List[TargetGeo] = []
    for item in geo_raw:
        hid = item.get("host_id") or item.get("id")
        if not hid:
            continue

        sids = host_services.get(hid, [])
        status, latency = aggregate_host_health(sids, last_by_service)

        name = item.get("name") or hosts.get(hid, {}).get("name") or hid

        out.append(
            TargetGeo(
                id=hid,
                name=name,
                lat=float(item["lat"]),
                lng=float(item["lng"]),
                status=status,
                latency_ms=latency,
            )
        )

    return out


@app.get("/health")
def health():
    # Check config presence and DB section
    cfg = get_cfg()
    db = cfg.get("db")
    if not isinstance(db, dict):
        return {"status": "error", "reason": "missing db config"}

    # pool ready?
    if DB_POOL is None:
        return {"status": "error", "reason": "db pool not initialized"}

    return {"status": "ok"}

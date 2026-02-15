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
GlobalNet Monitor (GNM) – collector.py
GNMRADAR Core – Collector Engine (Monolith v1)

Author: Soufianne Nassibi
Website: https://soufianne-nassibi.com
Contact: contact@soufianne-nassibi.com
License: GPL-3.0

Version hosts.json + services.json, checks internes, avec host_id en BDD.

Objectifs (version moins sensible, sans casser l'existant) :
- Seuils WARN/latence configurables via config.yaml (collector.thresholds.*)
- CRIT uniquement pour HARD DOWN (timeout / connexion impossible / DNS fail / TLS fail)
- WARN pour "degraded" (latence élevée, HTTP 4xx/5xx, JSON key missing, etc.)
- Anti faux positifs : 2-strikes sur HARD DOWN (1er hard-down => WARN, 2e consécutif => CRIT)
- Region dynamique basée sur IP publique (geo-IP) + cache TTL local + override ENV

Dépendances :
- requests, PyYAML, pymysql, dnspython
"""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import dns.resolver
import pymysql
import requests
import yaml

# --------------------------------------------------------------------------- #
# Paths de configuration
# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent  # supposé être ~/gnm/

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
HOSTS_PATH = PROJECT_ROOT / "config" / "hosts.json"
SERVICES_PATH = PROJECT_ROOT / "config" / "services.json"

# Geo-probe cache (pour région dynamique)
PROBE_CACHE_PATH = PROJECT_ROOT / "config" / "probe_cache.json"
PROBE_CACHE_TTL_SEC = 24 * 3600  # 24h

# Anti faux positifs (2-strikes) : hard down doit être confirmé 2 fois
FAIL_STREAK: Dict[str, int] = {}
OK_STREAK: Dict[str, int] = {}


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #

def load_config() -> Dict[str, Any]:
    """Charge la configuration YAML globale."""
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_hosts() -> Dict[str, Dict[str, Any]]:
    """Charge hosts.json et renvoie un dict host_id -> host_object."""
    if not HOSTS_PATH.exists():
        raise RuntimeError(f"hosts file not found: {HOSTS_PATH}")
    with HOSTS_PATH.open(encoding="utf-8") as fh:
        hosts_list = json.load(fh)

    hosts: Dict[str, Dict[str, Any]] = {}
    for h in hosts_list:
        hid = h.get("host_id")
        if not hid:
            continue
        hosts[hid] = h
    return hosts


def load_services() -> List[Dict[str, Any]]:
    """Charge services.json et renvoie la liste des services enabled."""
    if not SERVICES_PATH.exists():
        raise RuntimeError(f"services file not found: {SERVICES_PATH}")
    with SERVICES_PATH.open(encoding="utf-8") as fh:
        services = json.load(fh)
    return [s for s in services if s.get("enabled", True)]


# --------------------------------------------------------------------------- #
# Logging helpers
# --------------------------------------------------------------------------- #

def log_info(msg: str) -> None:
    ts = dt.datetime.utcnow().isoformat(timespec="milliseconds")
    print(f"[INFO] {ts} {msg}", file=sys.stdout, flush=True)


def log_error(msg: str, exc: Optional[BaseException] = None) -> None:
    ts = dt.datetime.utcnow().isoformat(timespec="milliseconds")
    err = f"[ERROR] {ts} {msg}"
    if exc:
        err += f" exception={exc}"
    print(err, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# DB helpers – adaptés à la colonne host_id
# --------------------------------------------------------------------------- #

def get_db_conn(db_cfg: Dict[str, Any]) -> pymysql.Connection:
    return pymysql.connect(
        host=db_cfg["host"],
        port=int(db_cfg["port"]),
        user=db_cfg["user"],
        password=db_cfg["password"],
        database=db_cfg["database"],
        autocommit=True,
        charset="utf8mb4",
        init_command="SET time_zone = '+00:00'",
    )



def insert_measurement(
    conn: pymysql.Connection,
    ts: dt.datetime,
    region: str,
    project_id: Optional[int],
    target_id: str,
    host_id: Optional[str],
    type: str,
    status: int,
    latency_ms: int,
    meta: Dict[str, Any],
) -> None:
    """Insert d’une mesure dans la table measurements incluant host_id."""
    sql = """
        INSERT INTO measurements
        (ts, region, project_id, target_id, host_id, type, status, latency_ms, meta_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    meta_json = json.dumps(meta) if meta else None
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                ts,
                region,
                project_id,
                target_id,
                host_id,
                type,
                status,
                latency_ms,
                meta_json,
            ),
        )


# --------------------------------------------------------------------------- #
# Helpers robustes pour address / hostname
# --------------------------------------------------------------------------- #

def _hostname_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def resolve_host_address(service: Dict[str, Any], host: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Donne une address robuste :
    - si host existe et a "address" => OK
    - sinon pour json_api/http => hostname dérivé depuis params.url
    - sinon None
    """
    if host and host.get("address"):
        return str(host["address"]).strip() or None

    params = service.get("params", {}) or {}
    url = params.get("url")
    hn = _hostname_from_url(url)
    if hn:
        return hn

    return None


# --------------------------------------------------------------------------- #
# Probe discovery (region dynamique basée sur IP publique)
# --------------------------------------------------------------------------- #

def _country_to_region(country_code: Optional[str]) -> str:
    if not country_code:
        return "UNKNOWN"
    cc = country_code.upper()

    EU = {"FR","ES","PT","BE","NL","DE","LU","IT","GB","IE","CH","AT","SE","NO","DK","FI","PL","CZ","SK","HU","RO","BG","GR","HR","SI","EE","LV","LT"}
    NA = {"US","CA","MX"}
    SA = {"BR","AR","CL","CO","PE","UY","PY","BO","EC","VE"}
    AF = {"MA","DZ","TN","EG","ZA","NG","KE","GH","SN","CI","CM","ET","UG","TZ","RW"}
    AS = {"TR","SA","AE","QA","KW","OM","BH","IN","PK","BD","CN","JP","KR","SG","MY","TH","VN","ID","PH","HK","TW"}
    OC = {"AU","NZ"}

    if cc in EU: return "EU"
    if cc in NA: return "NA"
    if cc in SA: return "SA"
    if cc in AF: return "AF"
    if cc in AS: return "AS"
    if cc in OC: return "OC"
    return "OTHER"


def _load_probe_cache() -> Optional[Dict[str, Any]]:
    try:
        if not PROBE_CACHE_PATH.exists():
            return None
        data = json.loads(PROBE_CACHE_PATH.read_text(encoding="utf-8"))
        ts = float(data.get("_cached_at", 0))
        if not ts:
            return None
        if time.time() - ts > PROBE_CACHE_TTL_SEC:
            return None
        return data
    except Exception:
        return None


def _save_probe_cache(data: Dict[str, Any]) -> None:
    try:
        data["_cached_at"] = time.time()
        PROBE_CACHE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def discover_probe_identity(cfg_region_fallback: str, timeout_sec: int = 4) -> Dict[str, Any]:
    """
    Détermine automatiquement la région de la sonde via IP publique + geo-IP.
    - Override via env
    - Cache local TTL 24h
    - Fallback sur cfg['region'] si tout échoue
    """
    env_region = os.getenv("GNM_PROBE_REGION")
    if env_region:
        return {
            "probe_region": env_region,
            "probe_country": os.getenv("GNM_PROBE_COUNTRY"),
            "probe_city": os.getenv("GNM_PROBE_CITY"),
            "probe_public_ip": os.getenv("GNM_PROBE_PUBLIC_IP"),
            "probe_source": "env",
        }

    cached = _load_probe_cache()
    if cached and cached.get("probe_region"):
        cached["probe_source"] = "cache"
        return cached

    public_ip = None
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=timeout_sec)
        if r.ok:
            public_ip = (r.json() or {}).get("ip")
    except Exception:
        public_ip = None

    if not public_ip:
        return {"probe_region": cfg_region_fallback, "probe_source": "fallback_no_public_ip"}

    geo: Dict[str, Any] = {}
    try:
        r = requests.get(f"https://ipapi.co/{public_ip}/json/", timeout=timeout_sec)
        if r.ok:
            geo = r.json() or {}
    except Exception:
        geo = {}

    country = (geo.get("country_code") or geo.get("country") or "").upper() or None
    city = geo.get("city") or None

    probe_region = _country_to_region(country) if country else "UNKNOWN"

    data = {
        "probe_public_ip": public_ip,
        "probe_country": country,
        "probe_city": city,
        "probe_region": probe_region if probe_region else cfg_region_fallback,
        "probe_source": "ip_geo",
    }
    _save_probe_cache(data)
    return data


# --------------------------------------------------------------------------- #
# Threshold helpers (moins sensible)
# --------------------------------------------------------------------------- #

def _tint(thresholds: Dict[str, Any], key: str, default: int) -> int:
    try:
        v = thresholds.get(key, default)
        return int(v)
    except Exception:
        return default


# --------------------------------------------------------------------------- #
# Checks internes — CRIT = hard down uniquement
# --------------------------------------------------------------------------- #

def check_ping(host: str, timeout_sec: int, thresholds: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
    start = time.perf_counter()
    meta: Dict[str, Any] = {}

    WARN_MS = _tint(thresholds, "ping_warn_ms", 500)
    VERY_SLOW_MS = _tint(thresholds, "ping_very_slow_ms", 1500)

    try:
        cmd = ["ping", "-c", "1", "-W", str(timeout_sec), host]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec + 1)
        latency_ms = int((time.perf_counter() - start) * 1000)
        meta["returncode"] = completed.returncode

        if completed.returncode != 0:
            meta["error"] = completed.stderr.strip() or "ping_failed"
            meta["hard_down"] = True
            return 2, latency_ms, meta

        if latency_ms < WARN_MS:
            return 0, latency_ms, meta

        meta["reason"] = "slow_ping"
        meta["slow_level"] = "very" if latency_ms >= VERY_SLOW_MS else "mild"
        return 1, latency_ms, meta

    except Exception as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta


def check_http(url: str, timeout_sec: int, thresholds: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
    start = time.perf_counter()
    meta: Dict[str, Any] = {}

    WARN_MS = _tint(thresholds, "http_warn_ms", 8000)
    VERY_SLOW_MS = _tint(thresholds, "http_very_slow_ms", 20000)

    try:
        resp = requests.get(
            url,
            timeout=timeout_sec,
            headers={"User-Agent": "GNM-Collector/1.0"},
            allow_redirects=True,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        code = resp.status_code
        meta["http_status"] = code

        # Codes HTTP : dégradation, pas hard down
        if code >= 500:
            meta["reason"] = "http_5xx"
            return 1, latency_ms, meta

        if 400 <= code < 500:
            meta["reason"] = "http_4xx"
            return 1, latency_ms, meta

        # Succès 2xx/3xx : latence => WARN si lente
        if latency_ms < WARN_MS:
            return 0, latency_ms, meta

        meta["reason"] = "slow_http"
        meta["slow_level"] = "very" if latency_ms >= VERY_SLOW_MS else "mild"
        return 1, latency_ms, meta

    except requests.exceptions.Timeout:
        meta["error"] = "timeout"
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta

    except requests.exceptions.RequestException as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta

    except Exception as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta


def check_dns(name: str, timeout_sec: int, thresholds: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
    start = time.perf_counter()
    meta: Dict[str, Any] = {}

    WARN_MS = _tint(thresholds, "dns_warn_ms", 1200)

    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout_sec
        resolver.lifetime = timeout_sec
        answer = resolver.resolve(name, "A")
        latency_ms = int((time.perf_counter() - start) * 1000)
        meta["rrset"] = str(answer.rrset)

        if latency_ms < WARN_MS:
            return 0, latency_ms, meta

        meta["reason"] = "slow_dns"
        return 1, latency_ms, meta

    except Exception as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta


def check_tcp(host: str, port: int, timeout_sec: int, thresholds: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
    start = time.perf_counter()
    meta: Dict[str, Any] = {}

    WARN_MS = _tint(thresholds, "tcp_warn_ms", 1500)
    VERY_SLOW_MS = _tint(thresholds, "tcp_very_slow_ms", 4000)

    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            pass
        latency_ms = int((time.perf_counter() - start) * 1000)

        if latency_ms < WARN_MS:
            return 0, latency_ms, meta

        meta["reason"] = "slow_tcp"
        meta["slow_level"] = "very" if latency_ms >= VERY_SLOW_MS else "mild"
        return 1, latency_ms, meta

    except Exception as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta


def check_ssl_cert(host: str, port: int, timeout_sec: int) -> Tuple[int, int, Dict[str, Any]]:
    start = time.perf_counter()
    meta: Dict[str, Any] = {}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout_sec) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()

        not_after = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        days_left = (not_after - dt.datetime.utcnow()).days
        meta["not_after"] = not_after.isoformat()
        meta["days_left"] = days_left
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Cert policy
        if days_left >= 30:
            return 0, latency_ms, meta
        if days_left >= 7:
            return 1, latency_ms, meta
        return 2, latency_ms, meta  # cert critique (<7j)

    except Exception as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta


def check_json_api(url: str, timeout_sec: int, expect_key: Optional[str], thresholds: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
    start = time.perf_counter()
    meta: Dict[str, Any] = {}

    WARN_MS = _tint(thresholds, "json_warn_ms", 8000)
    VERY_SLOW_MS = _tint(thresholds, "json_very_slow_ms", 20000)

    try:
        resp = requests.get(url, timeout=timeout_sec, headers={"User-Agent": "GNM-Collector/1.0"})
        latency_ms = int((time.perf_counter() - start) * 1000)
        meta["http_status"] = resp.status_code

        if resp.status_code != 200:
            meta["reason"] = f"http_{resp.status_code}"
            return 1, latency_ms, meta

        try:
            data = resp.json()
        except ValueError:
            meta["error"] = "json_decode_failed"
            return 1, latency_ms, meta

        if expect_key:
            meta["has_key"] = expect_key in data
            if expect_key not in data:
                meta["error"] = f"missing_key:{expect_key}"
                return 1, latency_ms, meta

        if latency_ms < WARN_MS:
            return 0, latency_ms, meta

        meta["reason"] = "slow_json_api"
        meta["slow_level"] = "very" if latency_ms >= VERY_SLOW_MS else "mild"
        return 1, latency_ms, meta

    except requests.exceptions.Timeout:
        meta["error"] = "timeout"
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta

    except requests.exceptions.RequestException as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta

    except Exception as exc:
        meta["error"] = str(exc)
        meta["hard_down"] = True
        return 2, int((time.perf_counter() - start) * 1000), meta


# --------------------------------------------------------------------------- #
# Dispatcher générique
# --------------------------------------------------------------------------- #

def run_check(ttype: str, t: Dict[str, Any], timeouts: Dict[str, Any], thresholds: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
    if ttype == "ping":
        if "host" not in t or not t["host"]:
            return 2, 0, {"error": "missing_field:host", "hard_down": True}
        return check_ping(t["host"], timeouts["ping_timeout_sec"], thresholds)

    if ttype == "http":
        if "url" not in t or not t["url"]:
            return 2, 0, {"error": "missing_field:url", "hard_down": True}
        return check_http(t["url"], timeouts["http_timeout_sec"], thresholds)

    if ttype == "dns":
        if "host" not in t or not t["host"]:
            return 2, 0, {"error": "missing_field:host", "hard_down": True}
        return check_dns(t["host"], timeouts["dns_timeout_sec"], thresholds)

    if ttype == "tcp":
        if "host" not in t or "port" not in t or not t["host"] or t["port"] is None:
            return 2, 0, {"error": "missing_field:host|port", "hard_down": True}
        return check_tcp(t["host"], int(t["port"]), timeouts["tcp_timeout_sec"], thresholds)

    if ttype == "ssl_cert":
        if "host" not in t or "port" not in t or not t["host"] or t["port"] is None:
            return 2, 0, {"error": "missing_field:host|port", "hard_down": True}
        return check_ssl_cert(t["host"], int(t["port"]), timeouts["tcp_timeout_sec"])

    if ttype == "json_api":
        if "url" not in t or not t["url"]:
            return 2, 0, {"error": "missing_field:url", "hard_down": True}
        return check_json_api(
            t["url"],
            timeouts["http_timeout_sec"],
            t.get("expect_key"),
            thresholds,
        )

    return 2, 0, {"error": f"unknown_type:{ttype}", "hard_down": True}


# --------------------------------------------------------------------------- #
# Construction du payload
# --------------------------------------------------------------------------- #

def build_check_payload(service: Dict[str, Any], host: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    ttype = service["type"]
    params = service.get("params", {}) or {}
    address = resolve_host_address(service, host)

    if ttype == "ping":
        t = {"host": address}
    elif ttype == "dns":
        t = {"host": address}
    elif ttype == "http":
        url = params.get("url")
        if not url:
            scheme = params.get("scheme", "https")
            path = params.get("path", "/")
            if address:
                url = f"{scheme}://{address}{path}"
        t = {"url": url}
    elif ttype == "ssl_cert":
        port = params.get("port", 443)
        t = {"host": address, "port": port}
    elif ttype == "json_api":
        url = params.get("url")
        expect_key = params.get("expect_key")
        t = {"url": url, "expect_key": expect_key}
    elif ttype == "tcp":
        port = params.get("port")
        t = {"host": address, "port": port}
    else:
        t = {}

    return ttype, t


# --------------------------------------------------------------------------- #
# Exécution d'un service
# --------------------------------------------------------------------------- #

def run_one_service(
    service: Dict[str, Any],
    hosts: Dict[str, Dict[str, Any]],
    timeouts: Dict[str, Any],
    thresholds: Dict[str, Any],
    region_fallback: str,
    probe: Dict[str, Any],
) -> Optional[Dict[str, Any]]:

    service_id = service.get("service_id")
    if not service_id:
        log_error("missing_field:service_id")
        return None

    host_id = service.get("host_id")
    if not host_id:
        log_error(f"service_id={service_id} missing_field:host_id")
        return None

    ttype = service.get("type")
    if not ttype:
        log_error(f"service_id={service_id} missing_field:type")
        return None

    host = hosts.get(host_id)

    # json_api peut fonctionner même si hosts.json est incomplet
    if not host and ttype != "json_api":
        log_error(f"service_id={service_id} unknown_host_id={host_id}")
        return None

    addr = resolve_host_address(service, host)
    if ttype in ("ping", "dns", "tcp", "ssl_cert") and not addr:
        log_error(f"service_id={service_id} host_id={host_id} missing_field:host.address")
        return None

    ttype, t_payload = build_check_payload(service, host)
    status, latency_ms, meta = run_check(ttype, t_payload, timeouts, thresholds)

    meta = meta or {}
    meta.setdefault("host_id", host_id)
    meta.setdefault("service_id", service_id)
    meta.setdefault("host_address", addr or host_id)

    # Enrich probe info
    probe_region = probe.get("probe_region") or region_fallback
    meta.setdefault("probe_region", probe_region)
    meta.setdefault("probe_country", probe.get("probe_country"))
    meta.setdefault("probe_city", probe.get("probe_city"))
    meta.setdefault("probe_public_ip", probe.get("probe_public_ip"))
    meta.setdefault("probe_source", probe.get("probe_source"))

    # 2-strikes : hard down doit être confirmé 2 fois
    hard_down = bool(meta.get("hard_down"))
    key = service_id  # streak par service

    if hard_down:
        FAIL_STREAK[key] = FAIL_STREAK.get(key, 0) + 1
        OK_STREAK[key] = 0

        if FAIL_STREAK[key] < 2:
            meta["softened"] = "first_hard_down"
            status = 1
    else:
        OK_STREAK[key] = OK_STREAK.get(key, 0) + 1
        FAIL_STREAK[key] = 0

    # La "region" en DB = point de vue réel (sonde)
    region = probe_region

    return {
        "ts": dt.datetime.utcnow(),
        "region": region,
        "project_id": service.get("project_id"),
        "target_id": service_id,
        "host_id": host_id,
        "type": ttype,
        "status": status,
        "latency_ms": latency_ms,
        "meta": meta,
    }


# --------------------------------------------------------------------------- #
# Boucle principale
# --------------------------------------------------------------------------- #

def main() -> None:
    cfg = load_config()
    db_cfg = cfg["db"]
    region_fallback = cfg.get("region", "UNKNOWN")

    interval_sec = cfg["collector"]["interval_sec"]
    timeouts = {
        "ping_timeout_sec": cfg["collector"]["ping_timeout_sec"],
        "http_timeout_sec": cfg["collector"]["http_timeout_sec"],
        "dns_timeout_sec": cfg["collector"]["dns_timeout_sec"],
        "tcp_timeout_sec": cfg["collector"]["tcp_timeout_sec"],
    }

    thresholds = cfg["collector"].get("thresholds", {})

    max_workers = cfg["collector"]["max_workers"]
    once = len(sys.argv) > 1 and sys.argv[1] == "once"

    hosts = load_hosts()

    # Probe dynamic region discovery (au démarrage; cache TTL 24h)
    probe = discover_probe_identity(cfg_region_fallback=region_fallback, timeout_sec=4)
    log_info(
        f"probe region={probe.get('probe_region')} country={probe.get('probe_country')} "
        f"city={probe.get('probe_city')} ip={probe.get('probe_public_ip')} source={probe.get('probe_source')}"
    )

    while True:
        cycle_start = time.time()
        elapsed = 0.0

        conn = get_db_conn(db_cfg)

        try:
            services = load_services()
            results: List[Dict[str, Any]] = []

            workers = min(max_workers, len(services) or 1)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(run_one_service, s, hosts, timeouts, thresholds, region_fallback, probe)
                    for s in services
                ]
                for fut in as_completed(futures):
                    try:
                        res = fut.result()
                        if res:
                            results.append(res)
                    except Exception as e:
                        log_error("worker_failed", e)

            for res in results:
                insert_measurement(conn, **res)
                log_info(
                    f"service={res['target_id']} host_id={res['host_id']} type={res['type']} "
                    f"status={res['status']} latency={res['latency_ms']}ms region={res['region']}"
                )

            elapsed = time.time() - cycle_start
            ok = sum(1 for r in results if r["status"] == 0)
            warn = sum(1 for r in results if r["status"] == 1)
            crit = sum(1 for r in results if r["status"] == 2)

            log_info(
                f"cycle_summary services={len(results)} ok={ok} warn={warn} crit={crit} "
                f"cycle_duration={elapsed:.3f}s"
            )

        finally:
            conn.close()

        if once:
            break

        sleep_time = max(1, interval_sec - elapsed) if elapsed > 0 else interval_sec
        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)

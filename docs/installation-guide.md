Installation Guide – GlobalNet Monitor (GNM)

Author: Soufianne Nassibi
Role: Technical Lead – Linux Systems & Large-Scale Monitoring Architect
Website: https://soufianne-nassibi.com

Live Demo: https://gnmradar.ovh/

License: GNU GPL v3.0 (Collector & API components only)

1. Overview

This document describes the full installation procedure for:

Collector engine

API backend

MySQL database

systemd service management

Production hardening recommendations

Target environment:

Linux (Debian / Ubuntu recommended)

Python 3.8+

MySQL 5.7+ or MariaDB equivalent

2. System Requirements
Minimum

2 vCPU

2 GB RAM

20 GB disk

Python 3.8+

MySQL 5.7+

Recommended (Moderate Load)

4 vCPU

4–8 GB RAM

SSD storage

Separate DB node (optional)

3. Directory Layout

Recommended layout:

/opt/gnm/
│
├── collector.py
├── api.py
├── requirements.txt
│
├── config/
│   ├── config.yaml
│   ├── hosts.json
│   └── services.json
│
├── logs/
│
└── venv/

4. System User Creation

Create dedicated service user:

sudo useradd -r -s /bin/false gnm
sudo mkdir -p /opt/gnm
sudo chown -R gnm:gnm /opt/gnm

5. Python Environment Setup
cd /opt/gnm
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

6. MySQL Setup
6.1 Create Database
CREATE DATABASE gnm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

6.2 Create User
CREATE USER 'gnm_user'@'localhost' IDENTIFIED BY 'strong_password';
GRANT ALL PRIVILEGES ON gnm.* TO 'gnm_user'@'localhost';
FLUSH PRIVILEGES;

6.3 Apply Schema
mysql -u gnm_user -p gnm < schema.sql

7. Configuration Files
7.1 config.yaml

Example:

region: EU

db:
  host: localhost
  port: 3306
  user: gnm_user
  password: strong_password
  database: gnm

collector:
  interval_sec: 60
  max_workers: 10
  ping_timeout_sec: 5
  http_timeout_sec: 10
  dns_timeout_sec: 5
  tcp_timeout_sec: 5

7.2 hosts.json
[
  {
    "host_id": "web01",
    "address": "example.com"
  }
]

7.3 services.json
[
  {
    "service_id": "web01_http",
    "host_id": "web01",
    "type": "http",
    "params": {
      "url": "https://example.com"
    }
  }
]

8. Running Collector Manually

Test execution:

cd /opt/gnm
source venv/bin/activate
python collector.py once


Continuous mode:

python collector.py

9. Running API Manually
source venv/bin/activate
uvicorn api:app --host 0.0.0.0 --port 8000


Test:

http://localhost:8000/health

10. systemd Service Configuration
10.1 Collector Service

Create:

/etc/systemd/system/gnm-collector.service

[Unit]
Description=GlobalNet Monitor Collector
After=network.target mysql.service

[Service]
User=gnm
WorkingDirectory=/opt/gnm
ExecStart=/opt/gnm/venv/bin/python collector.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target


Enable:

sudo systemctl daemon-reload
sudo systemctl enable gnm-collector
sudo systemctl start gnm-collector

10.2 API Service

Create:

/etc/systemd/system/gnm-api.service

[Unit]
Description=GlobalNet Monitor API
After=network.target mysql.service

[Service]
User=gnm
WorkingDirectory=/opt/gnm
ExecStart=/opt/gnm/venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target


Enable:

sudo systemctl daemon-reload
sudo systemctl enable gnm-api
sudo systemctl start gnm-api

11. Reverse Proxy (Recommended)

Install Nginx:

sudo apt install nginx


Example configuration:

server {
    listen 443 ssl;
    server_name monitoring.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}


Enable TLS via Certbot.

12. Production Hardening

Recommended:

Run under dedicated non-root user

Restrict MySQL to localhost

Use firewall (ufw or iptables)

Enable TLS on API

Enable rate limiting at reverse proxy

Disable directory browsing

Regular security updates

13. Backup Strategy

Recommended:

Daily MySQL dump

mysqldump -u gnm_user -p gnm > backup.sql


Rotate backups

Monitor disk usage

14. Scaling Strategy
Horizontal

Multiple collectors

Shared DB

API behind load balancer

Vertical

Increase worker pool

Upgrade DB hardware

Optimize indexes

15. Upgrade Procedure

Stop services:

systemctl stop gnm-collector
systemctl stop gnm-api


Pull new code

Update dependencies

Apply DB migrations (if needed)

Restart services

16. Troubleshooting

Check logs:

journalctl -u gnm-collector -f
journalctl -u gnm-api -f


Common issues:

DB connection refused

Permission denied

Port already in use

Missing configuration file

17. Deployment Modes
Lab Mode

All components on one node.

Split Mode

Collector remote, API+DB central.

Federated Mode

Multiple collectors writing to shared DB.

18. Production Readiness Checklist

DB schema applied

Services enabled

Reverse proxy configured

Firewall configured

TLS enabled

Log rotation active

Backup configured

Monitoring of monitoring in place

Author

Soufianne Nassibi
Technical Lead – Linux Systems & Monitoring Architect

https://soufianne-nassibi.com

https://gnmradar.ovh

© Soufianne Nassibi – GlobalNet Monitor (GNM)

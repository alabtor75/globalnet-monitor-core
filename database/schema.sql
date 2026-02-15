-- GlobalNet Monitor (GNM)
-- Database Schema
-- Author: Soufianne Nassibi
-- License: GNU GPL v3.0 (Collector & API components only)

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


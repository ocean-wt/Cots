-- Cots platform schema — MySQL 8.0, utf8mb4.
-- Auto-loaded by docker-compose (mounted into /docker-entrypoint-initdb.d).
-- The application also runs idempotent create_all; existing tables are kept.

CREATE DATABASE IF NOT EXISTS cots
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE cots;

-- 1. tenants ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_code   VARCHAR(64)  NOT NULL,
  name          VARCHAR(128) NOT NULL,
  plan          VARCHAR(32)  NOT NULL DEFAULT 'pro',
  status        VARCHAR(32)  NOT NULL DEFAULT 'active',
  daily_quota   INT          NOT NULL DEFAULT 100000,
  qps_limit     INT          NOT NULL DEFAULT 50,
  balance_cents INT          NOT NULL DEFAULT 0,
  overdue       TINYINT(1)   NOT NULL DEFAULT 0,
  extra         JSON         NULL,
  created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_tenants_code (tenant_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='tenants (plan / quota / QPS / arrears)';

-- 2. users ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_id     BIGINT UNSIGNED NOT NULL,
  email         VARCHAR(255) NOT NULL,
  display_name  VARCHAR(128) NOT NULL,
  password_hash VARCHAR(255) NOT NULL DEFAULT '!',
  role          VARCHAR(32)  NOT NULL DEFAULT 'admin',
  status        VARCHAR(32)  NOT NULL DEFAULT 'active',
  extra         JSON NULL,
  created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email),
  KEY ix_users_tenant (tenant_id),
  CONSTRAINT fk_users_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='tenant users';

-- 3. applications -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_id   BIGINT UNSIGNED NOT NULL,
  app_code    VARCHAR(64)  NOT NULL,
  name        VARCHAR(128) NOT NULL,
  environment VARCHAR(32)  NOT NULL DEFAULT 'production',
  status      VARCHAR(32)  NOT NULL DEFAULT 'active',
  config      JSON NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_apps_code (app_code),
  KEY ix_apps_tenant (tenant_id),
  CONSTRAINT fk_apps_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='tenant applications';

-- 4. api_keys ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_keys (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_id      BIGINT UNSIGNED NOT NULL,
  application_id BIGINT UNSIGNED NULL,
  key_prefix     VARCHAR(16)  NOT NULL,
  key_hash       VARCHAR(255) NOT NULL,
  name           VARCHAR(128) NOT NULL DEFAULT 'default',
  scopes         JSON NULL,
  status         VARCHAR(32)  NOT NULL DEFAULT 'active',
  last_used_at   DATETIME(6) NULL,
  created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_api_keys_hash (key_hash),
  KEY ix_api_keys_prefix (key_prefix),
  KEY ix_api_keys_tenant (tenant_id),
  CONSTRAINT fk_keys_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  CONSTRAINT fk_keys_app FOREIGN KEY (application_id) REFERENCES applications (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='API keys (hash stored only)';

-- 5. conversations ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_id   BIGINT UNSIGNED NOT NULL,
  user_id     BIGINT UNSIGNED NOT NULL,
  title       VARCHAR(255) NOT NULL DEFAULT '新会话',
  status      VARCHAR(32)  NOT NULL DEFAULT 'active',
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_convos_tenant (tenant_id),
  KEY ix_convos_user (user_id),
  CONSTRAINT fk_convos_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  CONSTRAINT fk_convos_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='user conversations';

-- 6. messages ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT UNSIGNED NOT NULL,
  role            VARCHAR(32) NOT NULL,
  content         MEDIUMTEXT  NOT NULL,
  trace_id        VARCHAR(64) NULL,
  token_usage     JSON NULL,
  structured      JSON NULL,
  created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_messages_convo (conversation_id),
  KEY ix_messages_trace (trace_id),
  CONSTRAINT fk_messages_convo FOREIGN KEY (conversation_id)
    REFERENCES conversations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='conversation messages (incl. structured final report)';

-- 7. tickets ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_id   BIGINT UNSIGNED NOT NULL,
  ticket_no   VARCHAR(32)  NOT NULL,
  title       VARCHAR(255) NOT NULL,
  category    VARCHAR(64)  NOT NULL DEFAULT 'technical',
  priority    VARCHAR(16)  NOT NULL DEFAULT 'P2',
  status      VARCHAR(32)  NOT NULL DEFAULT 'open',
  trace_id    VARCHAR(64)  NULL,
  source      VARCHAR(64)  NOT NULL DEFAULT 'agent_auto',
  detail      JSON NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_tickets_no (ticket_no),
  KEY ix_tickets_tenant (tenant_id),
  KEY ix_tickets_trace (trace_id),
  CONSTRAINT fk_tickets_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='tickets (incl. agent auto-escalation)';

-- 8. api_logs ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_logs (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_id      BIGINT UNSIGNED NOT NULL,
  application_id BIGINT UNSIGNED NULL,
  api_key_id     BIGINT UNSIGNED NULL,
  trace_id       VARCHAR(64) NOT NULL,
  method         VARCHAR(8)  NOT NULL,
  endpoint       VARCHAR(255) NOT NULL,
  status_code    INT NOT NULL,
  latency_ms     INT NOT NULL DEFAULT 0,
  request_body   MEDIUMTEXT NULL,
  error_message  MEDIUMTEXT NULL,
  upstream       VARCHAR(128) NULL,
  created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_logs_trace (trace_id),
  KEY ix_logs_status (status_code),
  KEY ix_logs_created (created_at),
  KEY ix_logs_trace_status (trace_id, status_code),
  CONSTRAINT fk_logs_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  CONSTRAINT fk_logs_app FOREIGN KEY (application_id) REFERENCES applications (id),
  CONSTRAINT fk_logs_key FOREIGN KEY (api_key_id) REFERENCES api_keys (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='API call logs (source of truth for diagnostics)';

-- 9. agent_execution_traces -------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_execution_traces (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id          VARCHAR(64) NOT NULL,
  trace_id        VARCHAR(64) NOT NULL,
  tenant_id       BIGINT UNSIGNED NULL,
  conversation_id BIGINT UNSIGNED NULL,
  round_index     INT NOT NULL DEFAULT 0,
  task_id         VARCHAR(64) NULL,
  agent_name      VARCHAR(64) NOT NULL,
  node            VARCHAR(64) NOT NULL,
  phase           VARCHAR(32) NOT NULL,
  action          VARCHAR(255) NOT NULL DEFAULT '',
  detail          MEDIUMTEXT NULL,
  input_payload   JSON NULL,
  output_payload  JSON NULL,
  evidence        JSON NULL,
  token_usage     JSON NULL,
  status          VARCHAR(32) NOT NULL DEFAULT 'ok',
  duration_ms     INT NOT NULL DEFAULT 0,
  created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_traces_run (run_id),
  KEY ix_traces_trace (trace_id),
  KEY ix_traces_run_agent (run_id, agent_name),
  KEY ix_traces_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='full agent trail: reasoning / tool calls / evidence / tokens (lossless async writes)';

-- 10. dynamic_workflow_states ----------------------------------------------
CREATE TABLE IF NOT EXISTS dynamic_workflow_states (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id         VARCHAR(64) NOT NULL,
  trace_id       VARCHAR(64) NOT NULL,
  current_node   VARCHAR(64) NOT NULL DEFAULT 'supervisor',
  round_index    INT NOT NULL DEFAULT 0,
  max_rounds     INT NOT NULL DEFAULT 2,
  status         VARCHAR(32) NOT NULL DEFAULT 'planning',
  plan           JSON NULL,
  state_snapshot JSON NULL,
  verdict_summary JSON NULL,
  created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_wf_run (run_id),
  KEY ix_wf_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='dynamic workflow state (resumable checkpoints, JSON-first)';

-- 11. knowledge_chunks ------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  chunk_uid        VARCHAR(64) NOT NULL,
  doc_id           VARCHAR(64) NOT NULL,
  doc_title        VARCHAR(255) NOT NULL,
  chunk_index      INT NOT NULL DEFAULT 0,
  section          VARCHAR(255) NOT NULL DEFAULT '',
  tags             JSON NULL,
  content          MEDIUMTEXT NOT NULL,
  token_count      INT NOT NULL DEFAULT 0,
  embedding_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  rerank_bias      DOUBLE NOT NULL DEFAULT 0,
  created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_chunk_uid (chunk_uid),
  UNIQUE KEY uq_doc_chunk (doc_id, chunk_index),
  KEY ix_chunks_doc (doc_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='knowledge corpus (authoritative source for BM25 and Milvus retrieval)';

# AIOps Email RCA Runbook

## Overview

This runbook describes the minimal viable workflow described in the project README:

1. **Email/Alert intake** via IMAP polling, Microsoft Graph subscriptions or Alertmanager webhooks.
2. **Normalization** to the canonical event JSON schema.
3. **Root Cause Analysis (RCA)** using the Qwen-Plus model exposed through the `rca` microservice.
4. **Policy evaluation and action orchestration** handled by the `orchestrator` microservice.
5. **Remediation** via REST tool integrations (`/tools/prom`, `/tools/k8s`, `/tools/es`, `/tools/netprobe`). Implementations of these tools are expected to be provided by downstream platform teams.

## Microservice responsibilities

| Service | Responsibility | Interfaces |
| ------- | -------------- | ---------- |
| `ingest` | Polls mailboxes, validates webhooks, transforms messages into events and forwards them to the orchestrator. | `POST /events/email`, `POST /webhook/alertmanager`, `POST /msgraph/webhook`, metrics exporter on port `9301`. |
| `rca` | Wraps Qwen-Plus API with offline fallback. | `POST /rca`, metrics exporter on port `9302`. |
| `orchestrator` | Deduplicates events, calls RCA service, maps decisions to remediation policies and tracks approvals. | `POST /events`, `POST /approvals/{id}`, `POST /policies/reload`, metrics exporter on port `9303`. |

## Operating procedures

### Configuration

* Configuration is stored under the `config/` directory and mounted into each container read-only.
* Environment-sensitive values (secrets, tenant identifiers, endpoints) are injected through environment variables and expanded at runtime.
* Policy definitions live under `policies/` and are hot-reloaded every two minutes by default.

### Deploying locally

```bash
docker compose up --build
```

Expose required environment variables prior to launching (e.g. `export QWEN_API_KEY=...`).

### On-call checklist

1. **Service health** – Verify `/healthz` endpoints and Prometheus metrics exporters (ports `9301-9303`).
2. **Mailbox connectivity** – Ensure IMAP or Graph credentials are valid; check logs for `imap.poll.error` or `graph.payload` warnings.
3. **RCA fallbacks** – If `QWEN_API_KEY` is missing, the RCA service will emit warnings and produce deterministic offline plans.
4. **Policy approvals** – Monitor logs for `orchestrator.approval_required` entries and trigger approval via `POST /approvals/{request_id}`.
5. **Knowledge base updates** – Persist RCA outcomes and policy actions into the organisation's knowledge base after incident closure.

### Disaster recovery

* The orchestrator deduplication cache prevents alert storms from overwhelming the RCA service; its TTL and capacity can be tuned in `config/orchestrator.yaml`.
* Restarting services is safe; IMAP pollers resume from unseen messages and policies are reloaded at startup.
* Ensure secrets are rotated regularly and stored in Vault/Kubernetes Secret resources.

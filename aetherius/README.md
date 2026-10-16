# Aetherius Backend (`aetherius/`)

This README is scoped to the operational backend module only.

For product positioning, deliverable scope, and detection track record, see the root `README.md`.

## Scope

`aetherius/` contains the pilot operations backbone:

- FastAPI API and operator console routes
- PostgreSQL models and migrations
- Celery workers and scheduling
- Signal drafting, review workflow, quality gates, and delivery services
- Jinja templates for console, email, and PDF outputs

## Directory Overview

```text
aetherius/
  app/
    api/
    core/
    db/
    models/
    schemas/
    services/
    templates/
    workers/
  alembic/
  tests/
```

## Local Backend Bring-Up

1. Start infrastructure from repo root:

```bash
docker compose -f docker/docker-compose.yml up -d
```

2. Apply migrations:

```bash
cd aetherius
python -m alembic upgrade head
```

3. Verify health:

- `GET http://localhost:8000/health`

## Auth and Role Model

- Bootstrap: `POST /api/v1/auth/bootstrap-admin`
- Login: `POST /api/v1/auth/login`
- Roles: `admin`, `analyst`, `viewer`

All protected routes require bearer authentication and role checks.

Client-scoped endpoints (reporting, delivery) allow admins on every client and
other operators only on clients assigned to them:

- Assign: `POST /api/v1/auth/assignments` (admin) with `operator_user_id`, `client_id`
- Unassign: `DELETE /api/v1/auth/assignments/{assignment_id}` (admin)

Delivering a brief requires `admin`, or an `analyst` assigned to that client.

## Scheduled Jobs (Celery beat)

| Job | Schedule | What it does |
| --- | --- | --- |
| `ingest_watchlist_sources` | hourly at :05 | EDGAR filings + 24h GDELT news per active ticker -> evidence -> signals |
| `briefing_daily_sweep` | 08:00 | Draft a daily brief per client for review |
| `briefing_weekly_sweep` | Mon 09:00 | Draft a weekly summary per client for review |
| `delivery_retry_failed` | every 5 min | Re-attempt failed deliveries (re-running every gate) with 5/10/20 min backoff |
| `dead_letter_requeue` | every 15 min | Move deliveries that exhausted retries to `dead_letter` |
| `observability_health_alerts` | every 10 min | Log a warning when failed/dead-letter/pending-review counts cross thresholds |
| `retention_archive_cleanup` | 02:00 | Mark observations older than 180 days `archived` (rows are kept for audit) |

Signals are only raised automatically for evidence that would ship
(elevated/high severity *and* adverse language in the source), using the same
scoring as `simulations/backtest/run_backtest.py`.

## Delivery Modes

- Local: Mailpit SMTP (`localhost:1025`, UI `http://localhost:8025`)
- Pilot/production: Postmark SMTP

## Ownership Boundary

- Update this subtree for backend workflow changes (auth, review, delivery, audit).
- The historical detection-timing evidence lives in root `simulations/backtest/`.

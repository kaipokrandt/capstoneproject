# Backup, Restore, and Observability

Last Verified: 2026-04-11  
Owner: Platform Operations  
Code References: `wbs/wbs/models.py`, `wbs/wbs/reports_views.py`  
Test References: `wbs/wbs/tests/test_reports_api.py`

## Backup Scope
- Database contents (all entities including sessions/metrics/reports/annotations/preferences).
- File system artifacts: `generated_reports/`.
- Environment config snapshot (without plaintext secrets in shared channels).

## Backup Procedure (Postgres)
```bash
pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql
```
Archive `generated_reports/` with same timestamp as DB dump.

## Restore Procedure
1. Stop app writes.
2. Restore DB dump.
3. Restore `generated_reports/` archive.
4. Run `python wbs/manage.py check`.
5. Validate key flows: login, list sessions, report preview/download.

## Data Integrity Verification
- Compare counts from `/api/overview/` pre/post restore.
- Validate latest session and latest report ids.
- Spot-check report download and FHIR export retrieval.

## Observability Baseline
- Track:
- API error rate by endpoint
- session frame ingest latency
- report generation latency
- DB connection errors
- authentication failure spikes
- Log minimum fields: request id, user id, endpoint, status, latency, error detail.

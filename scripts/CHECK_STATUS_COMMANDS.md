# Check Status Commands

## Video Models

```bash
# List all video models
ENV=staging uv run python scripts/check_status.py models

# List recent 5 models
ENV=staging uv run python scripts/check_status.py models --recent 5

# Filter by status
ENV=staging uv run python scripts/check_status.py models --status pending
ENV=staging uv run python scripts/check_status.py models --status processing
ENV=staging uv run python scripts/check_status.py models --status completed
ENV=staging uv run python scripts/check_status.py models --status failed

# Filter by user email
ENV=staging uv run python scripts/check_status.py models --email user@example.com

# Check specific model by ID
ENV=staging uv run python scripts/check_status.py models --id <uuid>
```

## Avatar Jobs

```bash
# List all avatar jobs
ENV=staging uv run python scripts/check_status.py jobs

# List recent 5 jobs
ENV=staging uv run python scripts/check_status.py jobs --recent 5

# Filter by status
ENV=staging uv run python scripts/check_status.py jobs --status pending
ENV=staging uv run python scripts/check_status.py jobs --status processing
ENV=staging uv run python scripts/check_status.py jobs --status completed
ENV=staging uv run python scripts/check_status.py jobs --status failed

# Filter by user email
ENV=staging uv run python scripts/check_status.py jobs --email user@example.com

# Check specific job by ID
ENV=staging uv run python scripts/check_status.py jobs --id <uuid>
```

## Logs (via check_status.py)

```bash
# View logs for avatar jobs
ENV=staging uv run python scripts/check_status.py logs
```

## LiveTalking Logs (on server)

```bash
# View log for a specific avatar job (on the server running LiveTalking)
cat /tmp/avatar_jobs/<job_id>.log

# Tail log in real-time while job is running
tail -f /tmp/avatar_jobs/<job_id>.log

# List all job logs
ls -la /tmp/avatar_jobs/*.log

# Search for errors in all job logs
grep -i "error\|failed" /tmp/avatar_jobs/*.log
```

## Local Environment

Replace `ENV=staging` with `ENV=local` for local database.

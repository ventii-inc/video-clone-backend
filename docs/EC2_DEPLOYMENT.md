# EC2 Deployment Guide

This guide covers deploying the Video Clone Backend on an Ubuntu EC2 instance.

---

## EC2 Instance Details

| Field | Value |
|-------|-------|
| Instance ID | `i-01da999a687cb411b` |
| Name | `livetalking-test` |
| Public IP | `43.207.65.6` |
| Type | `t3.micro` |
| Region | `ap-northeast-1` (Tokyo) |
| OS | Ubuntu 24.04 |
| Key Pair | `redash` |

---

## 1. Connect to EC2

```bash
ssh -i ~/.ssh/redash.pem ubuntu@43.207.65.6
```

---

## 2. Install System Dependencies

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv python3-dev git ffmpeg libsm6 libxext6 libgl1
```

---

## 3. Install uv (Python Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

---

## 4. Configure Git Credentials

```bash
git config --global credential.helper store
```

---

## 5. Clone the Repository

```bash
cd ~
git clone https://github.com/ventii-inc/video-clone-backend.git
cd video-clone-backend
```

---

## 6. Install Python Dependencies

```bash
uv sync
uv add aiodns  # For async DNS resolution
```

---

## 7. Setup Environment File

Create or copy `.env.staging`:

```bash
cat > .env.staging << 'EOF'
# Staging Environment
DB_NAME=video_clone_staging
DB_USER=dbadmin
DB_PASSWORD=<your-password>
DB_HOST=video-clone-stg-cluster.cluster-c5rlur1mgrap.ap-northeast-1.rds.amazonaws.com
DB_PORT=5432

ENV=staging
DEBUG=true

FIREBASE_CREDENTIALS_FILE=firebase-staging.json

# AWS S3 Configuration
S3_AWS_REGION=ap-northeast-1
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
S3_BUCKET_NAME=video-clone
S3_PRESIGNED_URL_EXPIRATION=3600
S3_VIDEO_STREAMING_EXPIRATION=21600
S3_UPLOAD_TIMEOUT=300

# Avatar Job Queue
AVATAR_API_KEY=<your-api-key>
AVATAR_MAX_CONCURRENT=3

# RunPod Configuration
RUNPOD_API_KEY=<your-runpod-key>
RUNPOD_ENDPOINT_ID=<your-endpoint-id>
EOF
```

Also copy the Firebase credentials file:
```bash
# Copy firebase-staging.json to the server
scp -i ~/.ssh/redash.pem firebase-staging.json ubuntu@43.207.65.6:~/video-clone-backend/
```

---

## 8. Run the Server

### Start in Background

```bash
cd ~/video-clone-backend
pkill -f uvicorn  # Kill any existing server
nohup env ENV=staging uv run uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
```

### Check Health

```bash
curl localhost:8000/health
```

Expected response:
```json
{"status":"healthy","database":"connected"}
```

### View Logs

```bash
tail -f server.log
```

---

## 9. Server Management

### Restart Server

```bash
pkill -f uvicorn
cd ~/video-clone-backend
nohup env ENV=staging uv run uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
```

### Stop Server

```bash
pkill -f uvicorn
```

### Check if Running

```bash
ps aux | grep uvicorn
```

---

## 10. EC2 Instance Management

### Stop Instance (to save costs)

```bash
aws ec2 stop-instances --region ap-northeast-1 --instance-ids i-01da999a687cb411b
```

### Start Instance

```bash
aws ec2 start-instances --region ap-northeast-1 --instance-ids i-01da999a687cb411b
```

### Check Status

```bash
aws ec2 describe-instances --region ap-northeast-1 --instance-ids i-01da999a687cb411b \
  --query 'Reservations[0].Instances[0].[State.Name,PublicIpAddress]' --output text
```

> **Note:** Public IP may change after stopping/starting. Consider using an Elastic IP for a fixed address.

---

## 11. Database Migrations

```bash
cd ~/video-clone-backend
ENV=staging uv run alembic upgrade head
```

---

## Security Groups

The following ports need to be open:

| Port | Purpose | Security Group |
|------|---------|----------------|
| 22 | SSH | EC2 SG |
| 8000 | API | EC2 SG |
| 5432 | PostgreSQL (EC2 IP only) | RDS SG |

---

## Troubleshooting

### DNS Resolution Error

If you see "Temporary failure in name resolution":

```bash
uv add aiodns
# Then restart the server
```

### Database Connection Failed

1. Check RDS security group allows EC2's public IP on port 5432
2. Verify `.env.staging` has correct DB credentials
3. Test connection: `nc -zv <rds-endpoint> 5432`

### Server Won't Start

Check logs:
```bash
cat server.log
```

Common issues:
- Missing environment variables
- Port already in use: `sudo lsof -i :8000`
- Missing dependencies: `uv sync`

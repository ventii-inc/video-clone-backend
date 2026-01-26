#!/usr/bin/env python3
"""
Status Check Script

Check video model, avatar job, and generated video status directly from the database.
Useful for debugging without needing API authentication.

Usage:
    # List all video models (avatar training)
    ENV=staging uv run python scripts/check_status.py models

    # List models with specific status
    ENV=staging uv run python scripts/check_status.py models --status processing

    # List avatar jobs
    ENV=staging uv run python scripts/check_status.py jobs

    # Check specific model by ID
    ENV=staging uv run python scripts/check_status.py models --id <uuid>

    # Filter by user email
    ENV=staging uv run python scripts/check_status.py models --email user@example.com

    # Show recent activity (last N items)
    ENV=staging uv run python scripts/check_status.py models --recent 5

    # Show avatar job output logs (most recent job)
    ENV=staging uv run python scripts/check_status.py logs

    # Show logs for specific job
    ENV=staging uv run python scripts/check_status.py logs --id <uuid>

    # Show all lines (not just last 100)
    ENV=staging uv run python scripts/check_status.py logs --tail 0

    # Show video generation output logs (most recent video)
    ENV=staging uv run python scripts/check_status.py genlogs

    # Show generation logs for specific video
    ENV=staging uv run python scripts/check_status.py genlogs --id <uuid>

    # List generated videos
    ENV=staging uv run python scripts/check_status.py generations

    # List generations with specific status
    ENV=staging uv run python scripts/check_status.py generations --status processing

    # Check specific generation by ID
    ENV=staging uv run python scripts/check_status.py generations --id <uuid>

    # Filter generations by user email
    ENV=staging uv run python scripts/check_status.py generations --email user@example.com
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment from .env file
from dotenv import load_dotenv

env_file = os.getenv("ENV", "local")
load_dotenv(f".env.{env_file}")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.models import AvatarJob, GeneratedVideo, User, VideoModel


def get_db_session() -> Session:
    """Create a sync database session."""
    db_port = os.getenv("DB_PORT", "5432")
    if db_port == "None" or not db_port:
        db_port = "5432"

    database_url = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{db_port}/{os.getenv('DB_NAME')}"
    )
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def format_datetime(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def truncate(s: str, length: int = 20) -> str:
    """Truncate string to specified length."""
    if s is None:
        return "-"
    if len(s) <= length:
        return s
    return s[: length - 3] + "..."


def list_video_models(
    db: Session,
    status: Optional[str] = None,
    email: Optional[str] = None,
    model_id: Optional[str] = None,
    recent: Optional[int] = None,
):
    """List video models with optional filters."""
    query = select(VideoModel, User).join(User, VideoModel.user_id == User.id)

    # Apply filters
    if status:
        query = query.where(VideoModel.status == status)
    if email:
        query = query.where(User.email == email)
    if model_id:
        try:
            uuid_id = UUID(model_id)
            query = query.where(VideoModel.id == uuid_id)
        except ValueError:
            print(f"Error: Invalid UUID format: {model_id}")
            return

    # Order by created_at descending
    query = query.order_by(VideoModel.created_at.desc())

    # Limit if recent is specified
    if recent:
        query = query.limit(recent)

    results = db.execute(query).all()

    if not results:
        print("No video models found matching criteria.")
        return

    # Header
    title = "Video Models"
    if email:
        title += f" ({email})"
    if status:
        title += f" [status={status}]"

    print(f"\n{title}")
    print("=" * 100)
    print(
        f"{'ID':<36}  {'Name':<20}  {'Status':<12}  {'Error':<15}  {'Created'}"
    )
    print("-" * 100)

    for video_model, user in results:
        error_msg = truncate(video_model.error_message, 15) if video_model.error_message else "-"
        print(
            f"{str(video_model.id):<36}  "
            f"{truncate(video_model.name, 20):<20}  "
            f"{video_model.status:<12}  "
            f"{error_msg:<15}  "
            f"{format_datetime(video_model.created_at)}"
        )

    print(f"\nTotal: {len(results)} model(s)")

    # Show additional details for single model
    if model_id and len(results) == 1:
        video_model, user = results[0]
        print(f"\nDetails for {video_model.id}:")
        print(f"  User Email: {user.email}")
        print(f"  Source Video Key: {video_model.source_video_key or '-'}")
        print(f"  Model Data Key: {video_model.model_data_key or '-'}")
        print(f"  Local Video Path: {video_model.local_video_path or '-'}")
        print(f"  Processing Started: {format_datetime(video_model.processing_started_at)}")
        print(f"  Processing Completed: {format_datetime(video_model.processing_completed_at)}")
        if video_model.error_message:
            print(f"  Error Message: {video_model.error_message}")


def list_avatar_jobs(
    db: Session,
    status: Optional[str] = None,
    email: Optional[str] = None,
    job_id: Optional[str] = None,
    recent: Optional[int] = None,
):
    """List avatar jobs with optional filters."""
    query = (
        select(AvatarJob, VideoModel, User)
        .join(VideoModel, AvatarJob.video_model_id == VideoModel.id)
        .join(User, AvatarJob.user_id == User.id)
    )

    # Apply filters
    if status:
        query = query.where(AvatarJob.status == status)
    if email:
        query = query.where(User.email == email)
    if job_id:
        try:
            uuid_id = UUID(job_id)
            query = query.where(AvatarJob.id == uuid_id)
        except ValueError:
            print(f"Error: Invalid UUID format: {job_id}")
            return

    # Order by created_at descending
    query = query.order_by(AvatarJob.created_at.desc())

    # Limit if recent is specified
    if recent:
        query = query.limit(recent)

    results = db.execute(query).all()

    if not results:
        print("No avatar jobs found matching criteria.")
        return

    # Header
    title = "Avatar Jobs"
    if email:
        title += f" ({email})"
    if status:
        title += f" [status={status}]"

    print(f"\n{title}")
    print("=" * 120)
    print(
        f"{'Job ID':<36}  {'Model ID':<36}  {'Status':<12}  {'Attempts':<10}  {'Created'}"
    )
    print("-" * 120)

    for job, video_model, user in results:
        print(
            f"{str(job.id):<36}  "
            f"{str(job.video_model_id):<36}  "
            f"{job.status:<12}  "
            f"{job.attempts}/{job.max_attempts:<7}  "
            f"{format_datetime(job.created_at)}"
        )

    print(f"\nTotal: {len(results)} job(s)")

    # Show additional details for single job
    if job_id and len(results) == 1:
        job, video_model, user = results[0]
        print(f"\nDetails for {job.id}:")
        print(f"  User Email: {user.email}")
        print(f"  Video Model Name: {video_model.name}")
        print(f"  RunPod Job ID: {job.runpod_job_id or '-'}")
        print(f"  PID: {job.pid or '-'}")
        print(f"  Output File: {job.output_file or '-'}")
        print(f"  Started At: {format_datetime(job.started_at)}")
        print(f"  Completed At: {format_datetime(job.completed_at)}")
        print(f"  Avatar S3 Key: {job.avatar_s3_key or '-'}")
        if job.error_message:
            print(f"  Error Message: {job.error_message}")


def show_job_logs(
    db: Session,
    job_id: Optional[str] = None,
    tail: int = 100,
):
    """Show logs for a job's output file."""
    query = (
        select(AvatarJob, VideoModel, User)
        .join(VideoModel, AvatarJob.video_model_id == VideoModel.id)
        .join(User, AvatarJob.user_id == User.id)
    )

    if job_id:
        try:
            uuid_id = UUID(job_id)
            query = query.where(AvatarJob.id == uuid_id)
        except ValueError:
            print(f"Error: Invalid UUID format: {job_id}")
            return
    else:
        # Get most recent job with an output file
        query = query.where(AvatarJob.output_file.isnot(None))
        query = query.order_by(AvatarJob.created_at.desc()).limit(1)

    result = db.execute(query).first()

    if not result:
        print("No job found matching criteria.")
        return

    job, video_model, user = result

    print(f"\nJob: {job.id}")
    print(f"Model: {video_model.name}")
    print(f"User: {user.email}")
    print(f"Status: {job.status}")
    print(f"PID: {job.pid or '-'}")
    print(f"Output File: {job.output_file or '-'}")
    print("=" * 80)

    if not job.output_file:
        print("No output file path recorded for this job.")
        return

    # Read the output file
    output_path = Path(job.output_file)
    if not output_path.exists():
        print(f"Output file not found: {job.output_file}")
        return

    try:
        with open(output_path, "r") as f:
            content = f.read()

        if not content:
            print("(empty file)")
            return

        lines = content.splitlines()
        if tail and len(lines) > tail:
            print(f"(showing last {tail} lines, total {len(lines)} lines)\n")
            lines = lines[-tail:]

        for line in lines:
            print(line)

    except Exception as e:
        print(f"Error reading output file: {e}")


def show_generation_logs(
    db: Session,
    video_id: Optional[str] = None,
    tail: int = 100,
):
    """Show logs for a generated video's output file."""
    query = select(GeneratedVideo, User).join(User, GeneratedVideo.user_id == User.id)

    if video_id:
        try:
            uuid_id = UUID(video_id)
            query = query.where(GeneratedVideo.id == uuid_id)
        except ValueError:
            print(f"Error: Invalid UUID format: {video_id}")
            return
    else:
        # Get most recent video with an output file
        query = query.where(GeneratedVideo.output_file.isnot(None))
        query = query.order_by(GeneratedVideo.created_at.desc()).limit(1)

    result = db.execute(query).first()

    if not result:
        print("No generated video found matching criteria.")
        return

    video, user = result

    print(f"\nVideo: {video.id}")
    print(f"Title: {video.title or 'Untitled'}")
    print(f"User: {user.email}")
    print(f"Status: {video.status}")
    print(f"Stage: {video.processing_stage or '-'}")
    print(f"Output File: {video.output_file or '-'}")
    print("=" * 80)

    if not video.output_file:
        print("No output file path recorded for this video.")
        return

    # Read the output file
    output_path = Path(video.output_file)
    if not output_path.exists():
        print(f"Output file not found: {video.output_file}")
        return

    try:
        with open(output_path, "r") as f:
            content = f.read()

        if not content:
            print("(empty file)")
            return

        lines = content.splitlines()
        if tail and len(lines) > tail:
            print(f"(showing last {tail} lines, total {len(lines)} lines)\n")
            lines = lines[-tail:]

        for line in lines:
            print(line)

    except Exception as e:
        print(f"Error reading output file: {e}")


def list_generated_videos(
    db: Session,
    status: Optional[str] = None,
    email: Optional[str] = None,
    video_id: Optional[str] = None,
    recent: Optional[int] = None,
):
    """List generated videos with optional filters."""
    query = select(GeneratedVideo, User).join(User, GeneratedVideo.user_id == User.id)

    # Apply filters
    if status:
        query = query.where(GeneratedVideo.status == status)
    if email:
        query = query.where(User.email == email)
    if video_id:
        try:
            uuid_id = UUID(video_id)
            query = query.where(GeneratedVideo.id == uuid_id)
        except ValueError:
            print(f"Error: Invalid UUID format: {video_id}")
            return

    # Order by created_at descending
    query = query.order_by(GeneratedVideo.created_at.desc())

    # Limit if recent is specified
    if recent:
        query = query.limit(recent)

    results = db.execute(query).all()

    if not results:
        print("No generated videos found matching criteria.")
        return

    # Header
    title = "Generated Videos"
    if email:
        title += f" ({email})"
    if status:
        title += f" [status={status}]"

    print(f"\n{title}")
    print("=" * 120)
    print(
        f"{'ID':<36}  {'Title':<20}  {'Status':<12}  {'Stage':<12}  {'Progress':<8}  {'Created'}"
    )
    print("-" * 120)

    for video, user in results:
        progress_str = f"{video.progress_percent}%" if video.progress_percent is not None else "-"
        print(
            f"{str(video.id):<36}  "
            f"{truncate(video.title or 'Untitled', 20):<20}  "
            f"{video.status:<12}  "
            f"{video.processing_stage or '-':<12}  "
            f"{progress_str:<8}  "
            f"{format_datetime(video.created_at)}"
        )

    print(f"\nTotal: {len(results)} video(s)")

    # Show additional details for single video
    if video_id and len(results) == 1:
        video, user = results[0]
        print(f"\nDetails for {video.id}:")
        print(f"  User Email: {user.email}")
        print(f"  Title: {video.title or '-'}")
        print(f"  Input Text: {truncate(video.input_text, 100) if video.input_text else '-'}")
        print(f"  Language: {video.input_text_language or '-'}")
        print(f"  Resolution: {video.resolution or '-'}")
        print(f"  Duration: {video.duration_seconds}s" if video.duration_seconds else "  Duration: -")
        print(f"  Credits Used: {video.credits_used}")
        print(f"  Video Model ID: {video.video_model_id or '-'}")
        print(f"  Voice Model ID: {video.voice_model_id or '-'}")
        print(f"  Output Video Key: {video.output_video_key or '-'}")
        print(f"  Output File: {video.output_file or '-'}")
        print(f"  Processing Started: {format_datetime(video.processing_started_at)}")
        print(f"  Processing Completed: {format_datetime(video.processing_completed_at)}")
        if video.error_message:
            print(f"  Error Message: {video.error_message}")


def main():
    parser = argparse.ArgumentParser(
        description="Check video model and avatar job status from the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Models subcommand
    models_parser = subparsers.add_parser("models", help="List video models")
    models_parser.add_argument(
        "--status",
        type=str,
        choices=["pending", "uploading", "processing", "completed", "failed"],
        help="Filter by status",
    )
    models_parser.add_argument(
        "--email",
        type=str,
        help="Filter by user email",
    )
    models_parser.add_argument(
        "--id",
        type=str,
        dest="model_id",
        help="Show specific model by ID",
    )
    models_parser.add_argument(
        "--recent",
        type=int,
        help="Show only the N most recent items",
    )

    # Jobs subcommand
    jobs_parser = subparsers.add_parser("jobs", help="List avatar jobs")
    jobs_parser.add_argument(
        "--status",
        type=str,
        choices=["pending", "processing", "completed", "failed"],
        help="Filter by status",
    )
    jobs_parser.add_argument(
        "--email",
        type=str,
        help="Filter by user email",
    )
    jobs_parser.add_argument(
        "--id",
        type=str,
        dest="job_id",
        help="Show specific job by ID",
    )
    jobs_parser.add_argument(
        "--recent",
        type=int,
        help="Show only the N most recent items",
    )

    # Logs subcommand
    logs_parser = subparsers.add_parser("logs", help="Show avatar job output logs")
    logs_parser.add_argument(
        "--id",
        type=str,
        dest="job_id",
        help="Show logs for specific job (default: most recent job with output)",
    )
    logs_parser.add_argument(
        "--tail",
        type=int,
        default=100,
        help="Number of lines to show (default: 100, use 0 for all)",
    )

    # Genlogs subcommand
    genlogs_parser = subparsers.add_parser("genlogs", help="Show video generation output logs")
    genlogs_parser.add_argument(
        "--id",
        type=str,
        dest="video_id",
        help="Show logs for specific video (default: most recent video with output)",
    )
    genlogs_parser.add_argument(
        "--tail",
        type=int,
        default=100,
        help="Number of lines to show (default: 100, use 0 for all)",
    )

    # Generations subcommand
    gen_parser = subparsers.add_parser("generations", help="List generated videos")
    gen_parser.add_argument(
        "--status",
        type=str,
        choices=["queued", "processing", "completed", "failed"],
        help="Filter by status",
    )
    gen_parser.add_argument(
        "--email",
        type=str,
        help="Filter by user email",
    )
    gen_parser.add_argument(
        "--id",
        type=str,
        dest="video_id",
        help="Show specific generated video by ID",
    )
    gen_parser.add_argument(
        "--recent",
        type=int,
        help="Show only the N most recent items",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Show which environment we're using
    print(f"Environment: {env_file}")
    print(f"Database: {os.getenv('DB_HOST')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME')}")

    try:
        db = get_db_session()

        if args.command == "models":
            list_video_models(
                db,
                status=args.status,
                email=args.email,
                model_id=args.model_id,
                recent=args.recent,
            )
        elif args.command == "jobs":
            list_avatar_jobs(
                db,
                status=args.status,
                email=args.email,
                job_id=args.job_id,
                recent=args.recent,
            )
        elif args.command == "logs":
            show_job_logs(
                db,
                job_id=args.job_id,
                tail=args.tail,
            )
        elif args.command == "genlogs":
            show_generation_logs(
                db,
                video_id=args.video_id,
                tail=args.tail,
            )
        elif args.command == "generations":
            list_generated_videos(
                db,
                status=args.status,
                email=args.email,
                video_id=args.video_id,
                recent=args.recent,
            )

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

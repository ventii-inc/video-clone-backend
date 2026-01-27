"""Voice models router for CRUD operations"""

import asyncio
import os
import tempfile
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db import get_db
from app.models import User, VoiceModel
from app.models.voice_model import ModelStatus, SourceType
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.services.ai import ai_service
from app.services.fish_audio import fish_audio_service
from app.schemas.common import MessageResponse, PaginationMeta, UploadInfo
from app.schemas.voice_model import (
    VoiceModelCreate,
    VoiceModelResponse,
    VoiceModelBrief,
    VoiceModelListResponse,
    VoiceModelUpdate,
    VoiceModelCreateResponse,
    VoiceModelUploadCompleteRequest,
    DirectVoiceUploadResponse,
)
from app.utils import logger
from app.utils.constants import MAX_VOICE_MODELS_PER_USER

router = APIRouter(prefix="/models/voice", tags=["Voice Models"])


ALLOWED_AUDIO_TYPES = [
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/aac",
    "audio/webm",
]
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


@router.get("", response_model=VoiceModelListResponse)
async def list_voice_models(
    status: str | None = None,
    source_type: str | None = None,
    page: int = 1,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List user's voice models with optional filters.
    """
    query = select(VoiceModel).where(VoiceModel.user_id == user.id)

    if status:
        query = query.where(VoiceModel.status == status)

    if source_type:
        query = query.where(VoiceModel.source_type == source_type)

    # Get total count - build count query directly with same filters (more efficient)
    count_query = select(func.count(VoiceModel.id)).where(VoiceModel.user_id == user.id)
    if status:
        count_query = count_query.where(VoiceModel.status == status)
    if source_type:
        count_query = count_query.where(VoiceModel.source_type == source_type)
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    query = query.order_by(VoiceModel.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    models = result.scalars().all()

    return VoiceModelListResponse(
        models=[VoiceModelBrief.model_validate(m) for m in models],
        pagination=PaginationMeta(
            page=page,
            limit=limit,
            total=total,
            total_pages=(total + limit - 1) // limit,
        ),
    )


@router.get("/{model_id}", response_model=VoiceModelResponse)
async def get_voice_model(
    model_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get voice model details by ID.
    """
    result = await db.execute(
        select(VoiceModel).where(
            VoiceModel.id == model_id,
            VoiceModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice model not found",
        )

    return VoiceModelResponse.model_validate(model)


@router.post("", response_model=VoiceModelCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_voice_model(
    data: VoiceModelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new voice model and get presigned upload URL.
    """
    # Check model creation limit (bypass if user has flag set)
    if not user.bypass_model_limit:
        count_result = await db.execute(
            select(func.count()).where(VoiceModel.user_id == user.id)
        )
        current_count = count_result.scalar()
        if current_count >= MAX_VOICE_MODELS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum number of voice models ({MAX_VOICE_MODELS_PER_USER}) reached",
            )

    # Validate content type
    if data.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(ALLOWED_AUDIO_TYPES)}",
        )

    # Validate file size
    if data.file_size_bytes > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Create model record
    model = VoiceModel(
        user_id=user.id,
        name=data.name,
        file_size_bytes=data.file_size_bytes,
        source_type=data.source_type,
        status=ModelStatus.PENDING.value,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)

    # Generate S3 key and presigned URL
    s3_key = s3_service.generate_s3_key(
        user_id=str(user.id),
        filename=data.file_name,
        media_type="voice-models",
        unique_id=str(model.id),
    )

    presigned_url = await s3_service.generate_presigned_upload_url(
        s3_key=s3_key,
        content_type=data.content_type,
        expiration=3600,
    )

    # Store S3 key
    model.source_audio_key = s3_key
    await db.commit()

    return VoiceModelCreateResponse(
        model=VoiceModelBrief.model_validate(model),
        upload=UploadInfo(
            presigned_url=presigned_url,
            s3_key=s3_key,
            expires_in_seconds=3600,
        ),
    )


@router.post("/upload", response_model=DirectVoiceUploadResponse, status_code=status.HTTP_201_CREATED)
async def direct_upload_voice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Audio file to upload"),
    name: str = Form(..., min_length=1, max_length=100, description="Model name"),
    duration_seconds: int = Form(..., gt=0, description="Audio duration in seconds"),
    source_type: str = Form(default="upload", description="Source type: upload or recording"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload audio directly to server and trigger voice cloning.

    Flow:
    1. Validate and save audio file locally (temp)
    2. Create model record
    3. Trigger parallel background tasks:
       - Upload audio to S3
       - Process voice (trim + Fish Audio cloning)
    """
    # Check model creation limit (bypass if user has flag set)
    if not user.bypass_model_limit:
        count_result = await db.execute(
            select(func.count()).where(VoiceModel.user_id == user.id)
        )
        current_count = count_result.scalar()
        if current_count >= MAX_VOICE_MODELS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum number of voice models ({MAX_VOICE_MODELS_PER_USER}) reached",
            )

    # Validate content type
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(ALLOWED_AUDIO_TYPES)}",
        )

    # Validate source_type
    if source_type not in ["upload", "recording"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_type must be 'upload' or 'recording'",
        )

    # Read file to get size and content
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Create model record
    model = VoiceModel(
        user_id=user.id,
        name=name,
        file_size_bytes=file_size,
        duration_seconds=duration_seconds,
        source_type=source_type,
        status=ModelStatus.UPLOADING.value,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)

    # Save file to temp directory
    ext = os.path.splitext(file.filename or "audio.mp3")[1] or ".mp3"
    temp_dir = tempfile.gettempdir()
    local_path = os.path.join(temp_dir, f"voice_{model.id}{ext}")

    with open(local_path, "wb") as f:
        f.write(content)

    logger.info(f"Saved voice audio to temp: {local_path}")

    # Generate S3 key for the audio
    s3_key = s3_service.generate_s3_key(
        user_id=str(user.id),
        filename=file.filename or f"{model.id}.mp3",
        media_type="voice-models",
        unique_id=str(model.id),
    )
    model.source_audio_key = s3_key
    await db.commit()

    # Trigger parallel S3 upload and voice processing
    background_tasks.add_task(
        process_direct_voice_upload_task,
        model_id=model.id,
        local_path=local_path,
        s3_key=s3_key,
    )

    return DirectVoiceUploadResponse(
        model=VoiceModelBrief.model_validate(model),
        message="Audio uploaded, voice cloning started",
    )


async def process_direct_voice_upload_task(
    model_id: UUID,
    local_path: str,
    s3_key: str,
):
    """
    Background task to run S3 upload and voice processing in parallel.
    """
    from app.db import get_db_session

    async def upload_to_s3():
        """Upload the local audio file to S3."""
        try:
            success = await s3_service.upload_file(local_path, s3_key)
            if success:
                logger.info(f"Voice S3 upload complete: {s3_key}")
                # Update model with presigned URL
                async with get_db_session() as db:
                    result = await db.execute(
                        select(VoiceModel).where(VoiceModel.id == model_id)
                    )
                    model = result.scalar_one_or_none()
                    if model:
                        model.source_audio_url = await s3_service.generate_presigned_url(s3_key)
                        await db.commit()
            else:
                logger.error(f"Voice S3 upload failed: {s3_key}")
        except Exception as e:
            logger.error(f"Voice S3 upload error: {e}")

    async def process_voice():
        """Process voice model (trim + Fish Audio cloning) using local file."""
        async with get_db_session() as db:
            await ai_service.process_voice_model(model_id, db, local_audio_path=local_path)

    # Run S3 upload and voice processing in parallel
    try:
        await asyncio.gather(
            upload_to_s3(),
            process_voice(),
            return_exceptions=True,
        )
    finally:
        # Clean up temp file
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"Cleaned up temp file: {local_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up temp file {local_path}: {e}")


@router.post("/{model_id}/upload-complete", response_model=dict)
async def complete_upload(
    model_id: UUID,
    data: VoiceModelUploadCompleteRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark upload as complete and trigger AI processing.
    """
    result = await db.execute(
        select(VoiceModel).where(
            VoiceModel.id == model_id,
            VoiceModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice model not found",
        )

    if model.status != ModelStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete upload for model in '{model.status}' status",
        )

    # Verify file exists in S3
    if model.source_audio_key:
        exists = await s3_service.file_exists(model.source_audio_key)
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload not found. Please upload the file first.",
            )

        # Get presigned URL for viewing
        model.source_audio_url = await s3_service.generate_presigned_url(model.source_audio_key)

    # Update model
    model.duration_seconds = data.duration_seconds
    model.status = ModelStatus.UPLOADING.value
    await db.commit()

    # Start AI processing in background
    background_tasks.add_task(
        process_voice_model_task,
        model_id=model.id,
    )

    return {
        "model": VoiceModelBrief.model_validate(model).model_dump(),
        "message": "Voice model is now being processed",
    }


async def process_voice_model_task(model_id: UUID):
    """Background task to process voice model."""
    from app.db import get_db_session

    async with get_db_session() as db:
        await ai_service.process_voice_model(model_id, db)


@router.patch("/{model_id}", response_model=VoiceModelResponse)
async def update_voice_model(
    model_id: UUID,
    data: VoiceModelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update voice model name and/or visibility.
    """
    result = await db.execute(
        select(VoiceModel).where(
            VoiceModel.id == model_id,
            VoiceModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice model not found",
        )

    # Check if at least one field is provided
    if data.name is None and data.visibility is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field (name or visibility) must be provided",
        )

    # Update Fish Audio model if visibility is being changed and model is completed
    if data.visibility is not None and model.reference_id and model.status == "completed":
        fish_audio_id = model.reference_id
        # Skip if it's a mock model
        if not fish_audio_id.startswith("mock://"):
            update_result = await fish_audio_service.update_model(
                model_id=fish_audio_id,
                title=data.name if data.name else None,
                visibility=data.visibility,
            )
            if not update_result.get("success"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update Fish Audio model: {update_result.get('error')}",
                )

    # Update local database
    if data.name is not None:
        model.name = data.name
    if data.visibility is not None:
        model.visibility = data.visibility

    await db.commit()
    await db.refresh(model)

    return VoiceModelResponse.model_validate(model)


@router.delete("/{model_id}", response_model=MessageResponse)
async def delete_voice_model(
    model_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a voice model.
    """
    result = await db.execute(
        select(VoiceModel).where(
            VoiceModel.id == model_id,
            VoiceModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice model not found",
        )

    # Check if model has generated videos (use count query to avoid lazy loading)
    from app.models import GeneratedVideo
    video_count_result = await db.execute(
        select(func.count(GeneratedVideo.id)).where(GeneratedVideo.voice_model_id == model_id)
    )
    if video_count_result.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete model that has generated videos",
        )

    # Delete from S3 if exists
    if model.source_audio_key:
        try:
            await s3_service.delete_file(model.source_audio_key)
        except Exception:
            pass

    await db.delete(model)
    await db.commit()

    return MessageResponse(message="Voice model deleted successfully")

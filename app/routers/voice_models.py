"""Voice models router for CRUD operations"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db import get_db
from app.models import User, VoiceModel
from app.models.voice_model import ModelStatus, SourceType
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.services.ai import ai_service
from app.schemas.common import MessageResponse, PaginationMeta, UploadInfo
from app.schemas.voice_model import (
    VoiceModelCreate,
    VoiceModelResponse,
    VoiceModelBrief,
    VoiceModelListResponse,
    VoiceModelUpdate,
    VoiceModelCreateResponse,
    VoiceModelUploadCompleteRequest,
)

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

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
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
    Update voice model name.
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

    model.name = data.name
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

    # Check if model has generated videos
    if model.generated_videos and len(model.generated_videos) > 0:
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

"""Common schemas for pagination, errors, and responses"""

from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination query parameters"""
    page: int = Field(default=1, ge=1, description="Page number")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginationMeta(BaseModel):
    """Pagination metadata in response"""
    page: int
    limit: int
    total: int
    total_pages: int


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper"""
    items: list[T]
    pagination: PaginationMeta


class ErrorDetail(BaseModel):
    """Error detail structure"""
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: ErrorDetail


class MessageResponse(BaseModel):
    """Simple message response"""
    message: str


class UploadInfo(BaseModel):
    """Presigned URL upload information"""
    presigned_url: str
    s3_key: str
    expires_in_seconds: int = 3600

"""Standardized response utilities."""

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


def success(
    data: Any = None,
    message: str = "Success",
) -> dict:
    """Create a standardized success response.

    Args:
        data: Response data payload
        message: Success message

    Returns:
        Dictionary with success response structure
    """
    response = {
        "success": True,
        "message": message,
    }
    if data is not None:
        response["data"] = data
    return response


def error_response(
    code: str,
    message: str,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    details: dict | None = None,
) -> JSONResponse:
    """Create a standardized error response.

    Args:
        code: Error code (e.g., 'VALIDATION_ERROR', 'NOT_FOUND')
        message: Human-readable error message
        status_code: HTTP status code
        details: Additional error details

    Returns:
        JSONResponse with error structure
    """
    content = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details:
        content["error"]["details"] = details

    return JSONResponse(
        status_code=status_code,
        content=content,
    )


def validation_error(
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    """Create a validation error response.

    Args:
        message: Error message
        details: Validation error details

    Returns:
        JSONResponse with 422 status
    """
    return error_response(
        code="VALIDATION_ERROR",
        message=message,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details=details,
    )


def not_found_error(
    resource: str = "Resource",
    message: str | None = None,
) -> JSONResponse:
    """Create a not found error response.

    Args:
        resource: Name of the resource that wasn't found
        message: Custom error message

    Returns:
        JSONResponse with 404 status
    """
    return error_response(
        code="NOT_FOUND",
        message=message or f"{resource} not found",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def unauthorized_error(
    message: str = "Authentication required",
) -> JSONResponse:
    """Create an unauthorized error response.

    Args:
        message: Error message

    Returns:
        JSONResponse with 401 status
    """
    return error_response(
        code="UNAUTHORIZED",
        message=message,
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


def forbidden_error(
    message: str = "You don't have permission to access this resource",
) -> JSONResponse:
    """Create a forbidden error response.

    Args:
        message: Error message

    Returns:
        JSONResponse with 403 status
    """
    return error_response(
        code="FORBIDDEN",
        message=message,
        status_code=status.HTTP_403_FORBIDDEN,
    )


def internal_error(
    message: str = "An unexpected error occurred",
) -> JSONResponse:
    """Create an internal server error response.

    Args:
        message: Error message

    Returns:
        JSONResponse with 500 status
    """
    return error_response(
        code="INTERNAL_ERROR",
        message=message,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def insufficient_credits_error(
    required: int,
    available: int,
) -> JSONResponse:
    """Create an insufficient credits error response.

    Args:
        required: Minutes required
        available: Minutes available

    Returns:
        JSONResponse with 402 status
    """
    return error_response(
        code="INSUFFICIENT_CREDITS",
        message="Not enough minutes remaining",
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        details={
            "required_minutes": required,
            "available_minutes": available,
        },
    )

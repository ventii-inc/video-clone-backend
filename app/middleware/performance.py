"""Performance monitoring middleware."""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.logger import logger


class PerformanceMiddleware(BaseHTTPMiddleware):
    """Middleware to measure and log request processing time.

    Features:
    - Measures request processing time
    - Logs slow requests (>500ms) with warning
    - Adds X-Process-Time header to responses
    - Excludes health check and docs endpoints from slow request alerts
    """

    SLOW_REQUEST_THRESHOLD = 0.5  # 500ms

    EXCLUDED_PATHS = {
        "/health",
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and measure timing.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            Response with timing header
        """
        start_time = time.perf_counter()

        # Process the request
        response = await call_next(request)

        # Calculate processing time
        process_time = time.perf_counter() - start_time

        # Add timing header
        response.headers["X-Process-Time"] = f"{process_time:.4f}"

        # Log the request
        path = request.url.path
        method = request.method

        # Skip logging for excluded paths
        if path not in self.EXCLUDED_PATHS:
            if process_time >= self.SLOW_REQUEST_THRESHOLD:
                logger.warning(
                    f"[SLOW REQUEST] {method} {path} - {process_time:.3f}s"
                )
            else:
                logger.debug(
                    f"[REQUEST] {method} {path} - {process_time:.3f}s"
                )

        return response

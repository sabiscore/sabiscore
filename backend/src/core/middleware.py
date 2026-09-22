# backend/src/core/middleware.py

from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable
import re
import time
import logging

# Configure logger
logger = logging.getLogger(__name__)


class VersionedAPIRoute(APIRoute):
    """
    Custom API route handler that extracts and stores API version from URL path.
    Supports versioned API endpoints like /api/v1/, /api/v2/, etc.
    """

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            # Get the API version from the URL path
            path = request.url.path
            version_match = re.match(r"^/api/v(\d+)/", path)

            if version_match:
                version = int(version_match.group(1))
                request.state.api_version = version
                logger.debug(f"API version {version} detected from path: {path}")
            else:
                request.state.api_version = 1  # Default to v1
                logger.debug(f"No version in path, defaulting to v1: {path}")

            # Call the original route handler
            response = await original_route_handler(request)

            # Add version header to response
            response.headers["X-API-Version"] = str(request.state.api_version)

            return response

        return custom_route_handler


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP requests and responses.
    Logs request details, response status, and processing time.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # Generate request ID for tracing
        request_id = id(request)

        # Extract client info
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else "unknown"

        # Log request details
        logger.info(
            f"[{request_id}] Incoming request: "
            f"{request.method} {request.url.path} "
            f"from {client_host}:{client_port}"
        )

        # Log query parameters if present
        if request.query_params:
            logger.debug(f"[{request_id}] Query params: {dict(request.query_params)}")

        # Log headers (exclude sensitive ones)
        sensitive_headers = {"authorization", "cookie", "x-api-key"}
        safe_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in sensitive_headers
        }
        logger.debug(f"[{request_id}] Headers: {safe_headers}")

        # Process request and measure time
        start_time = time.time()

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            # Log response
            logger.info(
                f"[{request_id}] Response: {response.status_code} "
                f"in {process_time:.4f}s"
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = str(request_id)

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"[{request_id}] Error processing request: {str(e)} "
                f"after {process_time:.4f}s",
                exc_info=True,
            )
            raise


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple rate limiting middleware (in-memory, for single-instance deployments).
    For production, consider using Redis-based rate limiting.
    """

    def __init__(self, app: ASGIApp, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):
        # Get client identifier (IP address)
        client_id = request.client.host if request.client else "unknown"

        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/ready"]:
            return await call_next(request)

        current_time = time.time()

        # Initialize or clean up old requests
        if client_id not in self.request_counts:
            self.request_counts[client_id] = []

        # Remove requests older than 1 minute
        self.request_counts[client_id] = [
            req_time
            for req_time in self.request_counts[client_id]
            if current_time - req_time < 60
        ]

        # Check rate limit
        if len(self.request_counts[client_id]) >= self.requests_per_minute:
            logger.warning(
                f"Rate limit exceeded for {client_id}: "
                f"{len(self.request_counts[client_id])} requests in last minute"
            )
            return Response(
                content='{"detail": "Rate limit exceeded. Please try again later."}',
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(self.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(current_time + 60)),
                    "Retry-After": "60",
                },
            )

        # Add current request
        self.request_counts[client_id].append(current_time)

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            self.requests_per_minute - len(self.request_counts[client_id])
        )
        response.headers["X-RateLimit-Reset"] = str(int(current_time + 60))

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    Helps protect against common web vulnerabilities.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


class CompressionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track response sizes (for monitoring).
    Actual compression should be handled by GZipMiddleware from Starlette.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Log large responses
        if hasattr(response, "body") and len(response.body) > 1_000_000:  # > 1MB
            logger.warning(
                f"Large response: {len(response.body)} bytes for "
                f"{request.method} {request.url.path}"
            )

        return response


# Export all middleware classes
__all__ = [
    "VersionedAPIRoute",
    "LoggingMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "CompressionMiddleware",
]

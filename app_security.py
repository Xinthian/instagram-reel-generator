"""Bound uploads and reject cross-site processing requests."""

import os
import threading
from urllib.parse import urlsplit

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


def normalize_host(host):
    host = (host or "").strip().lower()
    if not host:
        return ""
    if host.count(":") == 1:
        name, port = host.rsplit(":", 1)
        if port.isdigit() and port in ("80", "443"):
            return name
    return host


def allowed_request_hosts(headers):
    hosts = []
    for key in (b"x-forwarded-host", b"host"):
        raw = headers.get(key, b"").decode("ascii", "ignore")
        for part in raw.split(","):
            host = normalize_host(part)
            if host:
                hosts.append(host)
    name = os.environ.get("CODESPACE_NAME", "").strip()
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev").strip().lstrip(".")
    if name and domain:
        hosts.append(normalize_host(f"{name}-7008.{domain}"))
    return hosts


def origin_allowed(origin, headers):
    try:
        parsed = urlsplit(origin.decode("ascii"))
        if parsed.scheme not in ("http", "https"):
            return False
        return normalize_host(parsed.netloc) in allowed_request_hosts(headers)
    except (ValueError, UnicodeError, AttributeError):
        return False


class RequestBodyTooLarge(MultiPartException):
    """Also makes Starlette close any partially written multipart files."""


class RequestGuardMiddleware:
    def __init__(self, app, max_video_bytes, max_screenshot_bytes, max_jobs=1):
        if min(max_video_bytes, max_screenshot_bytes, max_jobs) <= 0:
            raise ValueError("Upload and concurrency limits must be positive")
        self.app = app
        self.limits = {
            "/api/generate": max_video_bytes + 1024 * 1024,
            "/api/extract-caption": max_screenshot_bytes + 64 * 1024,
        }
        self.jobs = threading.BoundedSemaphore(max_jobs)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        method = scope.get("method", "")
        if path == "/api/health" and method in ("GET", "HEAD"):
            return await self.app(scope, receive, send)

        async def error(status, detail, headers=None):
            await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, send)

        headers = dict(scope.get("headers", []))

        # Prevent other sites from submitting processing jobs through the browser.
        if method not in ("GET", "HEAD", "OPTIONS"):
            origin = headers.get(b"origin")
            if origin is not None and not origin_allowed(origin, headers):
                return await error(403, "Requests must come from this app's page.")
            if headers.get(b"sec-fetch-site") == b"cross-site":
                return await error(403, "Requests must come from this app's page.")

        is_job = method == "POST" and path in self.limits
        received = 0
        oversized = False
        replaced = False

        async def guarded_send(message):
            nonlocal replaced
            if is_job and oversized:
                if not replaced and message["type"] == "http.response.start":
                    replaced = True
                    await error(413, "The upload exceeds the allowed size.")
                return
            await send(message)

        if not is_job:
            return await self.app(scope, receive, guarded_send)

        limit = self.limits[path]
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if not raw_length.isdigit():
                    raise ValueError
                length = int(raw_length)
            except ValueError:
                return await error(400, "Invalid Content-Length header.")
            if length > limit:
                return await error(413, "The upload exceeds the allowed size.")
        if not self.jobs.acquire(blocking=False):
            return await error(429, "Another job is running. Try again when it finishes.", {"Retry-After": "2"})

        async def limited_receive():
            nonlocal received, oversized
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    oversized = True
                    raise RequestBodyTooLarge("The upload exceeds the allowed size.")
            return message

        try:
            await self.app(scope, limited_receive, guarded_send)
        except RequestBodyTooLarge:
            if not replaced:
                await error(413, "The upload exceeds the allowed size.")
        finally:
            self.jobs.release()

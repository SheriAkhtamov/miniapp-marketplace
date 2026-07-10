from __future__ import annotations

from typing import Optional

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from app.config import settings


router = APIRouter(tags=["hr-workspace"])

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


@router.api_route("/hr", methods=["GET", "HEAD"])
async def hr_workspace_redirect():
    return RedirectResponse(url="/hr/", status_code=307)


@router.api_route(
    "/hr/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def hr_workspace_proxy(path: str, request: Request):
    upstream_url = _build_hr_upstream_url(path, request.url.query)
    body = await request.body()
    headers = _forward_request_headers(request)

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(
            request.method,
            upstream_url,
            data=body if body else None,
            headers=headers,
            allow_redirects=False,
        ) as upstream:
            content = await upstream.read()
            response_headers = _forward_response_headers(upstream.headers)
            return Response(
                content=content,
                status_code=upstream.status,
                headers=response_headers,
                media_type=upstream.headers.get("content-type"),
            )


def _build_hr_upstream_url(path: str, query: Optional[str]) -> str:
    base_url = settings.HR_INTERNAL_URL.rstrip("/")
    normalized_path = f"/{path}" if path else "/"
    if query:
        return f"{base_url}{normalized_path}?{query}"
    return f"{base_url}{normalized_path}"


def _forward_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        lower_name = name.lower()
        if lower_name in HOP_BY_HOP_HEADERS or lower_name == "host":
            continue
        headers[name] = value

    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-prefix"] = "/hr"
    return headers


def _forward_response_headers(headers: aiohttp.typedefs.LooseHeaders) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for name, value in headers.items():
        lower_name = name.lower()
        if lower_name in HOP_BY_HOP_HEADERS or lower_name == "content-length":
            continue
        forwarded[name] = value
    return forwarded

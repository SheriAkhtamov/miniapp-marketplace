import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database.models import AuditLog


async def log_action(
    session: AsyncSession,
    action: str,
    request: Optional[Request] = None,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: Optional[dict] = None,
):
    ip = None
    if request:
        forwarded = request.headers.get("x-forwarded-for")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)

    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
        ip_address=ip,
    )
    session.add(entry)

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.web.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, timezone

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.web.routes import admin, shop, payme, click, deeplinks, hr_proxy
from app.database.core import engine, Base, async_session_maker
from app.database.models import User, Order
from app.utils.security import get_password_hash, verify_password
from app.utils.logger import logger
from app.utils.cache import get_redis, close_redis
from app.web.middlewares.request_id import RequestIdMiddleware
from app.web.middlewares.security import CSPMiddleware
from app.web.static_files import ProtectedMediaStaticFiles

import os

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"])

async def _support_image_cleanup_loop():
    """Background loop: clean up support media files older than 1 year.

    Messages (text) are NEVER deleted — kept forever.
    Media files on disk are removed after 1 year; the image_path in DB
    is cleared so the message itself stays but the attachment is gone.
    """
    from app.database.models import SupportMessage
    from sqlalchemy import update as sa_update
    SUPPORT_DIR = "media/support"
    INTERVAL = 3600  # check every hour
    MEDIA_MAX_AGE = 365 * 86400  # 1 year in seconds
    while True:
        try:
            await asyncio.sleep(INTERVAL)
            if not os.path.isdir(SUPPORT_DIR):
                continue

            # Phase 1: Clear image_path on messages older than 1 year (keep the message text)
            referenced_paths: set = set()
            try:
                async with async_session_maker() as session:
                    cutoff_dt = datetime.utcnow() - timedelta(days=365)
                    await session.execute(
                        sa_update(SupportMessage)
                        .where(
                            SupportMessage.created_at < cutoff_dt,
                            SupportMessage.image_path.isnot(None),
                        )
                        .values(image_path=None)
                    )
                    await session.commit()

                    # Query remaining image paths still referenced by active messages
                    stmt = select(SupportMessage.image_path).where(
                        SupportMessage.image_path.isnot(None)
                    )
                    rows = (await session.execute(stmt)).scalars().all()
                    for p in rows:
                        referenced_paths.add(p.lstrip("/").replace("\\", "/"))
            except Exception:
                logger.exception("Cleanup: failed to process support media, skipping cycle")
                continue

            # Phase 2: Remove orphan files on disk older than MEDIA_MAX_AGE
            now = datetime.utcnow().timestamp()
            for fname in os.listdir(SUPPORT_DIR):
                fpath = os.path.join(SUPPORT_DIR, fname)
                if not os.path.isfile(fpath):
                    continue
                if fpath.replace("\\", "/") in referenced_paths:
                    continue
                age = now - os.path.getmtime(fpath)
                if age > MEDIA_MAX_AGE:
                    try:
                        os.remove(fpath)
                        logger.debug(f"Cleanup: removed orphan support file {fpath}")
                    except OSError:
                        pass
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Support image cleanup error")

async def create_default_admin():
    """Создает суперадмина, если его нет"""
    async with async_session_maker() as session:
        try:
            stmt = select(User).where(User.login == settings.SUPERADMIN_LOGIN)
            admin_user = (await session.execute(stmt)).scalar_one_or_none()
            
            pwd_hash = get_password_hash(settings.SUPERADMIN_PASSWORD)

            if not admin_user:
                logger.info(f"⚡ Суперадмин {settings.SUPERADMIN_LOGIN} не найден. Создаю...")
                
                new_admin = User(
                    telegram_id=None,
                    username="SuperAdmin",
                    login=settings.SUPERADMIN_LOGIN,
                    password_hash=pwd_hash,
                    role="superadmin",
                    phone="admin_contact"
                )
                session.add(new_admin)
                await session.commit()
                logger.info(f"✅ Суперадмин создан! Логин: {settings.SUPERADMIN_LOGIN}")
            else:
                if not verify_password(settings.SUPERADMIN_PASSWORD, admin_user.password_hash):
                    if settings.SYNC_SUPERADMIN_PASSWORD:
                        admin_user.password_hash = pwd_hash
                        session.add(admin_user)
                        await session.commit()
                        logger.info(
                            f"🔄 Пароль суперадмина {settings.SUPERADMIN_LOGIN} обновлен из конфига."
                        )
                    else:
                        logger.warning(
                            "⚠️ Пароль суперадмина отличается от конфига, "
                            "но SYNC_SUPERADMIN_PASSWORD выключен — "
                            "автоматическое обновление не выполнено."
                        )
                else:
                    logger.info(f"✅ Суперадмин {settings.SUPERADMIN_LOGIN} уже существует и актуален.")
                
        except Exception as e:
            logger.error(f"Ошибка создания админа: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Запуск приложения...")
    async with engine.begin() as conn:
        # create_all создаёт только отсутствующие таблицы (для свежей БД).
        # Миграции Alembic применяются отдельно через entrypoint.sh.
        await conn.run_sync(Base.metadata.create_all)

        # Если это свежая БД (нет таблицы alembic_version), штампуем head,
        # чтобы Alembic не пытался применить миграции на уже полную схему.
        from sqlalchemy import inspect as sa_inspect, text as sa_text
        def _stamp_if_fresh(connection):
            inspector = sa_inspect(connection)
            if "alembic_version" not in inspector.get_table_names():
                from alembic.config import Config as AlembicConfig
                from alembic.script import ScriptDirectory
                alembic_cfg = AlembicConfig("alembic.ini")
                script = ScriptDirectory.from_config(alembic_cfg)
                head_rev = script.get_current_head()
                if head_rev:
                    connection.execute(sa_text(
                        "CREATE TABLE alembic_version ("
                        "version_num VARCHAR(32) NOT NULL, "
                        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                    ))
                    connection.execute(sa_text(
                        "INSERT INTO alembic_version (version_num) VALUES (:rev)"
                    ), {"rev": head_rev})
                    logger.info("✅ Alembic stamped to head '%s' (fresh DB)", head_rev)
        await conn.run_sync(_stamp_if_fresh)
    
    await create_default_admin()

    # Прогрев Redis
    try:
        r = await get_redis()
        await r.ping()
        logger.info("✅ Redis подключен")
    except Exception:
        logger.warning("⚠️ Redis недоступен — кеширование отключено")
    
    # Background task: cleanup support images older than 24h
    cleanup_task = asyncio.create_task(_support_image_cleanup_loop())

    # Background task: check blocked bot users every 24h
    from app.services.blocked_users import blocked_users_loop
    from app.bot.loader import bot as tg_bot
    blocked_task = asyncio.create_task(blocked_users_loop(tg_bot))

    yield
    
    # Shutdown
    logger.info("🛑 Остановка приложения...")
    cleanup_task.cancel()
    blocked_task.cancel()
    await close_redis()
    await engine.dispose()
    logger.info("Bye!")

app = FastAPI(title="Shop MiniApp", lifespan=lifespan)

# SlowAPI rate limiter
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Too many requests"}, status_code=429)

# Middlewares (порядок важен: первый добавленный — последний выполняемый)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CSPMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY, 
    max_age=86400 * 30,
    https_only=settings.SESSION_HTTPS_ONLY,
    same_site='none'
)

# Подключаем статику
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.mount("/media", ProtectedMediaStaticFiles(directory="media"), name="media")

templates = Jinja2Templates(directory="app/templates")

def format_datetime_uz(value, format="%d.%m.%Y %H:%M"):
    if value is None:
        return ""
    local_dt = value + timedelta(hours=5)
    return local_dt.strftime(format)

templates.env.filters["datetime_uz"] = format_datetime_uz

def format_number(value):
    try:
        return f"{int(value):,}".replace(",", " ")
    except (ValueError, TypeError):
        return value

templates.env.filters["number_format"] = format_number

# Подключаем роутеры
app.include_router(admin.router)
app.include_router(shop.router)
app.include_router(deeplinks.router)
app.include_router(hr_proxy.router)
app.include_router(payme.router)
app.include_router(click.router)

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    path = request.url.path
    if exc.status_code == 401 and path.startswith("/shop") and "/api/" not in path:
        return RedirectResponse("/shop", status_code=303)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# --- SSE: Подписка на обновления статуса заказа ---
from sse_starlette.sse import EventSourceResponse  # noqa: E402 — будет fallback если нет пакета
import json as _json

_order_subscribers: dict[int, list[asyncio.Queue]] = {}

async def notify_order_status(order_id: int, status: str):
    """Уведомить всех подписчиков об изменении статуса заказа"""
    queues = _order_subscribers.get(order_id, [])
    for q in queues:
        await q.put({"event": "status", "data": _json.dumps({"status": status})})

@app.get("/shop/api/orders/{order_id}/events")
async def order_events(request: Request, order_id: int):
    # Auth check: verify user owns this order
    user_id = request.session.get("shop_user_id")
    if not user_id:
        from fastapi.responses import JSONResponse as _JSONResponse
        return _JSONResponse({"error": "Unauthorized"}, status_code=401)

    async with async_session_maker() as _sess:
        _stmt = select(Order).where(Order.id == order_id, Order.user_id == user_id)
        _order = (await _sess.execute(_stmt)).scalar_one_or_none()
        if not _order:
            from fastapi.responses import JSONResponse as _JSONResponse
            return _JSONResponse({"error": "Not found"}, status_code=404)

    queue: asyncio.Queue = asyncio.Queue()
    _order_subscribers.setdefault(order_id, []).append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            _order_subscribers.get(order_id, []).remove(queue)
            if not _order_subscribers.get(order_id):
                _order_subscribers.pop(order_id, None)

    return EventSourceResponse(event_generator())

# Health-check endpoint
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def index():
    return RedirectResponse(url="/shop")

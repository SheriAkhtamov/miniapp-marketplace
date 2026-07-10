import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_200_OK

from sqlalchemy.ext.asyncio import AsyncSession
from app.database.core import get_db
from app.config import settings
from app.services.payme_logic import PaymeService, PaymeException, PaymeErrors
from app.utils.logger import logger

router = APIRouter(prefix="/api/payme", tags=["payme"])

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: Генерация ссылки ---
# Вынесена в app/utils/payment.py



# --- WEBHOOK: Обработка запросов от Payme ---

@router.post("")
async def payme_webhook(
    request: Request,
    authorization: str = Header(None),
    session: AsyncSession = Depends(get_db)
):
    """
    Единая точка входа для всех запросов Payme.
    """
    
    # 1. Читаем тело запроса
    try:
        body = await request.json()
    except Exception:
        logger.warning("Payme webhook: invalid JSON received")
        return {"jsonrpc": "2.0", "id": None, "error": {"code": PaymeErrors.JSON_PARSE_ERROR, "message": {"ru": "Ошибка парсинга JSON", "uz": "JSON tahlil xatosi", "en": "JSON parse error"}}}

    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})
    logger.info(f"Payme webhook: method={method}, params={params}")

    # 2. Проверка Авторизации (Basic Auth)
    # Payme шлет заголовок: Authorization: Basic base64("PaymeBusiness:KEY")
    if not authorization:
         return response_error(request_id, PaymeErrors.INSUFFICIENT_PRIVILEGE, {"ru": "Недостаточно привилегий для выполнения метода", "uz": "Metodni bajarish uchun huquqlar yetarli emas", "en": "Insufficient privileges to execute method"})
    
    try:
        scheme, credentials = authorization.split()
        if scheme.lower() != 'basic':
            raise ValueError
        decoded = base64.b64decode(credentials).decode("utf-8")
        login, password = decoded.split(":", 1) # Ограничиваем split чтобы двоеточие в пароле не ломало парсинг
        
        # Проверяем пароль (Ключ из настроек)
        # Логин PaymeBusiness игнорируем или проверяем, если нужно
        if password != settings.PAYME_KEY:
             return response_error(request_id, PaymeErrors.INSUFFICIENT_PRIVILEGE, {"ru": "Недостаточно привилегий для выполнения метода", "uz": "Metodni bajarish uchun huquqlar yetarli emas", "en": "Insufficient privileges to execute method"})
             
    except Exception:
        return response_error(request_id, PaymeErrors.INSUFFICIENT_PRIVILEGE, {"ru": "Недостаточно привилегий для выполнения метода", "uz": "Metodni bajarish uchun huquqlar yetarli emas", "en": "Insufficient privileges to execute method"})

    # 3. Маршрутизация методов
    service = PaymeService(session)
    result = None
    
    try:
        if method == "CheckPerformTransaction":
            result = await service.check_perform_transaction(params.get("amount"), params.get("account"))
            
        elif method == "CreateTransaction":
            result = await service.create_transaction(
                params.get("id"), 
                params.get("time"), 
                params.get("amount"), 
                params.get("account")
            )
            
        elif method == "PerformTransaction":
            result = await service.perform_transaction(params.get("id"))
            
        elif method == "CancelTransaction":
            result = await service.cancel_transaction(params.get("id"), params.get("reason"))
            
        elif method == "CheckTransaction":
            result = await service.check_transaction(params.get("id"))
            
        elif method == "GetStatement":
            result = await service.get_statement(params.get("from"), params.get("to")) 
            
        elif method == "SetFiscalData":
            result = {"success": True}
            
        elif method == "ChangePassword":
            result = {"success": True}
            
        else:
            return response_error(request_id, PaymeErrors.METHOD_NOT_FOUND, {"ru": f"Метод {method} не найден", "uz": f"{method} metodi topilmadi", "en": f"Method {method} not found"}, data=method)

    except PaymeException as e:
        logger.warning(f"Payme error: method={method}, code={e.code}, message={e.message}")
        return response_error(request_id, e.code, e.message, e.data)
    except Exception as e:
        logger.exception(f"Payme System Error: method={method}, error={e}")
        return response_error(request_id, -32400, {"ru": "Системная ошибка", "uz": "Tizim xatosi", "en": "System error"})

    # 4. Успешный ответ
    logger.info(f"Payme success: method={method}, result={result}")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    }

def response_error(req_id, code, message, data=None):
    """Формирует JSON-RPC ошибку.
    message должен быть локализованным объектом {ru, uz, en} по документации Payme.
    Если передана строка — оборачиваем в объект.
    """
    if isinstance(message, dict):
        msg = message
    else:
        msg = {"ru": str(message), "uz": str(message), "en": str(message)}
    err = {
        "code": code,
        "message": msg,
    }
    if data is not None:
        err["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err,
    }

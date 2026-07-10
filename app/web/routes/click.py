from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.core import get_db
from app.services.click_logic import ClickService, ClickErrors
from app.utils.logger import logger

router = APIRouter(prefix="/api/click", tags=["click"])

@router.post("/prepare")
async def click_prepare(
    click_trans_id: str = Form(...),
    service_id: str = Form(...),
    click_paydoc_id: str = Form(...),
    merchant_trans_id: str = Form(...),
    amount: str = Form(...),
    action: str = Form(...),
    error: str = Form("0"),
    error_note: str = Form(""),
    sign_time: str = Form(...),
    sign_string: str = Form(...),
    session: AsyncSession = Depends(get_db)
):
    """
    URL для метода Prepare (проверка)
    В настройках Click указать: https://unicombot.uz/api/click/prepare
    """
    data = locals() # Собираем все аргументы в словарь
    del data['session'] # Убираем сессию из данных
    
    logger.info(f"Click PREPARE received: {data}")
    try:
        service = ClickService(session)
        result = await service.prepare(data)
        logger.info(f"Click PREPARE result: {result}")
        return result
    except Exception as e:
        logger.exception(f"Click PREPARE exception: {e}")
        return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Internal server error"}

@router.post("/complete")
async def click_complete(
    click_trans_id: str = Form(...),
    service_id: str = Form(...),
    click_paydoc_id: str = Form(...),
    merchant_trans_id: str = Form(...),
    merchant_prepare_id: str = Form(""),
    amount: str = Form(...),
    action: str = Form(...),
    error: str = Form("0"),
    error_note: str = Form(""),
    sign_time: str = Form(...),
    sign_string: str = Form(...),
    session: AsyncSession = Depends(get_db)
):
    """
    URL для метода Complete (оплата)
    В настройках Click указать: https://unicombot.uz/api/click/complete
    """
    data = locals()
    del data['session']
    
    logger.info(f"Click COMPLETE received: {data}")
    try:
        service = ClickService(session)
        result = await service.complete(data)
        logger.info(f"Click COMPLETE result: {result}")
        return result
    except Exception as e:
        logger.exception(f"Click COMPLETE exception: {e}")
        return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Internal server error"}

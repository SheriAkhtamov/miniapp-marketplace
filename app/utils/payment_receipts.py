import uuid
from pathlib import Path

import aiofiles

from app.utils.upload_security import read_upload_limited, validate_image_upload


PAYMENT_RECEIPT_UPLOAD_DIR = Path("media/payment_receipts")
PAYMENT_RECEIPT_MAX_FILE_SIZE = 10 * 1024 * 1024


async def save_payment_receipt(upload_file) -> str:
    if not upload_file or not upload_file.filename:
        raise ValueError("receipt_required")

    content = await read_upload_limited(upload_file, PAYMENT_RECEIPT_MAX_FILE_SIZE)
    ext = validate_image_upload(upload_file.filename, content)

    PAYMENT_RECEIPT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = PAYMENT_RECEIPT_UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    async with aiofiles.open(target, "wb") as buffer:
        await buffer.write(content)
    return target.as_posix()

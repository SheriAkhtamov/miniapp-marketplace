import asyncio
import os
from pathlib import Path
from app.utils.logger import logger

# Абсолютный путь к разрешённой директории для медиафайлов
_ALLOWED_ROOT = Path(os.getcwd(), "media").resolve()


def _is_safe_path(resolved: Path) -> bool:
    """Проверяет, что resolved находится строго внутри _ALLOWED_ROOT."""
    try:
        resolved.relative_to(_ALLOWED_ROOT)
        return True
    except ValueError:
        return False


async def delete_file(file_path: str):
    """
    Удаляет файл с диска.
    :param file_path: Путь к файлу (относительный или абсолютный)
    """
    if not file_path:
        return
        
    # Игнорируем дефолтные изображения (если они есть)
    if "no-image" in file_path or "default" in file_path:
        return

    try:
        # Убираем начальный слеш, если путь от корня
        clean_path = file_path.lstrip('/')
        clean_path = clean_path.lstrip('\\')

        # Вычисляем абсолютный путь и проверяем, что он внутри media/
        resolved = Path(os.getcwd(), clean_path).resolve()
        if not _is_safe_path(resolved):
            logger.warning(f"Directory traversal blocked: {file_path!r} -> {resolved}")
            return
        
        if await asyncio.to_thread(os.path.exists, str(resolved)):
            await asyncio.to_thread(os.remove, str(resolved))
            logger.info(f"File deleted: {resolved}")
        else:
            logger.warning(f"File not found for deletion: {resolved}")

    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {e}")

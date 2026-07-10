import asyncio
import os
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional

import aiofiles
from PIL import Image
from fastapi import UploadFile

from app.utils.file_manager import delete_file
from app.utils.logger import logger
from app.utils.upload_security import read_upload_limited

IMAGE_MAX_SIZE = (1024, 1024)
IMAGE_QUALITY = 85
IMAGE_FORMAT = "WEBP"
IMAGE_EXTENSION = "webp"

VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "avi"}
VIDEO_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
IMAGE_MAX_BYTES = 15 * 1024 * 1024  # 15 MB
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "heic"}

MEDIA_ROOT = Path(os.getcwd(), "media").resolve()
PRODUCTS_DIR = MEDIA_ROOT / "products"
PRODUCT_POSTERS_DIR = PRODUCTS_DIR / "posters"


@dataclass(slots=True)
class SavedProductMedia:
    public_path: str
    media_type: str
    poster_path: Optional[str] = None


def is_video_file(filename: str) -> bool:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    return ext in VIDEO_EXTENSIONS


def is_media_file(filename: str) -> bool:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    return ext in VIDEO_EXTENSIONS or ext in IMAGE_EXTENSIONS


def process_product_image(file_bytes: bytes) -> bytes:
    try:
        with Image.open(BytesIO(file_bytes)) as img:
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail(IMAGE_MAX_SIZE, Image.LANCZOS)
            output = BytesIO()
            try:
                img.save(output, format=IMAGE_FORMAT, quality=IMAGE_QUALITY, optimize=True)
            except Exception:
                output = BytesIO()
                img.save(output, format="JPEG", quality=IMAGE_QUALITY, optimize=True)
            return output.getvalue()
    except Exception as exc:
        logger.warning(f"Image processing failed: {exc}")
        raise ValueError("invalid_image") from exc


def public_media_to_path(public_path: str) -> Optional[Path]:
    if not public_path:
        return None

    normalized = public_path.strip().lstrip("/").replace("\\", "/")
    candidate = Path(os.getcwd(), normalized).resolve()
    try:
        candidate.relative_to(MEDIA_ROOT)
    except ValueError:
        logger.warning(f"Blocked unsafe media path: {public_path!r}")
        return None
    return candidate


def path_to_public_media(path: Path) -> str:
    relative = path.resolve().relative_to(Path(os.getcwd()).resolve())
    return "/" + relative.as_posix()


def public_media_exists(public_path: Optional[str]) -> bool:
    resolved = public_media_to_path(public_path or "")
    return bool(resolved and resolved.is_file())


async def generate_video_poster(
    video_public_path: str,
    *,
    existing_poster_path: Optional[str] = None,
) -> Optional[str]:
    video_path = public_media_to_path(video_public_path)
    if not video_path or not video_path.is_file():
        return existing_poster_path

    if existing_poster_path and public_media_exists(existing_poster_path):
        return existing_poster_path

    await asyncio.to_thread(PRODUCT_POSTERS_DIR.mkdir, parents=True, exist_ok=True)

    poster_path = PRODUCT_POSTERS_DIR / f"{video_path.stem}.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "00:00:00.200",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "4",
        str(poster_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        if rc != 0 or not poster_path.is_file():
            logger.warning(f"ffmpeg poster generation failed for {video_public_path} with code {rc}")
            return existing_poster_path
    except FileNotFoundError:
        logger.warning("ffmpeg is not installed; video poster generation skipped")
        return existing_poster_path
    except Exception:
        logger.exception("Video poster generation failed")
        return existing_poster_path

    return path_to_public_media(poster_path)


async def save_uploaded_product_media(upload_file: UploadFile) -> Optional[SavedProductMedia]:
    if not upload_file or not upload_file.filename or not is_media_file(upload_file.filename):
        return None

    await asyncio.to_thread(PRODUCTS_DIR.mkdir, parents=True, exist_ok=True)

    if is_video_file(upload_file.filename):
        try:
            file_bytes = await read_upload_limited(upload_file, VIDEO_MAX_BYTES)
        except ValueError:
            return None

        ext = upload_file.filename.rsplit(".", 1)[-1].lower()
        unique_name = f"{uuid.uuid4()}.{ext}"
        target = PRODUCTS_DIR / unique_name
        async with aiofiles.open(target, "wb") as buffer:
            await buffer.write(file_bytes)

        public_path = path_to_public_media(target)
        poster_path = await generate_video_poster(public_path)
        return SavedProductMedia(
            public_path=public_path,
            media_type="video",
            poster_path=poster_path,
        )

    try:
        file_bytes = await read_upload_limited(upload_file, IMAGE_MAX_BYTES)
    except ValueError:
        return None

    processed_bytes = await asyncio.to_thread(process_product_image, file_bytes)
    unique_name = f"{uuid.uuid4()}.{IMAGE_EXTENSION}"
    target = PRODUCTS_DIR / unique_name
    async with aiofiles.open(target, "wb") as buffer:
        await buffer.write(processed_bytes)

    return SavedProductMedia(
        public_path=path_to_public_media(target),
        media_type="image",
    )


async def save_uploaded_product_media_batch(
    files: Iterable[UploadFile],
    *,
    limit: int = 10,
) -> list[SavedProductMedia]:
    saved: list[SavedProductMedia] = []
    valid_files = [f for f in (files or []) if f and f.filename and is_media_file(f.filename)][:limit]

    for media_file in valid_files:
        try:
            item = await save_uploaded_product_media(media_file)
            if item:
                saved.append(item)
        except Exception:
            logger.exception("Product media upload failed")
    return saved


async def delete_product_media_files(public_path: Optional[str], poster_path: Optional[str] = None):
    if public_path:
        await delete_file(public_path)
    if poster_path:
        await delete_file(poster_path)

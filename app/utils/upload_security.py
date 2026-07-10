from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, UnidentifiedImageError


SAFE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SAFE_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
IMAGE_FORMATS_BY_EXTENSION = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".gif": {"GIF"},
    ".webp": {"WEBP"},
}

Image.MAX_IMAGE_PIXELS = 25_000_000


async def read_upload_limited(upload_file, max_bytes: int) -> bytes:
    declared_size = getattr(upload_file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise ValueError("file_too_large")

    content = await upload_file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("file_too_large")
    return content


def validate_image_upload(
    filename: str,
    content: bytes,
    *,
    allowed_extensions: set[str] | None = None,
) -> str:
    ext = Path(filename or "").suffix.lower()
    allowed = allowed_extensions or SAFE_IMAGE_EXTENSIONS
    if ext not in allowed:
        raise ValueError("invalid_file_type")
    if not content:
        raise ValueError("invalid_image")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as img:
                image_format = img.format
                width, height = img.size
                img.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError) as exc:
        raise ValueError("invalid_image") from exc

    if image_format not in SAFE_IMAGE_FORMATS:
        raise ValueError("invalid_image")
    if image_format not in IMAGE_FORMATS_BY_EXTENSION.get(ext, set()):
        raise ValueError("invalid_file_type")
    if width <= 0 or height <= 0:
        raise ValueError("invalid_image")

    return ext

from pathlib import PurePosixPath

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProtectedMediaStaticFiles(StaticFiles):
    BLOCKED_PREFIXES = {"payment_receipts", "support"}
    BLOCKED_SUFFIXES = {
        ".bash",
        ".cgi",
        ".dll",
        ".dylib",
        ".exe",
        ".htm",
        ".html",
        ".js",
        ".mjs",
        ".phar",
        ".php",
        ".phtml",
        ".pl",
        ".py",
        ".sh",
        ".so",
        ".svg",
        ".zsh",
    }

    async def get_response(self, path: str, scope):
        normalized = PurePosixPath(path.replace("\\", "/"))
        parts = [part for part in normalized.parts if part not in {"", "."}]

        if not parts:
            raise StarletteHTTPException(status_code=404)
        if any(part.startswith(".") for part in parts):
            raise StarletteHTTPException(status_code=404)
        if parts[0] in self.BLOCKED_PREFIXES:
            raise StarletteHTTPException(status_code=404)
        if normalized.suffix.lower() in self.BLOCKED_SUFFIXES:
            raise StarletteHTTPException(status_code=404)

        return await super().get_response(path, scope)

import asyncio
import json
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import BigInteger, Boolean, Date, DateTime, Integer, Numeric

import app.database.models  # noqa: F401 - ensure models registered in metadata
from app.database.core import Base, async_session_maker
from app.utils.logger import logger

SKIP_TABLES: set[str] = {"alembic_version"}

BACKUP_ROOT = Path("backups").resolve()
BACKUP_READY_DIR = BACKUP_ROOT / "ready"
BACKUP_TMP_DIR = BACKUP_ROOT / "tmp"
BACKUP_UPLOAD_DIR = BACKUP_ROOT / "uploads"
BACKUP_ROLLBACK_DIR = BACKUP_ROOT / "rollback"
MEDIA_ROOT = Path("media").resolve()
JOB_RETENTION_HOURS = 24
ROLLBACK_RETENTION_DAYS = 7
ROLLBACK_ARCHIVE_NAME = "previous_state.zip"
ROLLBACK_METADATA_NAME = "previous_state.json"
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_BACKUP_ARCHIVE_FILES = 10_000
MAX_BACKUP_UPLOAD_BYTES = 1024 * 1024 * 1024
MAX_BACKUP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
UNSAFE_MEDIA_RESTORE_SUFFIXES = {
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


class BackupBusyError(RuntimeError):
    pass


@dataclass(slots=True)
class BackupJob:
    job_id: str
    kind: str
    status: str = "queued"
    percent: int = 0
    message: str = ""
    error: Optional[str] = None
    download_url: Optional[str] = None
    filename: Optional[str] = None
    warning: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "percent": self.percent,
            "message": self.message,
            "error": self.error,
            "download_url": self.download_url,
            "filename": self.filename,
            "warning": self.warning,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class BackupService:
    def __init__(self):
        self.jobs: Dict[str, BackupJob] = {}
        self._active_job_id: Optional[str] = None
        self._registry_lock = asyncio.Lock()
        self._ensure_dirs()

    @staticmethod
    def _ensure_dirs():
        BACKUP_READY_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_TMP_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _get_tables():
        return [table for table in Base.metadata.sorted_tables if table.name not in SKIP_TABLES]

    @staticmethod
    def _serialize_value(val: Any):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, date):
            return val.isoformat()
        if isinstance(val, Decimal):
            return str(val)
        return val

    @staticmethod
    def _cast_value(val: Any, col_type):
        if val is None:
            return None
        if isinstance(val, str):
            if isinstance(col_type, DateTime):
                try:
                    return datetime.fromisoformat(val)
                except ValueError:
                    return val
            if isinstance(col_type, Date):
                try:
                    return date.fromisoformat(val)
                except ValueError:
                    return val
            if isinstance(col_type, Numeric):
                try:
                    return Decimal(val)
                except Exception:
                    return val
            if isinstance(col_type, (Integer, BigInteger)):
                try:
                    return int(val)
                except Exception:
                    return val
            if isinstance(col_type, Boolean):
                return val.lower() in ("true", "1", "yes")
        return val

    def is_busy(self) -> bool:
        if not self._active_job_id:
            return False
        job = self.jobs.get(self._active_job_id)
        return bool(job and job.status not in {"done", "error"})

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        self._purge_expired_jobs()
        job = self.jobs.get(job_id)
        return job.as_dict() if job else None

    def get_rollback_state(self) -> dict[str, Any]:
        self._purge_expired_jobs()
        metadata = self._read_rollback_metadata()
        archive_path = BACKUP_ROLLBACK_DIR / ROLLBACK_ARCHIVE_NAME
        if not metadata or not archive_path.exists():
            return {
                "available": False,
                "filename": None,
                "created_at": None,
                "expires_at": None,
            }

        return {
            "available": True,
            "filename": metadata.get("filename") or ROLLBACK_ARCHIVE_NAME,
            "created_at": metadata.get("created_at"),
            "expires_at": metadata.get("expires_at"),
        }

    async def start_export_job(self) -> dict[str, Any]:
        async with self._registry_lock:
            if self.is_busy():
                raise BackupBusyError("Another backup job is already running")

            job = BackupJob(
                job_id=uuid.uuid4().hex,
                kind="export",
                status="queued",
                percent=0,
                message="Backup job queued",
            )
            self.jobs[job.job_id] = job
            self._active_job_id = job.job_id
            asyncio.create_task(self._run_export_job(job.job_id))
            return job.as_dict()

    async def start_import_job(self, upload_path: Path, source_name: str) -> dict[str, Any]:
        return await self._start_import_job(
            upload_path,
            source_name,
            create_restore_point=True,
            kind="import",
        )

    async def start_restore_previous_job(self) -> dict[str, Any]:
        rollback_state = self.get_rollback_state()
        if not rollback_state.get("available"):
            raise FileNotFoundError("Previous database snapshot is unavailable or expired")

        source = BACKUP_ROLLBACK_DIR / ROLLBACK_ARCHIVE_NAME
        copied = BACKUP_UPLOAD_DIR / f"restore_previous_{uuid.uuid4().hex}.zip"
        await asyncio.to_thread(shutil.copy2, source, copied)
        return await self._start_import_job(
            copied,
            rollback_state.get("filename") or ROLLBACK_ARCHIVE_NAME,
            create_restore_point=False,
            kind="restore_previous",
        )

    async def _start_import_job(
        self,
        upload_path: Path,
        source_name: str,
        *,
        create_restore_point: bool,
        kind: str,
    ) -> dict[str, Any]:
        async with self._registry_lock:
            if self.is_busy():
                raise BackupBusyError("Another backup job is already running")

            suffix = upload_path.suffix.lower()
            warning = None
            if kind == "import" and suffix == ".json":
                warning = "Legacy JSON restores database rows only and does not include media files."

            job = BackupJob(
                job_id=uuid.uuid4().hex,
                kind=kind,
                status="queued",
                percent=0,
                message=f"Import queued for {source_name}",
                warning=warning,
            )
            self.jobs[job.job_id] = job
            self._active_job_id = job.job_id
            asyncio.create_task(
                self._run_import_job(
                    job.job_id,
                    upload_path,
                    create_restore_point=create_restore_point,
                )
            )
            return job.as_dict()

    async def stream_upload_to_disk(
        self,
        upload_file,
        destination: Path,
        *,
        max_bytes: int = MAX_BACKUP_UPLOAD_BYTES,
    ):
        declared_size = getattr(upload_file, "size", None)
        if isinstance(declared_size, int) and declared_size > max_bytes:
            raise ValueError("Backup upload is too large")

        destination.parent.mkdir(parents=True, exist_ok=True)
        chunk_size = 1024 * 1024
        written = 0
        import aiofiles

        async with aiofiles.open(destination, "wb") as buffer:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("Backup upload is too large")
                await buffer.write(chunk)

    async def _run_export_job(self, job_id: str):
        temp_dir = BACKUP_TMP_DIR / job_id
        ready_path = BACKUP_READY_DIR / f"{job_id}.zip"

        try:
            self._set_job(job_id, status="exporting", percent=5, message="Preparing export directory...")
            await asyncio.to_thread(temp_dir.mkdir, parents=True, exist_ok=True)

            async with async_session_maker() as session:
                manifest = await self._dump_database_to_temp(job_id, session, temp_dir)

            manifest_path = temp_dir / "manifest.json"
            await asyncio.to_thread(
                manifest_path.write_text,
                json.dumps(manifest, ensure_ascii=False, indent=2),
                "utf-8",
            )

            self._set_job(job_id, percent=70, message="Packing database and media into ZIP...")
            await asyncio.to_thread(self._build_export_archive, temp_dir, ready_path)

            self._set_job(
                job_id,
                status="done",
                percent=100,
                message="Backup is ready for download.",
                filename=f"logical_backup_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.zip",
                download_url=f"/admin/backup/jobs/{job_id}/download",
            )
        except Exception as exc:
            logger.exception("Backup export job failed")
            if ready_path.exists():
                await asyncio.to_thread(ready_path.unlink, missing_ok=True)
            self._set_job(job_id, status="error", percent=0, message="Export failed", error=str(exc))
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)
            await self._clear_active_job(job_id)

    async def _create_rollback_snapshot(self, job_id: str, temp_dir: Path):
        await asyncio.to_thread(temp_dir.mkdir, parents=True, exist_ok=True)

        async with async_session_maker() as session:
            manifest = await self._dump_database_to_temp(
                job_id,
                session,
                temp_dir,
                progress_start=10,
                progress_span=20,
                message_prefix="Snapshotting table",
            )

        manifest["snapshot_type"] = "rollback"
        manifest_path = temp_dir / "manifest.json"
        await asyncio.to_thread(
            manifest_path.write_text,
            json.dumps(manifest, ensure_ascii=False, indent=2),
            "utf-8",
        )

        temp_archive = temp_dir.parent / f"{ROLLBACK_ARCHIVE_NAME}.tmp"
        await asyncio.to_thread(self._build_export_archive, temp_dir, temp_archive)

        final_archive = BACKUP_ROLLBACK_DIR / ROLLBACK_ARCHIVE_NAME
        final_archive.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(temp_archive.replace, final_archive)
        await asyncio.to_thread(self._write_rollback_metadata)

    async def _run_import_job(self, job_id: str, upload_path: Path, *, create_restore_point: bool):
        temp_dir = BACKUP_TMP_DIR / job_id
        suffix = upload_path.suffix.lower()

        try:
            self._set_job(job_id, status="importing", percent=5, message="Preparing import workspace...")
            await asyncio.to_thread(temp_dir.mkdir, parents=True, exist_ok=True)

            if create_restore_point:
                self._set_job(job_id, percent=10, message="Saving current database as rollback snapshot...")
                await self._create_rollback_snapshot(job_id, temp_dir / "rollback_snapshot")

            if suffix == ".json":
                self._set_job(job_id, percent=25, message="Loading legacy JSON backup...")
                data = await asyncio.to_thread(self._load_json_file, upload_path)
                async with async_session_maker() as session:
                    await self.import_legacy_json(session, data, job_id=job_id)
                self._set_job(
                    job_id,
                    status="done",
                    percent=100,
                    message="Legacy JSON import completed. Media files were not restored.",
                )
                return

            if suffix != ".zip":
                raise ValueError("Only .zip and legacy .json backups are supported")

            self._set_job(job_id, percent=25, message="Validating backup archive...")
            extracted = await asyncio.to_thread(self._extract_archive, upload_path, temp_dir / "extracted")

            media_stage = extracted["media_dir"]
            if media_stage.exists():
                self._set_job(job_id, percent=40, message="Restoring media files...")
                await asyncio.to_thread(self._overlay_tree, media_stage, MEDIA_ROOT)

            self._set_job(job_id, percent=55, message="Importing database data...")
            async with async_session_maker() as session:
                await self.import_from_jsonl_dir(session, extracted["db_dir"], job_id=job_id)

            final_message = "Backup import completed successfully."
            if self.jobs[job_id].kind == "restore_previous":
                final_message = "Previous database snapshot restored successfully."
            self._set_job(job_id, status="done", percent=100, message=final_message)
        except Exception as exc:
            logger.exception("Backup import job failed")
            self._set_job(job_id, status="error", percent=0, message="Import failed", error=str(exc))
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)
            await asyncio.to_thread(upload_path.unlink, missing_ok=True)
            await self._clear_active_job(job_id)

    async def _clear_active_job(self, job_id: str):
        async with self._registry_lock:
            if self._active_job_id == job_id:
                self._active_job_id = None

    def _set_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        percent: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        filename: Optional[str] = None,
        download_url: Optional[str] = None,
    ):
        job = self.jobs[job_id]
        if status is not None:
            job.status = status
        if percent is not None:
            job.percent = percent
        if message is not None:
            job.message = message
        if error is not None:
            job.error = error
        if filename is not None:
            job.filename = filename
        if download_url is not None:
            job.download_url = download_url
        if status in {"done", "error"}:
            job.finished_at = datetime.utcnow().isoformat()
        logger.info(f"Backup job {job_id}: {job.status} - {job.message} ({job.percent}%)")

    async def _dump_database_to_temp(
        self,
        job_id: str,
        session: AsyncSession,
        temp_dir: Path,
        *,
        progress_start: int = 10,
        progress_span: int = 50,
        message_prefix: str = "Exporting table",
    ) -> dict[str, Any]:
        db_dir = temp_dir / "db"
        await asyncio.to_thread(db_dir.mkdir, parents=True, exist_ok=True)

        tables = self._get_tables()
        total = max(len(tables), 1)
        for idx, table in enumerate(tables, start=1):
            percent = progress_start + int((idx - 1) / total * progress_span)
            self._set_job(job_id, percent=percent, message=f"{message_prefix} {table.name}...")
            table_path = db_dir / f"{table.name}.jsonl"
            await self._write_table_jsonl(session, table, table_path)

        return {
            "version": 3,
            "created_at": datetime.utcnow().isoformat(),
            "db_format": "jsonl",
            "includes_media": True,
            "tables": [table.name for table in tables],
        }

    async def _write_table_jsonl(self, session: AsyncSession, table, destination: Path):
        import aiofiles

        stream = await session.stream(select(table))
        async with aiofiles.open(destination, "w", encoding="utf-8") as buffer:
            async for row in stream.mappings():
                payload = {
                    col.name: self._serialize_value(row[col.name])
                    for col in table.columns
                }
                await buffer.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _build_export_archive(self, temp_dir: Path, ready_path: Path):
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ready_path, "w", allowZip64=True) as archive:
            for path in sorted(temp_dir.rglob("*")):
                if not path.is_file():
                    continue
                arcname = path.relative_to(temp_dir).as_posix()
                archive.write(path, arcname=arcname, compress_type=zipfile.ZIP_DEFLATED)

            if MEDIA_ROOT.exists():
                for path in sorted(MEDIA_ROOT.rglob("*")):
                    if not path.is_file():
                        continue
                    arcname = path.relative_to(Path.cwd()).as_posix()
                    archive.write(path, arcname=arcname, compress_type=zipfile.ZIP_STORED)

    def _extract_archive(self, archive_path: Path, extract_root: Path) -> dict[str, Path]:
        if extract_root.exists():
            shutil.rmtree(extract_root, ignore_errors=True)
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise ValueError("Backup archive is missing manifest.json")
            if not any(name.startswith("db/") for name in names):
                raise ValueError("Backup archive is missing db/ payload")

            file_members = [member for member in archive.infolist() if not member.is_dir()]
            if len(file_members) > MAX_BACKUP_ARCHIVE_FILES:
                raise ValueError("Backup archive contains too many files")
            if sum(member.file_size for member in file_members) > MAX_BACKUP_UNCOMPRESSED_BYTES:
                raise ValueError("Backup archive is too large after extraction")

            for member in file_members:
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError("Backup archive contains unsafe paths")

                target = (extract_root / member.filename).resolve()
                try:
                    target.relative_to(extract_root.resolve())
                except ValueError as exc:
                    raise ValueError("Backup archive contains unsafe paths") from exc

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)

        manifest_path = extract_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != 3:
            raise ValueError(f"Unsupported backup version: {manifest.get('version')}")
        if manifest.get("db_format") != "jsonl":
            raise ValueError("Unsupported database payload format")

        return {
            "manifest_path": manifest_path,
            "db_dir": extract_root / "db",
            "media_dir": extract_root / "media",
        }

    def _overlay_tree(self, source: Path, destination: Path):
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        for path in source.rglob("*"):
            if path.is_dir():
                continue
            relative = path.relative_to(source)
            if not self._is_safe_restored_media_path(relative):
                logger.warning(f"Skipped unsafe media file from backup: {relative}")
                continue
            target = (destination / relative).resolve()
            try:
                target.relative_to(destination_root)
            except ValueError as exc:
                raise ValueError("Backup media contains unsafe paths") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    @staticmethod
    def _is_safe_restored_media_path(relative: Path) -> bool:
        if any(part.startswith(".") for part in relative.parts):
            return False
        return relative.suffix.lower() not in UNSAFE_MEDIA_RESTORE_SUFFIXES

    def _load_json_file(self, path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as source:
            return json.load(source)

    async def import_from_jsonl_dir(self, session: AsyncSession, db_dir: Path, *, job_id: Optional[str] = None):
        tables = self._get_tables()
        delete_order = list(reversed(tables))
        total_steps = len(delete_order) + len(tables)
        current_step = 0

        try:
            for table in delete_order:
                current_step += 1
                if job_id:
                    self._set_job(
                        job_id,
                        percent=55 + int(current_step / total_steps * 25),
                        message=f"Clearing table {table.name}...",
                    )
                await session.execute(delete(table))

            await session.flush()

            for table in tables:
                current_step += 1
                payload_path = db_dir / f"{table.name}.jsonl"
                if job_id:
                    self._set_job(
                        job_id,
                        percent=55 + int(current_step / total_steps * 35),
                        message=f"Importing table {table.name}...",
                    )

                if not payload_path.exists():
                    continue

                batch: list[dict[str, Any]] = []
                with open(payload_path, "r", encoding="utf-8") as source:
                    for line in source:
                        line = line.strip()
                        if not line:
                            continue
                        row_dict = json.loads(line)
                        batch.append(self._prepare_row(table, row_dict))
                        if len(batch) >= 500:
                            await session.execute(insert(table), batch)
                            batch.clear()
                if batch:
                    await session.execute(insert(table), batch)

            if job_id:
                self._set_job(job_id, percent=96, message="Resetting PostgreSQL sequences...")
            await self._reset_sequences(session, tables)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    async def import_legacy_json(
        self,
        session: AsyncSession,
        backup_data: Dict[str, Any],
        *,
        job_id: Optional[str] = None,
    ):
        content = backup_data.get("content", {})
        if not content:
            raise ValueError("Invalid legacy backup format")

        tables = self._get_tables()
        delete_order = list(reversed(tables))
        total_steps = len(delete_order) + len(tables)
        current_step = 0

        try:
            for table in delete_order:
                current_step += 1
                if job_id:
                    self._set_job(
                        job_id,
                        percent=int(current_step / total_steps * 40),
                        message=f"Clearing table {table.name}...",
                    )
                await session.execute(delete(table))

            await session.flush()

            for table in tables:
                current_step += 1
                items_data = content.get(table.name, [])
                if job_id:
                    self._set_job(
                        job_id,
                        percent=40 + int(current_step / total_steps * 50),
                        message=f"Importing table {table.name}...",
                    )
                if not items_data:
                    continue

                batch = [self._prepare_row(table, row_dict) for row_dict in items_data]
                if batch:
                    await session.execute(insert(table), batch)

            if job_id:
                self._set_job(job_id, percent=96, message="Resetting PostgreSQL sequences...")
            await self._reset_sequences(session, tables)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    def _prepare_row(self, table, row_dict: dict[str, Any]) -> dict[str, Any]:
        clean: Dict[str, Any] = {}
        for col in table.columns:
            if col.name in row_dict:
                clean[col.name] = self._cast_value(row_dict[col.name], col.type)
        return clean

    async def _reset_sequences(self, session: AsyncSession, tables):
        for table in tables:
            if "id" not in table.columns:
                continue
            try:
                table_name = self._safe_sql_identifier(table.name)
                seq_name = self._safe_sql_identifier(f"{table.name}_id_seq")
                sql = text(
                    f"SELECT setval('{seq_name}', COALESCE(m.max_id, 1), m.max_id IS NOT NULL) "
                    f"FROM (SELECT MAX(id) as max_id FROM {table_name}) m"
                )
                async with session.begin_nested():
                    await session.execute(sql)
            except Exception as exc:
                logger.warning(f"Could not reset sequence for {table.name}: {exc}")

    @staticmethod
    def _safe_sql_identifier(identifier: str) -> str:
        if not SQL_IDENTIFIER_RE.fullmatch(identifier):
            raise ValueError(f"Unsafe SQL identifier: {identifier}")
        return identifier

    @staticmethod
    def _rollback_metadata_path() -> Path:
        return BACKUP_ROLLBACK_DIR / ROLLBACK_METADATA_NAME

    def _write_rollback_metadata(self):
        created_at = datetime.utcnow()
        expires_at = created_at.timestamp() + ROLLBACK_RETENTION_DAYS * 86400
        payload = {
            "filename": ROLLBACK_ARCHIVE_NAME,
            "created_at": created_at.isoformat(),
            "expires_at": datetime.utcfromtimestamp(expires_at).isoformat(),
        }
        self._rollback_metadata_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_rollback_metadata(self) -> Optional[dict[str, Any]]:
        meta_path = self._rollback_metadata_path()
        if not meta_path.exists():
            return None
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Rollback metadata is unreadable; deleting it")
            try:
                meta_path.unlink()
            except OSError:
                pass
            return None

        expires_at_raw = payload.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
        except ValueError:
            expires_at = None
        if not expires_at or expires_at <= datetime.utcnow():
            self._purge_rollback_snapshot()
            return None
        return payload

    def _purge_rollback_snapshot(self):
        archive_path = BACKUP_ROLLBACK_DIR / ROLLBACK_ARCHIVE_NAME
        metadata_path = self._rollback_metadata_path()
        for path in (archive_path, metadata_path):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    logger.warning(f"Could not remove expired rollback snapshot {path}")

    def resolve_ready_file(self, job_id: str) -> Optional[Path]:
        candidate = BACKUP_READY_DIR / f"{job_id}.zip"
        return candidate if candidate.exists() else None

    def _purge_expired_jobs(self):
        self._read_rollback_metadata()
        cutoff = datetime.utcnow().timestamp() - JOB_RETENTION_HOURS * 3600
        for job_id, job in list(self.jobs.items()):
            if not job.finished_at:
                continue
            try:
                finished_ts = datetime.fromisoformat(job.finished_at).timestamp()
            except ValueError:
                finished_ts = cutoff + 1
            if finished_ts >= cutoff:
                continue
            self.jobs.pop(job_id, None)
            ready_file = BACKUP_READY_DIR / f"{job_id}.zip"
            if ready_file.exists():
                try:
                    ready_file.unlink()
                except OSError:
                    logger.warning(f"Could not remove expired backup archive {ready_file}")


backup_service = BackupService()

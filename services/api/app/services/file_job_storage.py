"""Local filesystem storage for background file jobs (uploaded CSV/JSON
input, generated CSV/JSON output) - see 'Large import/export jobs' in
docs/operations.md and app.services.file_jobs, which is the only caller of
this module.

Path safety: a caller's original filename is never used to build a
filesystem path - every on-disk name here is freshly generated (a uuid4 hex,
optionally job-id-prefixed). resolve_path() additionally refuses to resolve
outside FILE_JOB_STORAGE_DIR, as defense in depth against a stored
relative_path ever containing a path-traversal sequence (which should never
happen, since every relative_path stored in FileJob.input_file_path/
output_file_path is produced by this module, never from request input).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

from app.settings import settings

# .gz is reserved for a possible future direct gzipped-Postgres-backup
# upload path (see scripts/db_backup.sh) - not accepted by any endpoint
# today, kept here only as a documented placeholder per the task spec.
ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".json")
RESERVED_FUTURE_EXTENSIONS = (".gz",)


class UnsupportedFileExtension(ValueError):
    pass


class UploadTooLarge(ValueError):
    pass


def _base_dir() -> Path:
    return Path(settings.FILE_JOB_STORAGE_DIR)


def _input_dir() -> Path:
    return _base_dir() / "input"


def _output_dir() -> Path:
    return _base_dir() / "output"


def ensure_storage_dirs() -> None:
    _input_dir().mkdir(parents=True, exist_ok=True)
    _output_dir().mkdir(parents=True, exist_ok=True)


def is_storage_writable() -> bool:
    """Best-effort writability probe for GET /admin/system-check - creates
    and immediately removes a throwaway file rather than trusting os.access,
    which can report incorrectly under some container/mount setups."""
    try:
        ensure_storage_dirs()
        probe = _base_dir() / f".write_probe_{uuid.uuid4().hex}"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _normalized_extension(extension: str) -> str:
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UnsupportedFileExtension(
            f"Unsupported file extension {ext!r}. Allowed: {list(ALLOWED_UPLOAD_EXTENSIONS)}"
        )
    return ext


def max_upload_bytes() -> int:
    return settings.FILE_JOB_MAX_UPLOAD_MB * 1024 * 1024


def save_upload(content: bytes, *, extension: str) -> str:
    """Saves uploaded bytes under the input directory using a freshly
    generated filename. Returns the path relative to FILE_JOB_STORAGE_DIR
    (stored in FileJob.input_file_path), so the storage dir can be
    relocated without invalidating already-stored rows. Raises
    UploadTooLarge/UnsupportedFileExtension rather than writing anything."""
    if len(content) > max_upload_bytes():
        raise UploadTooLarge(f"Upload exceeds the {settings.FILE_JOB_MAX_UPLOAD_MB}MB limit.")
    ext = _normalized_extension(extension)
    ensure_storage_dirs()
    filename = f"{uuid.uuid4().hex}{ext}"
    path = _input_dir() / filename
    path.write_bytes(content)
    return f"input/{filename}"


def allocate_output_path(job_id: int, *, extension: str) -> str:
    """Reserves an output path for job_id's generated file - always a fresh
    job-id/uuid-based name, never derived from user input. Returns the path
    relative to FILE_JOB_STORAGE_DIR (stored in FileJob.output_file_path).
    The browser-facing filename (FileJob.output_filename) is tracked
    separately by the caller and has no bearing on the on-disk name."""
    ext = _normalized_extension(extension)
    ensure_storage_dirs()
    filename = f"file_job_{job_id}_{uuid.uuid4().hex[:8]}{ext}"
    return f"output/{filename}"


def resolve_path(relative_path: str) -> Path:
    base = _base_dir().resolve()
    candidate = (base / relative_path).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"Refusing to resolve path outside storage dir: {relative_path!r}")
    return candidate


def delete_file(relative_path: str | None) -> None:
    """Best-effort delete - a missing file, or a relative_path that fails to
    resolve safely, is silently ignored (cleanup callers loop over many rows
    and must not abort the whole batch over one already-missing file)."""
    if not relative_path:
        return
    try:
        resolve_path(relative_path).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def read_input_text(relative_path: str, *, encoding: str = "utf-8-sig") -> str:
    return resolve_path(relative_path).read_text(encoding=encoding)


def write_output_text(relative_path: str, text: str) -> int:
    """Writes text to relative_path (UTF-8), returning the byte size written
    (for FileJob.summary_json/logging bookkeeping)."""
    path = resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return len(data)


def write_output_chunks(relative_path: str, chunks: Iterator[str]) -> int:
    """Writes a sequence of text chunks to relative_path (UTF-8) as they're
    produced - used for background export jobs built on a row-streaming
    generator (see app.services.collection_csv.iter_collection_csv_rows),
    so the whole rendered file is never held in memory at once. Returns the
    total byte size written."""
    path = resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with path.open("wb") as f:
        for chunk in chunks:
            data = chunk.encode("utf-8")
            f.write(data)
            total += len(data)
    return total


def iter_output_chunks(relative_path: str, *, chunk_size: int = 65536) -> Iterator[bytes]:
    """Yields an output file's bytes in fixed-size chunks, for a streaming
    download response - never loads the whole file into memory at once."""
    path = resolve_path(relative_path)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def output_file_size(relative_path: str) -> int | None:
    try:
        return resolve_path(relative_path).stat().st_size
    except OSError:
        return None

"""Shared helpers for serving uploaded claim document files."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from config import get_settings


def resolve_claim_document_path(file_path: str) -> Path:
    upload_root = Path(get_settings().upload_dir).resolve()
    resolved = Path(file_path).resolve()
    if upload_root not in resolved.parents and resolved != upload_root:
        raise HTTPException(status_code=403, detail="Invalid document path")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Document file not found on server")
    return resolved


def document_media_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def serve_claim_document_file(
    resolved_path: Path,
    filename: str,
    *,
    download: bool = False,
) -> FileResponse:
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=str(resolved_path),
        media_type=document_media_type(filename),
        filename=filename,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )

"""Versioned image upload and retrieval endpoints for device clients."""

import io
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

router = APIRouter(prefix="/api/v1/images", tags=["images"])
_MEDIA_TYPES = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}
_MAX_BYTES = 8 * 1024 * 1024


def _base_directory(request: Request) -> Path:
    directory = getattr(request.app.state, "image_upload_directory", None)
    if not isinstance(directory, Path):
        configured_media = getattr(request.app.state, "media_root", None)
        media_root = configured_media if isinstance(configured_media, Path) else Path.cwd() / "media"
        directory = media_root / "uploads"
        request.app.state.image_upload_directory = directory
        request.app.state.image_upload_directory_is_default = True
    return directory


def _directory(request: Request) -> Path:
    directory = _base_directory(request)
    if not getattr(request.app.state, "image_upload_directory_is_default", False):
        directory.mkdir(parents=True, exist_ok=True)
        return directory
    dated = directory / datetime.now().strftime("%Y/%m/%d")
    dated.mkdir(parents=True, exist_ok=True)
    return dated


@router.post("", status_code=201)
async def upload_image(request: Request, image: UploadFile) -> dict[str, str | int]:
    content = await image.read(_MAX_BYTES + 1)
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="Invalid image upload")
    try:
        decoded = Image.open(io.BytesIO(content))
        decoded.verify()
        media_type, extension = _MEDIA_TYPES[decoded.format or ""]
    except (KeyError, UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Invalid image upload") from None
    image_id = f"img_{uuid4().hex}"
    name = f"{image_id}{extension}"
    (_directory(request) / name).write_bytes(content)
    return {
        "image_id": image_id,
        "image_url": f"/api/v1/images/{image_id}",
        "media_type": media_type,
        "size_bytes": len(content),
    }


@router.get("/{image_id}")
async def get_image(request: Request, image_id: str) -> FileResponse:
    if not image_id.startswith("img_") or Path(image_id).name != image_id:
        raise HTTPException(status_code=404, detail="Image not found")
    requested = _directory(request) / image_id
    base_directory = _base_directory(request)
    matches = [requested] if requested.is_file() else list(base_directory.glob(f"**/{image_id}.*"))
    if len(matches) != 1 or not matches[0].is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(matches[0])

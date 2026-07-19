"""Temporary image upload endpoint for the local debug console."""

import io
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

router = APIRouter(prefix="/api/v1/images", tags=["images"])
_MEDIA_TYPES = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}
_MAX_BYTES = 8 * 1024 * 1024


def _directory(request: Request) -> Path:
    directory = getattr(request.app.state, "image_upload_directory", None)
    if not isinstance(directory, Path):
        directory = Path(tempfile.gettempdir()) / "somai-chat-images"
        directory.mkdir(parents=True, exist_ok=True)
        request.app.state.image_upload_directory = directory
    return directory


@router.post("", status_code=201)
async def upload_image(request: Request, image: UploadFile) -> dict[str, str]:
    content = await image.read(_MAX_BYTES + 1)
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="Invalid image upload")
    try:
        decoded = Image.open(io.BytesIO(content))
        decoded.verify()
        media_type, extension = _MEDIA_TYPES[decoded.format or ""]
    except (KeyError, UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Invalid image upload") from None
    name = f"img_{uuid4().hex}{extension}"
    (_directory(request) / name).write_bytes(content)
    return {"image_url": f"/api/v1/images/{name}"}


@router.get("/{image_name}")
async def get_image(request: Request, image_name: str) -> FileResponse:
    path = _directory(request) / Path(image_name).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)

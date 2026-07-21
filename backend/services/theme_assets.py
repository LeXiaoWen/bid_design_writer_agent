from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .workbench_store import ensure_private_directory, restrict_file_permissions


MAX_THEME_IMAGE_BYTES = 16 * 1024 * 1024
MAX_THEME_IMAGE_DIMENSION = 16_384
MAX_THEME_IMAGE_PIXELS = 50_000_000
ALLOWED_THEME_IMAGES = {
    ".png": ("PNG", {"image/png"}),
    ".jpg": ("JPEG", {"image/jpeg", "image/jpg"}),
    ".jpeg": ("JPEG", {"image/jpeg", "image/jpg"}),
    ".webp": ("WEBP", {"image/webp"}),
}


@dataclass(frozen=True)
class ThemeImageInfo:
    extension: str
    media_type: str
    width: int
    height: int


def validate_theme_image(filename: str, content: bytes, content_type: str | None) -> ThemeImageInfo:
    extension = Path(filename).suffix.lower()
    expected = ALLOWED_THEME_IMAGES.get(extension)
    if not expected:
        raise ValueError("主题背景仅支持 PNG、JPEG 或 WebP 图片。")
    if not content or len(content) > MAX_THEME_IMAGE_BYTES:
        raise ValueError("主题背景图片不能超过 16MB。")
    expected_format, expected_media_types = expected
    if content_type and content_type not in expected_media_types:
        raise ValueError("主题背景的文件扩展名与 MIME 类型不一致。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                width, height = image.size
                image_format = image.format
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("主题背景图片的像素数量过大。") from None
    except (OSError, UnidentifiedImageError):
        raise ValueError("主题背景不是有效图片。") from None
    if image_format != expected_format:
        raise ValueError("主题背景的文件扩展名与实际图片格式不一致。")
    if width > MAX_THEME_IMAGE_DIMENSION or height > MAX_THEME_IMAGE_DIMENSION or width * height > MAX_THEME_IMAGE_PIXELS:
        raise ValueError("主题背景图片的尺寸或像素数量过大。")
    return ThemeImageInfo(extension=extension, media_type=next(iter(expected_media_types)), width=width, height=height)


def user_theme_directory(root: Path, user_id: str) -> Path:
    return ensure_private_directory(root / "themes" / user_id)


def save_theme_image(root: Path, user_id: str, file_name: str, content: bytes) -> Path:
    target = user_theme_directory(root, user_id) / file_name
    target.write_bytes(content)
    restrict_file_permissions(target)
    return target

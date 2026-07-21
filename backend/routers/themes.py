from __future__ import annotations

import logging
import os
import random
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from ..schemas import ThemeActivateRequest, ThemeAppearance, ThemeListResponse, UserTheme
from ..services.theme_assets import ALLOWED_THEME_IMAGES, MAX_THEME_IMAGE_BYTES, save_theme_image, user_theme_directory, validate_theme_image
from ..services.workbench_store import data_dir, workbench_store
from .dependencies import current_user


logger = logging.getLogger(__name__)
router = APIRouter()
SYSTEM_THEME_ID = "system"


def _resolve_default_images_dir() -> Path | None:
    """Resolve the default images directory across dev and packaged modes."""
    override = os.getenv("AI_WORKBENCH_IMAGES_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    candidates: list[Path] = []

    # PyInstaller onedir: files land under sys._MEIPASS
    frozen_dir = getattr(sys, "_MEIPASS", None)
    if frozen_dir:
        candidates.append(Path(frozen_dir) / "images")

    # Frozen executable's directory (also works for Electron extraResources)
    executable = getattr(sys, "executable", None)
    if executable:
        candidates.append(Path(executable).parent / "images")

    # Dev/source tree fallback
    candidates.append(Path(__file__).resolve().parents[2] / "images")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    logger.debug("No default images directory found; candidates: %s", [str(c) for c in candidates])
    return None


def theme_response(theme: UserTheme) -> UserTheme:
    if theme.source == "custom":
        return theme.model_copy(update={"image_url": f"/api/v1/themes/{theme.id}/image"})
    return theme


def _fast_image_info(path: Path) -> tuple[str, str, int, int] | None:
    """Return (extension, media_type, width, height) for a bundled image without full decode."""
    extension = path.suffix.lower()
    if extension not in ALLOWED_THEME_IMAGES:
        return None
    expected_format, expected_media_types = ALLOWED_THEME_IMAGES[extension]
    try:
        with Image.open(path) as image:
            if image.format != expected_format:
                return None
            width, height = image.size
    except Exception:
        return None
    return extension, next(iter(expected_media_types)), width, height


def _seed_default_themes(user_id: str) -> tuple[list[UserTheme], bool]:
    """Seed user themes from the default images directory when the user has no custom themes.

    Returns (themes, was_seeded).
    """
    existing = workbench_store.list_user_themes(user_id)
    if existing:
        return existing, False

    default_dir = _resolve_default_images_dir()
    if not default_dir:
        return [], False

    candidate_paths = [
        path for path in default_dir.iterdir()
        if path.suffix.lower() in ALLOWED_THEME_IMAGES and path.stat().st_size <= MAX_THEME_IMAGE_BYTES
    ]
    candidate_paths.sort()
    if not candidate_paths:
        logger.warning("No valid default images found in %s", default_dir)
        return [], False

    logger.info("Seeding default themes for user %s from %s", user_id, default_dir)
    themes: list[UserTheme] = []
    for path in candidate_paths:
        info = _fast_image_info(path)
        if not info:
            logger.warning("Skipping default image %s: unreadable or wrong format", path.name)
            continue
        extension, media_type, width, height = info
        theme_id = str(uuid4())
        stored_name = f"{theme_id}{extension}"
        try:
            content = path.read_bytes()
            image_path = save_theme_image(data_dir(), user_id, stored_name, content)
            theme = workbench_store.create_user_theme(
                user_id,
                theme_id=theme_id,
                name=path.stem or "默认背景",
                image_path=str(image_path.relative_to(data_dir())),
                media_type=media_type,
                width=width,
                height=height,
                appearance=ThemeAppearance.AUTO,
            )
            themes.append(theme)
        except Exception:
            target = user_theme_directory(data_dir(), user_id) / stored_name
            target.unlink(missing_ok=True)
            logger.exception("Failed to seed default theme from %s", path.name)
            continue

    if themes:
        logger.info("Seeded %d default theme(s) for user %s", len(themes), user_id)
    return themes, bool(themes)


@router.get("/api/v1/themes", response_model=ThemeListResponse)
def list_themes(request: Request):
    user_id = current_user(request).id
    user_themes, was_seeded = _seed_default_themes(user_id)
    themes = [UserTheme(id=SYSTEM_THEME_ID, name="系统工作台", source="system")]
    themes.extend(theme_response(theme) for theme in user_themes)

    active_theme_id = workbench_store.get_active_theme_id(user_id)
    if was_seeded and user_themes:
        active_theme_id = random.choice(user_themes).id
        workbench_store.set_active_theme_id(user_id, active_theme_id)
    elif active_theme_id != SYSTEM_THEME_ID and not any(theme.id == active_theme_id for theme in themes):
        active_theme_id = SYSTEM_THEME_ID

    return ThemeListResponse(active_theme_id=active_theme_id, themes=themes)


@router.post("/api/v1/themes", response_model=UserTheme)
async def create_theme(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(default=""),
    appearance: ThemeAppearance = Form(default=ThemeAppearance.AUTO),
):
    user_id = current_user(request).id
    content = await file.read(MAX_THEME_IMAGE_BYTES + 1)
    try:
        info = validate_theme_image(file.filename or "", content, file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    title = name.strip() or Path(file.filename or "主题背景").stem or "主题背景"
    if len(title) > 80:
        raise HTTPException(status_code=422, detail="主题名称不能超过 80 个字符。")
    theme_id = str(uuid4())
    stored_name = f"{theme_id}{info.extension}"
    image_path = save_theme_image(data_dir(), user_id, stored_name, content)
    try:
        theme = workbench_store.create_user_theme(
            user_id,
            theme_id=theme_id,
            name=title,
            image_path=str(image_path.relative_to(data_dir())),
            media_type=info.media_type,
            width=info.width,
            height=info.height,
            appearance=appearance,
        )
    except Exception:
        image_path.unlink(missing_ok=True)
        raise
    workbench_store.set_active_theme_id(user_id, theme.id)
    return theme_response(theme)


@router.patch("/api/v1/themes/active", response_model=ThemeListResponse)
def activate_theme(request: Request, payload: ThemeActivateRequest):
    user_id = current_user(request).id
    if payload.theme_id != SYSTEM_THEME_ID:
        try:
            workbench_store.get_user_theme(user_id, payload.theme_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="主题不存在。") from exc
    workbench_store.set_active_theme_id(user_id, payload.theme_id)
    return list_themes(request)


@router.delete("/api/v1/themes/{theme_id}")
def delete_theme(theme_id: str, request: Request):
    user_id = current_user(request).id
    if theme_id == SYSTEM_THEME_ID:
        raise HTTPException(status_code=400, detail="系统工作台主题不能删除。")
    try:
        theme = workbench_store.delete_user_theme(user_id, theme_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="主题不存在。") from exc
    path = data_dir() / theme.image_path
    path.unlink(missing_ok=True)
    if workbench_store.get_active_theme_id(user_id) == theme_id:
        workbench_store.set_active_theme_id(user_id, SYSTEM_THEME_ID)
    return {"ok": True}


@router.get("/api/v1/themes/{theme_id}/image")
def get_theme_image(theme_id: str, request: Request):
    try:
        theme = workbench_store.get_user_theme(current_user(request).id, theme_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="主题不存在。") from exc
    path = data_dir() / theme.image_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="主题图片不存在。")
    return FileResponse(path, media_type=theme.media_type, headers={"Cache-Control": "private, max-age=3600"})

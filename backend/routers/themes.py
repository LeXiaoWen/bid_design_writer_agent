from __future__ import annotations

import random
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..schemas import ThemeActivateRequest, ThemeAppearance, ThemeListResponse, UserTheme
from ..services.theme_assets import ALLOWED_THEME_IMAGES, MAX_THEME_IMAGE_BYTES, save_theme_image, user_theme_directory, validate_theme_image
from ..services.workbench_store import data_dir, workbench_store
from .dependencies import current_user


router = APIRouter()
SYSTEM_THEME_ID = "system"
DEFAULT_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"


def theme_response(theme: UserTheme) -> UserTheme:
    if theme.source == "custom":
        return theme.model_copy(update={"image_url": f"/api/v1/themes/{theme.id}/image"})
    return theme


def _seed_default_themes(user_id: str) -> tuple[list[UserTheme], bool]:
    """Seed user themes from project-root images/ when the user has no custom themes.

    Returns (themes, was_seeded).
    """
    existing = workbench_store.list_user_themes(user_id)
    if existing or not DEFAULT_IMAGES_DIR.is_dir():
        return existing, False

    themes: list[UserTheme] = []
    for path in sorted(DEFAULT_IMAGES_DIR.iterdir()):
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_THEME_IMAGES:
            continue
        content = path.read_bytes()
        if len(content) > MAX_THEME_IMAGE_BYTES:
            continue
        _, expected_media_type = ALLOWED_THEME_IMAGES[suffix]
        try:
            info = validate_theme_image(path.name, content, expected_media_type)
        except ValueError:
            continue
        theme_id = str(uuid4())
        stored_name = f"{theme_id}{info.extension}"
        try:
            image_path = save_theme_image(data_dir(), user_id, stored_name, content)
            theme = workbench_store.create_user_theme(
                user_id,
                theme_id=theme_id,
                name=path.stem or "默认背景",
                image_path=str(image_path.relative_to(data_dir())),
                media_type=info.media_type,
                width=info.width,
                height=info.height,
                appearance=ThemeAppearance.AUTO,
            )
            themes.append(theme)
        except Exception:
            target = user_theme_directory(data_dir(), user_id) / stored_name
            target.unlink(missing_ok=True)
            continue
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

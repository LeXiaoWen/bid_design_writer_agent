from fastapi import APIRouter, HTTPException, Request

from ..schemas import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthRegisterRequest,
    AuthStatus,
    AuthUser,
    ChangePasswordRequest,
)
from ..services.auth import AuthRateLimitError, change_password, login_user, logout_token, register_user, user_from_token
from .dependencies import bearer_token, current_user

router = APIRouter()

@router.get("/api/v1/auth/status", response_model=AuthStatus)
def get_auth_status(request: Request):
    user = user_from_token(bearer_token(request))
    return AuthStatus(authenticated=user is not None, username=user.username if user else None)


@router.post("/api/v1/auth/register", response_model=AuthLoginResponse)
def register_auth(request: AuthRegisterRequest):
    try:
        register_user(request.username, request.password)
        return login_user(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/auth/login", response_model=AuthLoginResponse)
def login_auth(request: AuthLoginRequest):
    try:
        return login_user(request.username, request.password)
    except AuthRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/api/v1/auth/logout")
def logout_auth(request: Request):
    logout_token(bearer_token(request))
    return {"ok": True}


@router.get("/api/v1/me", response_model=AuthUser)
def get_me(request: Request):
    return current_user(request)


@router.post("/api/v1/auth/change-password")
def change_auth_password(request: Request, payload: ChangePasswordRequest):
    try:
        change_password(current_user(request), payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}

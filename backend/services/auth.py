from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from ..schemas import AuthLoginResponse, AuthUser
from .workbench_store import utc_now, workbench_store


logger = logging.getLogger("bid_design_writer.auth")


SESSION_HOURS = 8
MAX_LOGIN_FAILURES = 5
LOGIN_LOCK_SECONDS = 60
_hasher = PasswordHasher()
_login_failures: dict[str, tuple[int, datetime | None]] = {}


class AuthRateLimitError(ValueError):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()


def _login_key(username: str) -> str:
    return username.strip().casefold() or "<empty>"


def _check_login_allowed(username: str) -> None:
    key = _login_key(username)
    count, locked_until = _login_failures.get(key, (0, None))
    if count >= MAX_LOGIN_FAILURES and locked_until and locked_until > datetime.now(timezone.utc):
        raise AuthRateLimitError("登录失败次数过多，请稍后再试。")
    if locked_until and locked_until <= datetime.now(timezone.utc):
        _login_failures.pop(key, None)


def _record_login_failure(username: str) -> None:
    key = _login_key(username)
    count, locked_until = _login_failures.get(key, (0, None))
    count += 1
    if count >= MAX_LOGIN_FAILURES:
        locked_until = datetime.now(timezone.utc) + timedelta(seconds=LOGIN_LOCK_SECONDS)
    _login_failures[key] = (count, locked_until)


def _clear_login_failures(username: str) -> None:
    _login_failures.pop(_login_key(username), None)


def register_user(username: str, password: str) -> AuthUser:
    return workbench_store.create_user(username.strip(), _hasher.hash(password))


def login_user(username: str, password: str) -> AuthLoginResponse:
    _check_login_allowed(username)
    row = workbench_store.get_user_auth_record_by_username(username)
    if not row:
        _record_login_failure(username)
        raise ValueError("用户名或密码错误。")
    try:
        verified = _hasher.verify(row["password_hash"], password)
    except (VerifyMismatchError, VerificationError):
        verified = False
    if not verified:
        _record_login_failure(username)
        raise ValueError("用户名或密码错误。")

    _clear_login_failures(username)
    if _hasher.check_needs_rehash(row["password_hash"]):
        workbench_store.update_user_password_hash(row["id"], _hasher.hash(password))

    try:
        workbench_store.migrate_legacy_secrets_on_login(row["id"], password)
    except Exception:
        # Authentication must remain available even if an old machine has no keychain.
        # The migration has already created a password-encrypted recovery artifact.
        logger.warning("credential migration was deferred", extra={"user_id": row["id"]}, exc_info=True)

    token = secrets.token_urlsafe(32)
    expires_at = _expires_at()
    workbench_store.create_auth_session(row["id"], _hash_token(token), expires_at)
    user = workbench_store.update_user_last_login(row["id"])
    return AuthLoginResponse(token=token, expires_at=expires_at, username=user.username)


def user_from_token(token: str | None) -> AuthUser | None:
    if not token:
        return None
    return workbench_store.get_auth_session_user(_hash_token(token), utc_now())


def logout_token(token: str | None) -> None:
    if token:
        workbench_store.revoke_auth_session(_hash_token(token))


def change_password(user: AuthUser, current_password: str, new_password: str) -> None:
    row = workbench_store.get_user_auth_record_by_username(user.username)
    if not row:
        raise ValueError("用户不存在。")
    try:
        verified = _hasher.verify(row["password_hash"], current_password)
    except (VerifyMismatchError, VerificationError):
        verified = False
    if not verified:
        raise ValueError("当前密码错误。")
    workbench_store.update_user_password_hash(user.id, _hasher.hash(new_password))

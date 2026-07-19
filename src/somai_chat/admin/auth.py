"""Administrator session and CSRF helpers."""

import hmac
import secrets

from fastapi import HTTPException, Request


def verify_password(candidate: str, configured: str) -> bool:
    return hmac.compare_digest(candidate, configured)


def establish_session(request: Request, username: str) -> str:
    csrf_token = secrets.token_urlsafe(24)
    request.session.clear()
    request.session.update({"admin": username, "csrf": csrf_token})
    return csrf_token


def require_admin(request: Request) -> str:
    username = request.session.get("admin")
    if not isinstance(username, str):
        raise HTTPException(status_code=401, detail="Authentication required")
    return username


def require_csrf(request: Request) -> None:
    require_admin(request)
    expected = request.session.get("csrf")
    received = request.headers.get("X-CSRF-Token")
    if not isinstance(expected, str) or not isinstance(received, str) or not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="CSRF validation failed")

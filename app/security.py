import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AdminSession


def make_password_hash(password: str) -> str:
    iterations = 310_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key, salt="admin-session")


def create_admin_session(db: Session) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=settings.admin_session_days)
    db.add(AdminSession(token=token, expires_at=expires_at))
    db.commit()
    return _serializer().dumps({"token": token})


def get_admin_session(db: Session, signed_cookie: str | None) -> AdminSession | None:
    if not signed_cookie:
        return None
    try:
        payload = _serializer().loads(signed_cookie, max_age=get_settings().admin_session_days * 86400)
    except (BadSignature, SignatureExpired):
        return None
    token = payload.get("token") if isinstance(payload, dict) else None
    if not token:
        return None
    session = db.scalar(select(AdminSession).where(AdminSession.token == token))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not session or session.expires_at <= now:
        if session:
            db.delete(session)
            db.commit()
        return None
    return session


def revoke_admin_session(db: Session, signed_cookie: str | None) -> None:
    session = get_admin_session(db, signed_cookie)
    if session:
        db.delete(session)
        db.commit()


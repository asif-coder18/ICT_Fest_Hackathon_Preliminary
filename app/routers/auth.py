"""Authentication endpoints: register, login, refresh, logout."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_payload,
    hash_password,
    revoke_access_token,
    verify_password,
    _revoked_tokens,
    _revoked_tokens_lock,
)
from ..database import get_db
from ..errors import AppError
from ..models import Organization, User
from ..schemas import LoginRequest, RefreshRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    # FIX #4 (Race condition): wrap org creation + user check in a single
    # try/except so concurrent registrations with the same org_name don't
    # both pass the "org is None" check and double-insert.
    org = db.query(Organization).filter(Organization.name == payload.org_name).first()
    role = "admin" if org is None else "member"
    if org is None:
        try:
            org = Organization(name=payload.org_name)
            db.add(org)
            db.commit()
            db.refresh(org)
        except Exception:
            db.rollback()
            # Another request won the race — fetch the existing org.
            org = db.query(Organization).filter(Organization.name == payload.org_name).first()
            if org is None:
                raise
            role = "member"

    existing = (
        db.query(User)
        .filter(User.org_id == org.id, User.username == payload.username)
        .first()
    )
    # FIX #5: was silently returning existing user data — raise 409 instead.
    if existing is not None:
        raise AppError(409, "USERNAME_TAKEN", "Username already registered in this organisation")

    user = User(
        org_id=org.id,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "user_id": user.id,
        "org_id": org.id,
        "username": user.username,
        "role": user.role,
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.name == payload.org_name).first()
    user = None
    if org is not None:
        user = (
            db.query(User)
            .filter(User.org_id == org.id, User.username == payload.username)
            .first()
        )
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
    }


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise AppError(401, "UNAUTHORIZED", "Wrong token type")
    # FIX #6: invalidate the used refresh token so it cannot be reused.
    with _revoked_tokens_lock:
        jti = data.get("jti", "")
        if jti in _revoked_tokens:
            raise AppError(401, "UNAUTHORIZED", "Refresh token has already been used")
        _revoked_tokens.add(jti)
    user = db.query(User).filter(User.id == int(data["sub"])).first()
    if user is None:
        raise AppError(401, "UNAUTHORIZED", "Unknown user")
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
    }


@router.post("/logout")
def logout(payload: dict = Depends(get_token_payload)):
    revoke_access_token(payload)
    return {"status": "ok"}

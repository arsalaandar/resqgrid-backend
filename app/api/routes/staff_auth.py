from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_user
from app.core.config import settings
from app.core.passwords import (
    hash_password,
    verify_password,
    verify_password_timing_safe,
)
from app.core.rate_limit import limiter
from app.core.roles import STAFF_ROLES
from app.core.security import create_access_token
from app.db.dependencies import get_db
from app.models.user import User
from app.schemas.password_change import (
    PasswordChangeRequest,
    PasswordChangeResponse,
)
from app.schemas.staff_auth import (
    StaffLoginRequest,
    StaffLoginResponse,
)
from app.services.refresh_tokens import create_refresh_session

router = APIRouter(
    prefix="/api/v1/auth/staff",
    tags=["Staff Authentication"],
)


@router.post(
    "/login",
    response_model=StaffLoginResponse,
)
@limiter.limit("5/minute")
def staff_login(
    request: Request,
    payload: StaffLoginRequest,
    db: Session = Depends(get_db),
):
    account = db.scalar(select(User).where(User.phone == payload.phone))

    # Always perform one password verification, even for unknown phones, so
    # response time does not reveal which numbers are staff accounts.
    password_ok, upgraded_hash = verify_password_timing_safe(
        payload.password,
        account.password_hash if account else None,
    )

    # Use the same public error for unknown users and wrong passwords.
    if (
        account is None
        or not password_ok
        or account.role.upper() not in STAFF_ROLES
        or not account.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone number or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if upgraded_hash:
        # Transparently move the stored hash to current Argon2 parameters.
        try:
            account.password_hash = upgraded_hash
            db.commit()
        except SQLAlchemyError:
            db.rollback()

    access_token = create_access_token(
        user_id=account.id,
        token_version=account.token_version,
    )

    refresh_token, refresh_expiry = create_refresh_session(
        db=db,
        user=account,
    )

    return StaffLoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=max(
            0,
            int((refresh_expiry - datetime.now(UTC)).total_seconds()),
        ),
        user_id=account.id,
        role=account.role.upper(),
        designation=account.designation,
        department=account.department,
        must_change_password=account.must_change_password,
    )


@router.post(
    "/change-password",
    response_model=PasswordChangeResponse,
)
@limiter.limit("5/minute")
def change_staff_password(
    request: Request,
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    if current_user.role.upper() not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for staff accounts only.",
        )

    if not current_user.password_hash or not verify_password(
        payload.current_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    if verify_password(
        payload.new_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a password different from your current password.",
        )

    try:
        new_password_hash = hash_password(payload.new_password)
        current_user.password_hash = new_password_hash
        current_user.must_change_password = False
        current_user.token_version += 1
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again.",
        ) from exc

    return PasswordChangeResponse(
        message="Password changed successfully.",
        must_change_password=False,
    )

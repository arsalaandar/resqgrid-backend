from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.db.dependencies import get_db
from app.schemas.token import (
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    TokenRefreshResponse,
)
from app.services.refresh_tokens import (
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Token Management"],
)


@router.post("/refresh", response_model=TokenRefreshResponse)
@limiter.limit("30/minute")
def refresh_access_token(
    request: Request,
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> TokenRefreshResponse:
    user, new_refresh_token, refresh_expiry = rotate_refresh_token(
        db=db,
        raw_token=payload.refresh_token,
    )

    access_token = create_access_token(
        user_id=user.id,
        token_version=user.token_version,
    )

    refresh_expires_in = max(
        0,
        int((refresh_expiry - datetime.now(UTC)).total_seconds()),
    )

    return TokenRefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=refresh_expires_in,
        user_id=user.id,
        role=user.role.upper(),
    )


@router.post("/logout", response_model=LogoutResponse)
@limiter.limit("30/minute")
def logout(
    request: Request,
    payload: LogoutRequest,
    db: Session = Depends(get_db),
) -> LogoutResponse:
    revoke_refresh_token(
        db=db,
        raw_token=payload.refresh_token,
    )

    return LogoutResponse(
        message="Logout successful.",
    )

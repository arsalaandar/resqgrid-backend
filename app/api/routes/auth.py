
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.roles import Role
from app.core.security import create_access_token
from app.db.dependencies import get_db
from app.models.user import User
from app.schemas.otp import (
    CitizenLoginResponse,
    OTPMessageResponse,
    OTPRequest,
    OTPVerify,
)
from app.services.otp import request_otp, verify_otp
from app.services.refresh_tokens import create_refresh_session

router = APIRouter(
    prefix="/api/v1/auth/citizen",
    tags=["Citizen Authentication"],
)


@router.post(
    "/request-otp",
    response_model=OTPMessageResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("3/minute")
def request_citizen_otp(
    request: Request,
    payload: OTPRequest,
    db: Session = Depends(get_db),
):
    try:
        request_otp(db=db, phone=payload.phone)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTP service temporarily unavailable.",
        ) from exc

    return OTPMessageResponse(
        message="If the request can be processed, an OTP will be sent."
    )


@router.post(
    "/verify-otp",
    response_model=CitizenLoginResponse,
)
@limiter.limit("10/minute")
def verify_citizen_otp(
    request: Request,
    payload: OTPVerify,
    db: Session = Depends(get_db),
):
    # 1. Verify and consume the OTP.
    verified = verify_otp(
        db=db,
        phone=payload.phone,
        code=payload.code,
    )

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP.",
        )

    # 2. Find an existing account by verified phone number.
    account = db.query(User).filter(User.phone == payload.phone).first()

    if account is not None:
        # Citizen OTP login must never grant access to an official/admin.
        if account.role.upper() != Role.CITIZEN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account cannot use citizen login.",
            )

        if not account.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is inactive.",
            )

        if not account.is_verified:
            account.is_verified = True

            try:
                db.commit()
                db.refresh(account)
            except SQLAlchemyError as exc:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Could not update the account.",
                ) from exc

    else:
        # 3. New accounts always receive CITIZEN from the server.
        account = User(
            phone=payload.phone,
            role=Role.CITIZEN.value,
            is_active=True,
            is_verified=True,
        )

        try:
            db.add(account)
            db.commit()
            db.refresh(account)

        except IntegrityError:
            db.rollback()

            # A concurrent request may have created the account.
            account = (
                db.query(User)
                .filter(User.phone == payload.phone)
                .first()
            )

            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Account creation conflict. Request a new OTP.",
                ) from None

            if account.role.upper() != Role.CITIZEN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This account cannot use citizen login.",
                ) from None

            if not account.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This account is inactive.",
                ) from None

    # 4. Issue tokens only after authentication and account checks.
    access_token = create_access_token(
        user_id=account.id,
        token_version=account.token_version,
    )

    refresh_token, refresh_expiry = create_refresh_session(
        db=db,
        user=account,
    )

    return CitizenLoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=max(
            0,
            int(
                (refresh_expiry - datetime.now(UTC)).total_seconds()
            ),
        ),
        user_id=account.id,
        role=account.role.upper(),
    )

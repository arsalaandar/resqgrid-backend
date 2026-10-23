from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )

    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Official/admin profile information
    designation: Mapped[str | None] = mapped_column(String(100), nullable=True)

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)

    assigned_district: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    assigned_tehsil: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Who created this account (for administrative accountability)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # Pass a callable: datetime.now(UTC) here would be evaluated once at
        # import time and stamp every user with the application start time.
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

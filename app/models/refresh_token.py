from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Store only the SHA-256 hash of the opaque token, never the raw token.
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )

    # Tokens issued during one login session share a family ID.
    family_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # Incremented when the user changes their password or revokes sessions.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Absolute session expiry never changes during refresh rotation.
    session_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id"),
        nullable=True,
    )

    __table_args__ = (Index("ix_refresh_tokens_user_family", "user_id", "family_id"),)

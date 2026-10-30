import getpass
import re
import sys

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.passwords import hash_password
from app.core.roles import Role
from app.db.database import SessionLocal
from app.models.user import User

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def main() -> None:
    print("ResQGrid - Initial Super Admin Setup")
    print("------------------------------------")

    phone = input("Super Admin phone number (international format): ").strip()

    if not PHONE_PATTERN.fullmatch(phone):
        print(
            "Invalid phone number format. "
            "Use international format, e.g. +91 followed by your number."
        )
        sys.exit(1)

    password = getpass.getpass("Choose a strong password: ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        print("Passwords do not match.")
        sys.exit(1)

    if len(password) < 12:
        print("Password must contain at least 12 characters.")
        sys.exit(1)

    if len(password) > 1024:
        print("Password is too long.")
        sys.exit(1)

    db = SessionLocal()

    try:
        existing_super_admin = db.scalar(
            select(User.id)
            .where(func.upper(User.role) == Role.SUPER_ADMIN.value)
            .limit(1)
        )

        if existing_super_admin is not None:
            print("A Super Admin already exists. Setup cancelled.")
            sys.exit(1)

        existing_user = db.scalar(select(User.id).where(User.phone == phone).limit(1))

        if existing_user is not None:
            print("This phone number already belongs to an account.")
            print("Use a separate account or implement a controlled promotion process.")
            sys.exit(1)

        account = User(
            phone=phone,
            password_hash=hash_password(password),
            role=Role.SUPER_ADMIN.value,
            designation="State Administrator",
            department="Disaster Management",
            assigned_district=None,
            assigned_tehsil=None,
            must_change_password=False,
            created_by_id=None,
            is_active=True,
            is_verified=True,
        )

        db.add(account)
        db.commit()

        print("Super Admin account created successfully.")
        print("Keep the phone number and password secure.")
        print("The password itself was not stored or displayed.")

    except IntegrityError:
        db.rollback()
        print("Account creation conflicted with an existing database record.")
        print("No account was created by this transaction.")
        sys.exit(1)

    except Exception:
        db.rollback()
        print("Setup failed. Check the application logs and database configuration.")
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()

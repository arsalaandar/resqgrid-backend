from app.services.user import list_users, register_user
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.schemas.user import UserCreate

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.post("/")
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
):
    return register_user(
        db=db,
        phone=user_data.phone,
        email=user_data.email,
        role=user_data.role,
    )


@router.get("/")
def get_users(
    db: Session = Depends(get_db),
):
    return list_users(db)

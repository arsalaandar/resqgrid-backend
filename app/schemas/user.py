from pydantic import BaseModel


class UserCreate(BaseModel):
    phone: str | None = None
    email: str | None = None
    role: str

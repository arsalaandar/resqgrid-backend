from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.core.roles import Role
from app.models.user import User


def require_roles(*allowed_roles: str) -> Callable:
    # Role(...) raises ValueError for an unknown name, so a typo such as
    # "ADMN" fails when the route is defined instead of silently denying
    # everyone at request time.
    normalized_roles = {Role(str(role).upper()) for role in allowed_roles}

    def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_role = current_user.role.upper()

        if user_role not in normalized_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )

        return current_user

    return role_checker

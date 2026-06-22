"""Login endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import create_access_token, verify_password
from app.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.auth import TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_repo: UserRepoDep,
) -> TokenResponse:
    user = await user_repo.find_by_email(form_data.username)
    if user is None or not await verify_password(
        form_data.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role.value,
            "is_active": user.is_active,
        }
    )
    return TokenResponse(access_token=token, token_type="bearer")

"""Authentication endpoints."""
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import authenticate_user, create_access_token, get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import AuthError


router = APIRouter(prefix="/auth", tags=["Auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_id: str
    email: str


class CurrentUserResponse(BaseModel):
    email: str
    full_name: str | None
    client_id: str
    is_superuser: bool


@router.post("/token", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise AuthError("Invalid email or password")
    token = create_access_token(subject=user.email, client_id=user.client_id)
    return TokenResponse(
        access_token=token,
        client_id=user.client_id,
        email=user.email,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(user: User = Depends(get_current_user)):
    return CurrentUserResponse(
        email=user.email,
        full_name=user.full_name,
        client_id=user.client_id,
        is_superuser=user.is_superuser,
    )

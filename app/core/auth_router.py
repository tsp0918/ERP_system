"""Authentication endpoints."""
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import authenticate_user, create_access_token, create_service_token, get_current_user
from app.core.auth_models import User
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthError


router = APIRouter(prefix="/auth", tags=["Auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_id: str
    email: str


class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_id: str
    email: str
    expires_in: int


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


@router.post("/service-token", response_model=ServiceTokenResponse)
def service_token(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Issue a long-lived token for machine-to-machine callers.

    Same credentials as /auth/token, but the returned JWT is valid for
    M2M_TOKEN_EXPIRE_HOURS (default 24 h) instead of ACCESS_TOKEN_EXPIRE_MINUTES.
    Intended for batch integration processes (CRM scheduled jobs, ETL pipelines)
    that cannot re-authenticate on every request or every hour.
    """
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise AuthError("Invalid email or password")
    token = create_service_token(subject=user.email, client_id=user.client_id)
    return ServiceTokenResponse(
        access_token=token,
        client_id=user.client_id,
        email=user.email,
        expires_in=settings.M2M_TOKEN_EXPIRE_HOURS * 3600,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(user: User = Depends(get_current_user)):
    return CurrentUserResponse(
        email=user.email,
        full_name=user.full_name,
        client_id=user.client_id,
        is_superuser=user.is_superuser,
    )

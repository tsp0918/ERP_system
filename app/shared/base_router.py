"""Generic CRUD router factory.

Use this to mount a standard set of REST endpoints for any resource:
    GET    /{resource}           list (paginated)
    POST   /{resource}           create
    GET    /{resource}/{id}      retrieve
    PUT    /{resource}/{id}      update (partial)
    DELETE /{resource}/{id}      delete

Custom endpoints can be added on top by attaching extra routes to the returned
router object. This keeps boilerplate out of each module while leaving the
domain free to add specialized actions (release, post, cancel, etc.).
"""
from typing import Callable, Optional, Type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.shared.base_repository import BaseRepository
from app.shared.base_schemas import PaginatedResponse


def create_crud_router(
    *,
    prefix: str,
    tags: list[str],
    model: Type,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    response_schema: Type[BaseModel],
    resource_name: str,
    pre_create: Optional[Callable] = None,
    post_create: Optional[Callable] = None,
) -> APIRouter:
    """Build a router that exposes standard CRUD on `model`.

    Args:
        pre_create:  hook(db, payload_dict, user) -> payload_dict.
                     Use to enrich the payload before insert (e.g. set tenant).
        post_create: hook(db, instance, user) -> None.
                     Use to trigger side-effects (e.g. integrations).
    """
    router = APIRouter(prefix=prefix, tags=tags)

    def repo(db: Session) -> BaseRepository:
        return BaseRepository(model, db)

    @router.get("", response_model=PaginatedResponse[response_schema])
    def list_items(
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        r = repo(db)
        items = r.list(client_id=user.client_id, skip=skip, limit=limit)
        total = r.count(client_id=user.client_id)
        return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)

    @router.get("/{item_id}", response_model=response_schema)
    def get_item(
        item_id: int,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        instance = repo(db).get(item_id, client_id=user.client_id)
        if instance is None:
            raise NotFoundError(resource_name, item_id)
        return instance

    @router.post("", response_model=response_schema, status_code=status.HTTP_201_CREATED)
    def create_item(
        payload: create_schema,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        data = payload.model_dump(exclude_unset=True)
        data["client_id"] = user.client_id
        data["created_by"] = user.email
        data["updated_by"] = user.email
        if pre_create:
            data = pre_create(db, data, user)
        instance = repo(db).create(data)
        if post_create:
            post_create(db, instance, user)
        db.commit()
        db.refresh(instance)
        return instance

    @router.put("/{item_id}", response_model=response_schema)
    def update_item(
        item_id: int,
        payload: update_schema,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        r = repo(db)
        instance = r.get(item_id, client_id=user.client_id)
        if instance is None:
            raise NotFoundError(resource_name, item_id)
        data = payload.model_dump(exclude_unset=True)
        data["updated_by"] = user.email
        r.update(instance, data)
        db.commit()
        db.refresh(instance)
        return instance

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(
        item_id: int,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        r = repo(db)
        instance = r.get(item_id, client_id=user.client_id)
        if instance is None:
            raise NotFoundError(resource_name, item_id)
        r.delete(instance)
        db.commit()

    return router

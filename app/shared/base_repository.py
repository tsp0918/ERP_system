"""Generic repository providing standard CRUD over any SQLAlchemy model.

Subclasses can override or extend without re-implementing the basics.
"""
from typing import Any, Generic, List, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import Base


ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """CRUD repository. Tenant filtering is automatic if `tenant_field` exists."""

    tenant_field: str = "client_id"

    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db

    # ---- internal helpers ----
    def _tenant_filter(self, query, client_id: Optional[str]):
        if client_id and hasattr(self.model, self.tenant_field):
            return query.where(getattr(self.model, self.tenant_field) == client_id)
        return query

    def _apply_filters(self, query, filters: dict[str, Any] | None):
        if not filters:
            return query
        for key, value in filters.items():
            if value is None:
                continue
            if not hasattr(self.model, key):
                continue
            query = query.where(getattr(self.model, key) == value)
        return query

    # ---- read ----
    def get(self, id: int, client_id: Optional[str] = None) -> Optional[ModelType]:
        stmt = select(self.model).where(self.model.id == id)
        stmt = self._tenant_filter(stmt, client_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_field(self, field: str, value: Any, client_id: Optional[str] = None) -> Optional[ModelType]:
        if not hasattr(self.model, field):
            return None
        stmt = select(self.model).where(getattr(self.model, field) == value)
        stmt = self._tenant_filter(stmt, client_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        *,
        client_id: Optional[str] = None,
        filters: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 50,
        order_by: str = "id",
    ) -> List[ModelType]:
        stmt = select(self.model)
        stmt = self._tenant_filter(stmt, client_id)
        stmt = self._apply_filters(stmt, filters)
        if hasattr(self.model, order_by):
            stmt = stmt.order_by(getattr(self.model, order_by))
        stmt = stmt.offset(skip).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def count(
        self,
        *,
        client_id: Optional[str] = None,
        filters: dict[str, Any] | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(self.model)
        stmt = self._tenant_filter(stmt, client_id)
        stmt = self._apply_filters(stmt, filters)
        return self.db.execute(stmt).scalar_one()

    # ---- write ----
    def create(self, data: dict[str, Any]) -> ModelType:
        instance = self.model(**data)
        self.db.add(instance)
        self.db.flush()
        self.db.refresh(instance)
        return instance

    def update(self, instance: ModelType, data: dict[str, Any]) -> ModelType:
        for key, value in data.items():
            if value is not None and hasattr(instance, key):
                setattr(instance, key, value)
        self.db.flush()
        self.db.refresh(instance)
        return instance

    def delete(self, instance: ModelType) -> None:
        self.db.delete(instance)
        self.db.flush()

"""Shared Pydantic schemas: pagination, audit envelope, error response."""
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response schemas read from ORM objects."""
    model_config = ConfigDict(from_attributes=True)


class AuditFields(ORMModel):
    """Audit fields exposed on every response."""
    created_at: datetime
    created_by: Optional[str] = None
    updated_at: datetime
    updated_by: Optional[str] = None


class PaginationParams(BaseModel):
    """Standard pagination query parameters."""
    skip: int = Field(0, ge=0, description="Number of records to skip")
    limit: int = Field(50, ge=1, le=500, description="Max records to return")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response envelope."""
    items: List[T]
    total: int
    skip: int
    limit: int


class ErrorDetail(BaseModel):
    detail: str
    code: Optional[str] = None

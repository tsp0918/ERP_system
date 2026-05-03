"""Custom exception hierarchy for the ERP system."""
from fastapi import HTTPException, status


class ERPException(HTTPException):
    """Base for all ERP-specific HTTPException subclasses."""
    pass


class NotFoundError(ERPException):
    def __init__(self, resource: str, identifier: str | int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found: {identifier}",
        )


class DuplicateError(ERPException):
    def __init__(self, resource: str, field: str, value: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{resource} with {field}='{value}' already exists",
        )


class BusinessRuleError(ERPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=message,
        )


class IntegrationError(ERPException):
    def __init__(self, service: str, message: str):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{service} integration failed: {message}",
        )


class AuthError(ERPException):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )

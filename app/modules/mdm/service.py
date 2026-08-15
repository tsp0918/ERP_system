"""MDM service layer - business rules + integration orchestration."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateError
from app.core.numbering import next_number
from app.modules.mdm import models, schemas
from app.shared.base_repository import BaseRepository


class MaterialService:
    """Material lifecycle including AI_TradeManagement integration."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.Material, db)

    def create(
        self,
        payload: schemas.MaterialCreate,
        client_id: str,
        user_email: str,
    ) -> models.Material:
        # Number range
        material_code = payload.material_code or next_number(self.db, client_id, "MATERIAL")

        # Uniqueness
        existing = self.repo.get_by_field("material_code", material_code, client_id)
        if existing:
            raise DuplicateError("Material", "material_code", material_code)

        data = payload.model_dump(exclude={"material_code", "auto_classify"}, exclude_unset=True)
        data.update({
            "material_code": material_code,
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
            "fefta_judgment": "UNKNOWN",
        })
        material = self.repo.create(data)

        # Hook for AI_TradeManagement (non-fatal: failures don't block creation)
        if payload.auto_classify:
            from app.modules.gts.service import GTSService
            try:
                GTSService(self.db).classify_material(material)
            except Exception as exc:
                # Log only; material persists with UNKNOWN judgment for retry later
                import logging
                logging.getLogger(__name__).warning(
                    "AI_TradeManagement classification failed for %s: %s",
                    material.material_code, exc,
                )

        return material


class BusinessPartnerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.BusinessPartner, db)

    def create(
        self,
        payload: schemas.BusinessPartnerCreate,
        client_id: str,
        user_email: str,
    ) -> models.BusinessPartner:
        bp_code = payload.bp_code or next_number(self.db, client_id, "BUSINESS_PARTNER")

        existing = self.repo.get_by_field("bp_code", bp_code, client_id)
        if existing:
            raise DuplicateError("BusinessPartner", "bp_code", bp_code)

        data = payload.model_dump(exclude={"bp_code", "auto_screen"}, exclude_unset=True)
        data.update({
            "bp_code": bp_code,
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
        })
        bp = self.repo.create(data)

        # Denied-party screening hook
        if payload.auto_screen:
            from app.modules.gts.service import GTSService
            try:
                GTSService(self.db).screen_business_partner(bp)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Denied-party screening failed for %s: %s", bp.bp_code, exc,
                )

        return bp


class CompanyService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.Company, db)

    def create(
        self,
        payload: schemas.CompanyCreate,
        client_id: str,
        user_email: str,
    ) -> models.Company:
        existing = self.repo.get_by_field("company_code", payload.company_code, client_id)
        if existing:
            raise DuplicateError("Company", "company_code", payload.company_code)

        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
        })
        return self.repo.create(data)


class MaterialPlantService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.MaterialPlant, db)

    def create(
        self,
        payload: schemas.MaterialPlantCreate,
        client_id: str,
        user_email: str,
    ) -> models.MaterialPlant:
        # Check uniqueness: client + material + plant
        existing = self.db.query(models.MaterialPlant).filter(
            models.MaterialPlant.client_id == client_id,
            models.MaterialPlant.material_code == payload.material_code,
            models.MaterialPlant.plant_code == payload.plant_code,
        ).first()
        if existing:
            raise DuplicateError(
                "MaterialPlant", "material_code+plant_code",
                f"{payload.material_code}/{payload.plant_code}"
            )
        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
        })
        return self.repo.create(data)

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.process_model import ProcessModel
from app.schemas.project import ProcessModelOut

router = APIRouter(prefix="/process-models", tags=["process-models"])


@router.get("", response_model=list[ProcessModelOut])
def list_process_models(db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(ProcessModel)
            .where(ProcessModel.enabled)
            .options(selectinload(ProcessModel.stages))
        )
    )

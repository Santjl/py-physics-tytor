from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import models
from app.api.deps import get_db
from app.api.routes.auth import require_admin
from app.core.config import get_settings
from app.rag.processing import process_document_background, process_document_inline
from app.schemas import DocumentRead

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are supported")

    contents = await file.read()
    document = models.Document(filename=file.filename or "upload.pdf", status="pending")
    db.add(document)
    db.commit()
    db.refresh(document)

    if settings.app_env.lower() == "test":
        process_document_inline(db, document, contents, document.filename)
    else:
        background_tasks.add_task(process_document_background, document.id, contents, document.filename)
    db.refresh(document)
    return document


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    document = db.get(models.Document, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document

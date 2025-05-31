from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas.request import TrainingRequest, RequestBatch as RequestBatchSchema, TrainingRequestSimple
from schemas.user import User as UserSchema # For current_user type hint
from crud.request import (
    get_available_training_requests,
    get_training_request_by_id,
    get_batch_by_id,
    assign_batch_to_worker as crud_assign_batch,
    update_batch_status as crud_update_batch_status
)
from models.user import RequestBatchStatus, TrainingRequestStatus # Enums for status checking/setting
from routers.auth import get_current_user

router = APIRouter()

@router.get("/requests/available", response_model=List[TrainingRequestSimple])
def list_available_requests(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user) # Ensure worker is authenticated
):
    requests_models = get_available_training_requests(db, skip=skip, limit=limit)
    response_list = []
    for req_model in requests_models:
        response_list.append(
            TrainingRequestSimple(
                id=req_model.id,
                status=req_model.status,
                created_at=req_model.created_at,
                num_batches=len(req_model.batches)
            )
        )
    return response_list

@router.post("/requests/{request_id}/take_batch", response_model=RequestBatchSchema)
def take_request_batch(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user)
):
    db_request = get_training_request_by_id(db, request_id=request_id)
    if not db_request:
        raise HTTPException(status_code=404, detail="Training request not found")
    if db_request.status == TrainingRequestStatus.COMPLETED or db_request.status == TrainingRequestStatus.FAILED:
        raise HTTPException(status_code=400, detail="This request is already completed or failed.")

    pending_batch = None
    for batch_in_request in db_request.batches:
        if batch_in_request.status == RequestBatchStatus.PENDING:
            pending_batch = batch_in_request
            break
    if not pending_batch:
        raise HTTPException(status_code=404, detail="No available (pending) batches for this request.")

    assigned_batch = crud_assign_batch(db=db, batch=pending_batch, worker_id=current_user.id)
    # TODO: Update overall TrainingRequest status logic
    return assigned_batch

@router.post("/batch/{batch_id}/complete", response_model=RequestBatchSchema)
def mark_batch_as_completed(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user)
):
    db_batch = get_batch_by_id(db, batch_id=batch_id)
    if not db_batch: raise HTTPException(status_code=404, detail="Batch not found")
    if db_batch.worker_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized for this batch.")
    if db_batch.status not in [RequestBatchStatus.ASSIGNED, RequestBatchStatus.IN_PROGRESS]:
        raise HTTPException(status_code=400, detail=f"Batch status is '{db_batch.status}'. Cannot mark completed.")
    updated_batch = crud_update_batch_status(db=db, batch=db_batch, new_status=RequestBatchStatus.COMPLETED)
    # TODO: Update overall TrainingRequest status logic (e.g., if all batches are complete)
    return updated_batch

@router.post("/batch/{batch_id}/failed", response_model=RequestBatchSchema)
def mark_batch_as_failed(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user)
):
    db_batch = get_batch_by_id(db, batch_id=batch_id)
    if not db_batch: raise HTTPException(status_code=404, detail="Batch not found")
    if db_batch.worker_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized for this batch.")
    if db_batch.status not in [RequestBatchStatus.ASSIGNED, RequestBatchStatus.IN_PROGRESS]:
         raise HTTPException(status_code=400, detail=f"Batch status is '{db_batch.status}'. Cannot mark failed.")
    updated_batch = crud_update_batch_status(db=db, batch=db_batch, new_status=RequestBatchStatus.PENDING) # Changed to PENDING on failure for re-queue
    # TODO: More sophisticated failure handling (e.g., max retries)
    return updated_batch

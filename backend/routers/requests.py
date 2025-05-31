from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from database import get_db
from schemas.request import TrainingRequestCreate, TrainingRequest as TrainingRequestSchema, TrainingRequestSimple
from schemas.user import User as UserSchema # For current_user type hint
from crud.request import create_training_request as crud_create_request, get_training_request_by_id as crud_get_request
from routers.auth import get_current_user # Import the dependency

router = APIRouter()

@router.post("/", response_model=TrainingRequestSchema, status_code=status.HTTP_201_CREATED)
def submit_training_request(
    request_data: TrainingRequestCreate, # FastAPI will use the alias "metadata" from schema for input
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user)
):
    # request_data.metadata_json will be a dict here
    # The number of batches should be implicitly or explicitly defined in metadata
    # For example, metadata_json={"details": "...", "num_batches": 10}
    # The CRUD function will handle creating batch entries.

    # Example validation: Check if num_batches is present, otherwise use a default
    if "num_batches" not in request_data.metadata_json or not isinstance(request_data.metadata_json.get("num_batches"), int) or request_data.metadata_json.get("num_batches", 0) <=0:
        raise HTTPException(status_code=400, detail="Metadata must include a positive integer 'num_batches'.")

    created_request = crud_create_request(db=db, request_data=request_data, requester_id=current_user.id)
    return created_request

@router.get("/{request_id}/status", response_model=TrainingRequestSchema)
def get_request_status(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user) # Ensures only authenticated users can query
):
    # Optional: Check if current_user is the owner of the request or an admin
    db_request = crud_get_request(db=db, request_id=request_id) # Check ownership in CRUD or here
    if db_request is None:
        raise HTTPException(status_code=404, detail="Training request not found")

    # Basic ownership check (can be enhanced with roles/permissions)
    if db_request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this request's status")

    return db_request

# Example: List requests for the current user
@router.get("/", response_model=List[TrainingRequestSchema]) # Or TrainingRequestSimple
def list_my_requests(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user)
):
    from crud.request import get_training_requests_by_requester # Local import for clarity
    requests = get_training_requests_by_requester(db, requester_id=current_user.id, skip=skip, limit=limit)
    # If using TrainingRequestSimple, you'd need to transform:
    # return [TrainingRequestSimple(id=r.id, status=r.status, created_at=r.created_at, num_batches=len(r.batches)) for r in requests]
    return requests

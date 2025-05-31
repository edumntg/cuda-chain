from pydantic import BaseModel, Field, Json
from typing import List, Optional, Dict, Any
from datetime import datetime
from models.user import TrainingRequestStatus, RequestBatchStatus # Import enums from models

class RequestBatchBase(BaseModel):
    batch_number: int
    status: RequestBatchStatus = RequestBatchStatus.PENDING

class RequestBatchCreate(RequestBatchBase):
    pass # No extra fields needed for creation beyond what TrainingRequestCreate handles

class RequestBatch(RequestBatchBase):
    id: int
    request_id: int
    worker_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    started_processing_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class TrainingRequestBase(BaseModel):
    metadata_json: Dict[str, Any] = Field(..., alias="metadata") # Alias for user input

    class Config:
        allow_population_by_field_name = True


class TrainingRequestCreate(TrainingRequestBase):
    # Example: Define expected structure for metadata if desired, e.g.
    # num_batches: int = Field(..., gt=0) # Part of metadata_json, can be validated
    pass


class TrainingRequest(TrainingRequestBase):
    id: int
    requester_id: int
    status: TrainingRequestStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    batches: List[RequestBatch] = []

    class Config:
        orm_mode = True

class TrainingRequestSimple(BaseModel): # For lists where full detail isn't needed
    id: int
    status: TrainingRequestStatus
    created_at: datetime
    num_batches: int # Add a helper field

    class Config:
        orm_mode = True

from sqlalchemy.orm import Session
from sqlalchemy import func # For count

from models.user import TrainingRequest as TrainingRequestModel, RequestBatch as RequestBatchModel, RequestBatchStatus
from schemas.request import TrainingRequestCreate
import json # For loading metadata string if needed, though FastAPI handles dict

def create_training_request(db: Session, request_data: TrainingRequestCreate, requester_id: int):
    # Assuming metadata_json in request_data is already a dict due to Pydantic
    # If it could be a string: metadata_dict = json.loads(request_data.metadata_json_str)
    metadata_dict = request_data.metadata_json

    # Determine number of batches from metadata (e.g., a 'num_batches' field or len of a 'dataset_splits' list)
    # This is an example, adjust based on actual metadata structure
    num_batches = metadata_dict.get("num_batches", 1) # Default to 1 if not specified
    if not isinstance(num_batches, int) or num_batches <= 0:
        num_batches = 1 # Fallback

    db_request = TrainingRequestModel(
        requester_id=requester_id,
        metadata_json=metadata_dict, # Store the whole metadata
        # status will default to PENDING
    )
    db.add(db_request)
    db.flush() # Flush to get the db_request.id for batches

    for i in range(num_batches):
        db_batch = RequestBatchModel(
            request_id=db_request.id,
            batch_number=i + 1, # Batches are 1-indexed
            status=RequestBatchStatus.PENDING
        )
        db.add(db_batch)

    db.commit()
    db.refresh(db_request)
    return db_request

def get_training_request_by_id(db: Session, request_id: int, requester_id: Optional[int] = None):
    query = db.query(TrainingRequestModel).filter(TrainingRequestModel.id == request_id)
    if requester_id: # If checking ownership
        query = query.filter(TrainingRequestModel.requester_id == requester_id)
    return query.first()

def get_training_requests_by_requester(db: Session, requester_id: int, skip: int = 0, limit: int = 100):
    return db.query(TrainingRequestModel).filter(TrainingRequestModel.requester_id == requester_id).offset(skip).limit(limit).all()

def get_available_training_requests(db: Session, skip: int = 0, limit: int = 100):
    # A request is available if it has at least one batch in 'pending' status
    # and the overall request is not 'COMPLETED' or 'FAILED'.
    # This might need refinement based on desired behavior for partially completed requests.
    return db.query(TrainingRequestModel).filter(
        TrainingRequestModel.batches.any(RequestBatchModel.status == RequestBatchStatus.PENDING)
    ).offset(skip).limit(limit).all()

def get_batch_by_id(db: Session, batch_id: int):
    return db.query(RequestBatchModel).filter(RequestBatchModel.id == batch_id).first()

def assign_batch_to_worker(db: Session, batch: RequestBatchModel, worker_id: int):
    batch.worker_id = worker_id
    batch.status = RequestBatchStatus.ASSIGNED # Or IN_PROGRESS if worker confirms start
    batch.assigned_at = func.now()
    db.commit()
    db.refresh(batch)
    return batch

def update_batch_status(db: Session, batch: RequestBatchModel, new_status: RequestBatchStatus):
    batch.status = new_status
    if new_status == RequestBatchStatus.COMPLETED or new_status == RequestBatchStatus.FAILED:
        batch.completed_at = func.now()
    elif new_status == RequestBatchStatus.PENDING: # Re-queueing
        batch.worker_id = None
        batch.assigned_at = None
        batch.started_processing_at = None
        batch.completed_at = None

    db.commit()
    db.refresh(batch)
    # Here you might also update the parent TrainingRequest's overall status
    # For example, if all batches are COMPLETED, set TrainingRequest to COMPLETED.
    # This logic can be complex and might be better handled by a background task or service function.
    return batch

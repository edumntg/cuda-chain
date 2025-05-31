from .user import User, TrainingRequest, RequestBatch, TrainingRequestStatus, RequestBatchStatus
from database import Base, engine # For convenience

def create_all_tables():
    Base.metadata.create_all(bind=engine)

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func # for server_default=func.now()
import enum

from database import Base # Corrected import path

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    requests = relationship("TrainingRequest", back_populates="requester")
    assigned_batches = relationship("RequestBatch", back_populates="worker")

class TrainingRequestStatus(str, enum.Enum):
    PENDING = "pending" # Request made, no batches assigned or all batches are pending
    PARTIALLY_ASSIGNED = "partially_assigned" # Some batches assigned, some pending
    FULLY_ASSIGNED = "fully_assigned" # All batches assigned, none pending
    IN_PROGRESS = "in_progress" # At least one batch is 'in_progress' or 'assigned'
    PARTIALLY_COMPLETED = "partially_completed" # Some batches completed, others pending/assigned/in_progress
    COMPLETED = "completed" # All batches completed successfully
    FAILED = "failed" # All batches have failed or request terminated

class TrainingRequest(Base):
    __tablename__ = "training_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Store the original metadata JSON as submitted by the user
    metadata_json = Column(JSON, nullable=False)
    # Overall status of the entire request
    status = Column(SAEnum(TrainingRequestStatus), default=TrainingRequestStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    requester = relationship("User", back_populates="requests")
    batches = relationship("RequestBatch", back_populates="request", cascade="all, delete-orphan")

class RequestBatchStatus(str, enum.Enum):
    PENDING = "pending"       # Available for a worker to take
    ASSIGNED = "assigned"     # Assigned to a worker, not yet started processing (or worker picked it up but not confirmed start of training)
    IN_PROGRESS = "in_progress" # Worker is actively processing this batch
    COMPLETED = "completed"   # Worker finished successfully
    FAILED = "failed"         # Worker failed to process

class RequestBatch(Base):
    __tablename__ = "request_batches"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("training_requests.id"), nullable=False)
    batch_number = Column(Integer, nullable=False) # e.g., 1, 2, 3... for a given request

    worker_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True) # Which worker is handling it

    status = Column(SAEnum(RequestBatchStatus), default=RequestBatchStatus.PENDING, nullable=False)

    # Could also store specific slice/details of data for this batch if metadata_json doesn't cover it well
    # batch_data_info = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # When a worker was assigned this batch
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    # When a worker actually started processing (e.g. downloading data)
    started_processing_at = Column(DateTime(timezone=True), nullable=True)
    # When processing was completed or failed
    completed_at = Column(DateTime(timezone=True), nullable=True)

    request = relationship("TrainingRequest", back_populates="batches")
    worker = relationship("User", back_populates="assigned_batches")

    __table_args__ = (
        ForeignKeyConstraint(['worker_id'], ['users.id']),
    )

# It's good practice to have a single place to create all tables
def create_db_and_tables():
    Base.metadata.create_all(bind=engine)

# If you run this script directly, it will create the tables.
if __name__ == "__main__":
    create_db_and_tables()
    print("Database tables created (if they didn't exist).")

import uuid
from datetime import datetime, timezone

class Job:
    def __init__(self, kernel_file_path, submitter_node_id, job_id=None,
                 input_file_path=None, grid_dim=(1,1,1), block_dim=(1,1,1),
                 status="pending", assigned_node_id=None, kernel_code=None,
                 assigned_timestamp=None, start_timestamp=None, end_timestamp=None,
                 result_data=None): # Added result_data
        self.job_id = job_id if job_id else str(uuid.uuid4())
        self.kernel_file_path = kernel_file_path
        self.input_file_path = input_file_path
        self.grid_dim = grid_dim
        self.block_dim = block_dim
        self.status = status
        self.submitter_node_id = submitter_node_id
        self.assigned_node_id = assigned_node_id
        self.kernel_code = kernel_code
        self.assigned_timestamp = assigned_timestamp
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.result_data = result_data # Initialize result_data

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "kernel_file_path": self.kernel_file_path,
            "input_file_path": self.input_file_path,
            "grid_dim": list(self.grid_dim),
            "block_dim": list(self.block_dim),
            "status": self.status,
            "submitter_node_id": self.submitter_node_id,
            "assigned_node_id": self.assigned_node_id,
            "kernel_code": self.kernel_code,
            "assigned_timestamp": self.assigned_timestamp.isoformat() if self.assigned_timestamp else None,
            "start_timestamp": self.start_timestamp.isoformat() if self.start_timestamp else None,
            "end_timestamp": self.end_timestamp.isoformat() if self.end_timestamp else None,
            "result_data": self.result_data, # Include result_data
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            job_id=data.get("job_id"),
            kernel_file_path=data.get("kernel_file_path"),
            input_file_path=data.get("input_file_path"),
            grid_dim=tuple(data.get("grid_dim", [1,1,1])),
            block_dim=tuple(data.get("block_dim", [1,1,1])),
            status=data.get("status", "pending"),
            submitter_node_id=data.get("submitter_node_id"),
            assigned_node_id=data.get("assigned_node_id"),
            kernel_code=data.get("kernel_code"),
            assigned_timestamp=datetime.fromisoformat(data["assigned_timestamp"]) if data.get("assigned_timestamp") else None,
            start_timestamp=datetime.fromisoformat(data["start_timestamp"]) if data.get("start_timestamp") else None,
            end_timestamp=datetime.fromisoformat(data["end_timestamp"]) if data.get("end_timestamp") else None,
            result_data=data.get("result_data"), # Include result_data
        )

    def __repr__(self):
        return (f"<Job {self.job_id} ({self.status}) Kernel: {self.kernel_file_path} "
                f"Submitted by: {self.submitter_node_id[:8]} Assigned to: {self.assigned_node_id[:8] if self.assigned_node_id else 'None'}>")

def parse_dim_str(dim_str, default_dim=(1,1,1)):
    if not dim_str:
        return default_dim
    try:
        parts = [int(p.strip()) for p in dim_str.split(',')]
        if not (1 <= len(parts) <= 3):
            raise ValueError("Dimension string must have 1 to 3 parts.")

        if len(parts) == 1:
            return (parts[0], 1, 1)
        elif len(parts) == 2:
            return (parts[0], parts[1], 1)
        else: # len(parts) == 3
            return tuple(parts)
    except ValueError as e:
        raise ValueError(f"Invalid dimension string '{dim_str}'. Expected comma-separated integers e.g., 'x,y,z'. Original error: {e}")

import uuid

class Node:
    def __init__(self, node_id, ip_address, port, status="active", resources=None):
        self.node_id = node_id if node_id else str(uuid.uuid4())
        self.ip_address = ip_address
        self.port = port
        self.status = status
        self.resources = resources if resources else {} # e.g., {'cuda_cores': 2560, 'memory_gb': 8}

    def to_dict(self):
        return {
            "node_id": self.node_id,
            "ip_address": self.ip_address,
            "port": self.port,
            "status": self.status,
            "resources": self.resources,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            node_id=data.get("node_id"),
            ip_address=data.get("ip_address"),
            port=data.get("port"),
            status=data.get("status", "active"),
            resources=data.get("resources"),
        )

    def __repr__(self):
        return f"<Node {self.node_id} ({self.ip_address}:{self.port})>"

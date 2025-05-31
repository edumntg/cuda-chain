import asyncio
import json
import uuid
from datetime import datetime, timezone
from .node import Node
from .job import Job, parse_dim_str

class NetworkManager:
    def __init__(self, self_node_ip="127.0.0.1", self_node_port=8000, node_id=None):
        self.node_id = node_id if node_id else str(uuid.uuid4())
        self.self_node = Node(
            node_id=self.node_id,
            ip_address=self_node_ip,
            port=self_node_port,
            resources={"cuda_cores": 0, "memory_gb": 0}
        )
        self.peers = {}
        self.server_instance = None
        self.pending_jobs = []
        self.active_jobs = {}
        self.completed_jobs = {}
        self.bootstrap_node_addr = None
        self.job_processor_task = None
        self.shutting_down = False # Added for graceful shutdown

    async def handle_connection(self, reader, writer):
        data = None
        addr = writer.get_extra_info('peername')
        try:
            data = await reader.read(4096)
            if not data: return

            message_json = data.decode()
            message = json.loads(message_json)
            if message.get("type") not in ["PING", "PONG"]:
                 print(f"Received {message!r} from {addr}")

            msg_type = message.get("type")
            sender_node_id = message.get("sender_node_id")
            response = None

            if msg_type == "PING":
                response = {"type": "PONG", "sender_node_id": self.self_node.node_id}
            elif msg_type == "ANNOUNCE":
                node_info = message.get("node_info")
                if node_info: self.add_peer(node_info)
                response = {"type": "PONG", "sender_node_id": self.self_node.node_id, "message": "ANNOUNCE received"}
            elif msg_type == "GET_PEERS":
                peers_info = [peer.to_dict() for peer in self.get_all_peers()]
                response = {"type": "PEERS_LIST", "sender_node_id": self.self_node.node_id, "peers": peers_info}
            elif msg_type == "PEERS_LIST":
                for peer_data in message.get("peers", []): self.add_peer(peer_data)
            elif msg_type == "PONG":
                pass
            elif msg_type == "SUBMIT_JOB":
                job_data = message.get('job_data')
                if job_data:
                    job = Job.from_dict(job_data)
                    job.submitter_node_id = sender_node_id
                    self.pending_jobs.append(job)
                    print(f"Received job {job.job_id} from {job.submitter_node_id}. Added to pending queue ({len(self.pending_jobs)} pending).")
                    response = {"type": "JOB_ACK", "job_id": job.job_id, "status": job.status, "receiver_node_id": self.self_node.node_id}
                else:
                    response = {"type": "ERROR", "message": "SUBMIT_JOB lacked job_data"}
            elif msg_type == "JOB_ACK":
                 print(f"Job {message.get('job_id')} ack by {message.get('receiver_node_id')} status: {message.get('status')}")
            elif msg_type == "JOB_STATUS_UPDATE":
                job_data = message.get('job_data')
                if job_data: self.handle_job_status_update_message(job_data)
            elif msg_type == "GET_NODE_STATUS": # New message type for node status
                response_data = self.self_node.to_dict()
                response_data['pending_jobs_count'] = len(self.pending_jobs)
                response_data['active_jobs_count'] = len(self.active_jobs)
                # response_data['completed_jobs_count'] = len(self.completed_jobs) # Optionally add
                response = {"type": "NODE_STATUS_RESPONSE", "status_data": response_data, "sender_node_id": self.self_node.node_id}
                print(f"Sending NODE_STATUS_RESPONSE to {sender_node_id[:8] if sender_node_id else 'unknown'}")
            elif msg_type == "REQUEST_JOB_RESULT":
                requested_job_id = message.get('job_id')
                job = self.completed_jobs.get(requested_job_id)
                if job and job.result_data:
                    response = {"type": "JOB_RESULT_RESPONSE", "job_id": job.job_id,
                                "result_data": job.result_data, "sender_node_id": self.self_node.node_id}
                    print(f"Sending result for job {job.job_id} to {sender_node_id[:8]}")
                else:
                    response = {"type": "ERROR", "message": "Job result not found or job not completed by this node",
                                "job_id": requested_job_id, "sender_node_id": self.self_node.node_id}
                    print(f"Result not found for job {requested_job_id} requested by {sender_node_id[:8] if sender_node_id else 'unknown'}")
            elif msg_type == "REQUEST_JOB_CANCEL":
                job_id_to_cancel = message.get('job_id')
                cancelling_requester_id = message.get('sender_node_id') # The node asking for cancellation
                print(f"Received REQUEST_JOB_CANCEL for job {job_id_to_cancel} from {cancelling_requester_id[:8] if cancelling_requester_id else 'unknown'}")

                ack_status = "not_found"
                cancelled_job = None

                # Check pending jobs
                pending_job_idx = -1
                for i, job_obj in enumerate(self.pending_jobs):
                    if job_obj.job_id == job_id_to_cancel:
                        pending_job_idx = i
                        break

                if pending_job_idx != -1:
                    cancelled_job = self.pending_jobs.pop(pending_job_idx)
                    cancelled_job.status = "cancelled"
                    cancelled_job.end_timestamp = datetime.now(timezone.utc) # Mark end time
                    self.completed_jobs[cancelled_job.job_id] = cancelled_job
                    ack_status = "cancelled_pending"
                    print(f"Cancelled job {job_id_to_cancel} from pending queue.")
                    # If the job was submitted by someone else, inform them.
                    if cancelled_job.submitter_node_id != self.self_node.node_id:
                        # This node was holding it; original submitter needs to know.
                        await self.send_job_status_update(cancelled_job)
                else:
                    # Check active jobs (only if this node is assigned)
                    if job_id_to_cancel in self.active_jobs:
                        active_job = self.active_jobs[job_id_to_cancel]
                        if active_job.assigned_node_id == self.self_node.node_id:
                            # For simulation: directly move to cancelled.
                            # In a real system, this would signal the execution task.
                            cancelled_job = self.active_jobs.pop(job_id_to_cancel)
                            cancelled_job.status = "cancelled"
                            cancelled_job.end_timestamp = datetime.now(timezone.utc)
                            self.completed_jobs[cancelled_job.job_id] = cancelled_job
                            ack_status = "cancelled_active"
                            print(f"Cancelled job {job_id_to_cancel} from active jobs (simulated).")
                            # Inform the original submitter
                            await self.send_job_status_update(cancelled_job)
                        else:
                            # Job is active but assigned to another node (should not happen if logic is correct)
                            ack_status = "error_not_assigned_here"
                            print(f"Job {job_id_to_cancel} is active but not assigned to this node. Cannot cancel directly.")
                    elif job_id_to_cancel in self.completed_jobs and self.completed_jobs[job_id_to_cancel].status not in ["completed", "failed", "cancelled"]:
                        # If it was somehow completed but not with a terminal status (unlikely with current logic)
                        cj = self.completed_jobs[job_id_to_cancel]
                        cj.status = "cancelled"
                        cj.end_timestamp = datetime.now(timezone.utc)
                        ack_status = "cancelled_completed" # was already completed, now marked cancelled.
                        if cj.submitter_node_id != self.self_node.node_id:
                           await self.send_job_status_update(cj)


                response = {"type": "JOB_CANCEL_ACK", "job_id": job_id_to_cancel,
                            "status": ack_status, "cancelling_node_id": self.self_node.node_id}

            elif msg_type == "NODE_LEAVING":
                leaving_node_id = message.get('sender_node_id')
                if leaving_node_id:
                    print(f"Node {leaving_node_id[:8]} announced departure. Removing from peers.")
                    self.remove_peer(leaving_node_id)
                # No response needed for NODE_LEAVING
            else:
                print(f"Unknown message type: {msg_type} from {addr}")

            if response:
                writer.write(json.dumps(response).encode())
                await writer.drain()

        except json.JSONDecodeError: print(f"Error decoding JSON from {addr}")
        except ConnectionResetError: print(f"Connection reset by {addr}")
        except Exception as e: print(f"Error handling connection from {addr}: {e!r}")
        finally:
            if writer and not writer.is_closing(): writer.close(); await writer.wait_closed()

    async def start_server(self):
        try:
            server = await asyncio.start_server(self.handle_connection, self.self_node.ip_address, self.self_node.port)
            self.server_instance = server; addr = server.sockets[0].getsockname()
            print(f'Node {self.self_node.node_id} serving on {addr}')
            if not self.job_processor_task or self.job_processor_task.done():
                self.job_processor_task = asyncio.create_task(self.process_pending_jobs())
            async with server: await server.serve_forever()
        except OSError as e: raise
        finally:
            if self.job_processor_task and not self.job_processor_task.done():
                self.job_processor_task.cancel()
                try: await self.job_processor_task
                except asyncio.CancelledError: print("Job processor task cancelled.")

    async def send_message(self, target_ip, target_port, message_dict):
        message_dict["sender_node_id"] = self.self_node.node_id
        reader, writer = None, None
        try:
            reader, writer = await asyncio.open_connection(target_ip, target_port)

            if message_dict["type"] == "NODE_LEAVING":
                # Fire and forget for NODE_LEAVING
                writer.write(json.dumps(message_dict).encode())
                await writer.drain()
                # print(f"Sent {message_dict['type']} to {target_ip}:{target_port}") # Can be noisy
                return {"status": "sent_no_reply_expected"}
            else: # Default for messages expecting reply
                writer.write(json.dumps(message_dict).encode()); await writer.drain()
                # print(f"Sent {message_dict['type']} to {target_ip}:{target_port}") # Can be noisy

            # Expect reply for these types
            if message_dict["type"] in ["PING", "GET_PEERS", "SUBMIT_JOB", "REQUEST_JOB_RESULT", "GET_NODE_STATUS", "REQUEST_JOB_CANCEL"]:
                data = await asyncio.wait_for(reader.read(4096), timeout=10.0)
                response_json = data.decode() # Potential ReadAfterClose if connection drops immediately
                if response_json:
                    response = json.loads(response_json)
                    if response.get("type") == "PEERS_LIST":
                        for peer_data in response.get("peers", []): self.add_peer(peer_data)
                    elif response.get("type") == "JOB_ACK":
                        print(f"Job {response.get('job_id')} ack by node {response.get('receiver_node_id')[:8]}.")
                    # JOB_RESULT_RESPONSE and NODE_STATUS_RESPONSE are handled by their respective callers
                    return response
                return None
            return {"status": "sent_no_reply_expected"} # e.g. ANNOUNCE, JOB_STATUS_UPDATE

        except ConnectionRefusedError:
            print(f"Conn refused by {target_ip}:{target_port} for {message_dict['type']}")
            # Simplified peer removal for brevity
            # peer_to_remove = next((pid for pid,p in self.peers.items() if p.ip_address==target_ip and p.port==target_port), None)
            # if peer_to_remove: self.remove_peer(peer_to_remove)
        except asyncio.TimeoutError: print(f"Timeout for {message_dict['type']} to {target_ip}:{target_port}")
        except Exception as e: print(f"Error sending {message_dict['type']} to {target_ip}:{target_port}: {e!r}")
        finally:
            if writer and not writer.is_closing(): writer.close(); await writer.wait_closed()
        return None

    async def connect_to_bootstrap(self, bootstrap_ip, bootstrap_port): # Unchanged
        self.bootstrap_node_addr = (bootstrap_ip, bootstrap_port)
        print(f"Connecting to bootstrap node {bootstrap_ip}:{bootstrap_port}...")
        await self.send_message(bootstrap_ip, bootstrap_port, {"type": "ANNOUNCE", "node_info": self.self_node.to_dict()})
        await self.send_message(bootstrap_ip, bootstrap_port, {"type": "GET_PEERS"})
        print(f"Bootstrap process with {bootstrap_ip}:{bootstrap_port} completed.")

    def add_peer(self, node_info_dict): # Unchanged
        node = Node.from_dict(node_info_dict)
        if node.node_id == self.self_node.node_id or node.node_id in self.peers: return False
        self.peers[node.node_id] = node; print(f"Added peer: {node!r}"); return True

    def remove_peer(self, node_id): # Unchanged
        if node_id in self.peers: print(f"Removed peer: {self.peers.pop(node_id)!r}"); return True
        return False

    def get_peer(self, node_id): return self.peers.get(node_id) # Unchanged
    def get_all_peers(self): return list(self.peers.values()) # Unchanged
    def get_self_node_info(self): return self.self_node.to_dict() # Unchanged

    async def submit_new_job(self, kfp, ifp, gds, bds, tnas=None): # Minor changes for brevity
        try: grid_dim = parse_dim_str(gds); block_dim = parse_dim_str(bds)
        except ValueError as e: print(f"Dim parse error: {e}"); return None
        job = Job(kfp,self.self_node.node_id,input_file_path=ifp,grid_dim=grid_dim,block_dim=block_dim)

        # If this node is also a worker, it might pick its own job from pending_jobs.
        # If it's purely a submitter, it might need a separate list like "my_submitted_jobs_pending_ack"
        # For now, adding to pending_jobs relies on the processing loop to not pick up jobs submitted by self
        # unless it's also acting as a worker. This aspect might need refinement.
        # A simple way for a worker to ignore its own submitted jobs in process_pending_jobs:
        # if job.submitter_node_id == self.self_node.node_id: continue (or put it back)
        # However, the current setup has the submitter also store it, and process_pending_jobs picks it up.
        # For now, let's assume if a node submits a job, it can also process it if it's a worker.
        print(f"Job {job.job_id} created by {self.self_node.node_id[:8]}.")
        # Add to a local list so the submitter can track its status via JOB_STATUS_UPDATE messages
        # This is crucial for the submitter to know about its own jobs.
        # Let's use pending_jobs for this node's own submitted jobs until they are ack'd or processed.
        # If this node is ONLY a submitter, it will stay in pending_jobs until updates arrive.
        # If this node is a WORKER, it will also process from pending_jobs.
        # This logic is simplified; a more robust system might have separate lists for "jobs_i_submitted"
        # vs "jobs_i_need_to_process".
        # This logic for adding self-submitted jobs to pending_jobs is delicate.
        # If the node is purely a submitter, it needs to track its jobs.
        # If it's also a worker, process_pending_jobs will pick it up.
        # The current handle_job_status_update_message tries to update jobs in pending/active/completed
        # if this node is the submitter.
        if job.submitter_node_id == self.self_node.node_id:
            # Ensure the job is tracked if this node submitted it.
            # Add to pending if not already there by another mechanism.
            # The process_pending_jobs loop should ideally not process jobs submitted by self
            # unless the node is explicitly configured as a worker for its own jobs.
            # For now, this simplified logic assumes the job is added to pending for tracking.
            is_tracked = any(j.job_id == job.job_id for j in self.pending_jobs) or \
                         job.job_id in self.active_jobs or \
                         job.job_id in self.completed_jobs
            if not is_tracked:
                 self.pending_jobs.append(job)
                 print(f"Job {job.job_id} submitted by self, added to local pending_jobs for tracking.")


        msg = {"type": "SUBMIT_JOB", "job_data": job.to_dict()}
        # Target selection logic (simplified for brevity, same as before)
        tip, tp = None, None
        if tnas: tip, tp = tnas.split(':'); tp = int(tp)
        elif self.peers: p=list(self.peers.values())[0]; tip,tp=p.ip_address,p.port
        elif self.bootstrap_node_addr: tip,tp = self.bootstrap_node_addr
        else: print("No target for job submission."); return None
        return await self.send_message(tip,tp,msg)

    async def process_pending_jobs(self):
        while True:
            if self.shutting_down:
                print("Job processor shutting down.")
                break
            try:
                job = None
                if self.pending_jobs:
                    # Simple FIFO, assuming this node is a worker for any job in its queue.
                    # Refinement: could check job.assigned_node_id if pre-assignment occurs.
                    job = self.pending_jobs.pop(0)

                if job:
                    if job.status == "cancelling": # Job was marked for cancellation while in queue or by submitter
                        print(f"Job {job.job_id} was marked 'cancelling'. Moving to completed with status 'cancelled'.")
                        job.status = "cancelled"
                        job.end_timestamp = datetime.now(timezone.utc)
                        self.completed_jobs[job.job_id] = job
                        # If it was assigned to this node, and submitter is different, notify original submitter.
                        if job.assigned_node_id == self.self_node.node_id and job.submitter_node_id != self.self_node.node_id:
                           await self.send_job_status_update(job)
                        continue # Skip processing this job further
                    print(f"Processing job {job.job_id} from {job.submitter_node_id[:8]}.")
                    job.status = "assigning"; job.assigned_node_id = self.self_node.node_id
                    job.assigned_timestamp = datetime.now(timezone.utc)
                    self.active_jobs[job.job_id] = job
                    await self.send_job_status_update(job)

                    job.status = "running"; job.start_timestamp = datetime.now(timezone.utc)
                    await self.send_job_status_update(job)
                    print(f"Job {job.job_id} running. Simulating work...")
                    await asyncio.sleep(2) # Reduced sleep for faster testing

                    job.status = "completed"
                    job.end_timestamp = datetime.now(timezone.utc)
                    # **** Simulate result data ****
                    job.result_data = f"Simulated result for job {job.job_id} processed by node {self.self_node.node_id[:8]}"
                    # print(f"Job {job.job_id} completed. Result: {job.result_data}") # Covered by status update log
                    await self.send_job_status_update(job) # This update will include result_data and final status

                    # Remove from active, add to completed (even if status became 'failed' or 'cancelled' during processing)
                    if job.job_id in self.active_jobs: # Should always be true here
                        del self.active_jobs[job.job_id]
                    self.completed_jobs[job.job_id] = job
                await asyncio.sleep(1)
            except asyncio.CancelledError: print("Job processor cancelled."); break
            except Exception as e: print(f"Error in job processor: {e!r}"); await asyncio.sleep(5)

    async def send_job_status_update(self, job: Job):
        msg = {"type": "JOB_STATUS_UPDATE", "job_data": job.to_dict()}
        if job.submitter_node_id == self.self_node.node_id:
            self.handle_job_status_update_message(job.to_dict()) # Handle self-submitted job status locally
        else:
            peer = self.peers.get(job.submitter_node_id)
            if peer: await self.send_message(peer.ip_address, peer.port, msg)
            else: print(f"Submitter {job.submitter_node_id[:8]} for job {job.job_id} not a peer. Cannot send status.")

    def handle_job_status_update_message(self, job_data_dict): # Sync method
        updated_job = Job.from_dict(job_data_dict)
        jid = updated_job.job_id
        loc_job, loc_list_name = None, None

        # Check if this node is the submitter and is tracking the job
        if updated_job.submitter_node_id == self.self_node.node_id:
            if jid in self.active_jobs : loc_job,loc_list_name = self.active_jobs[jid],"active"
            elif jid in self.completed_jobs: loc_job,loc_list_name = self.completed_jobs[jid],"completed"
            else: # Check pending_jobs list
                try:
                    idx = [j.job_id for j in self.pending_jobs].index(jid)
                    loc_job, loc_list_name = self.pending_jobs[idx], "pending"
                except ValueError: pass

            if loc_job:
                print(f"Updating my submitted job {jid} (in {loc_list_name}): Status '{updated_job.status}', Result: {'set' if updated_job.result_data else 'not set'}")
                loc_job.status = updated_job.status
                loc_job.assigned_node_id = updated_job.assigned_node_id
                loc_job.assigned_timestamp = updated_job.assigned_timestamp
                loc_job.start_timestamp = updated_job.start_timestamp
                loc_job.end_timestamp = updated_job.end_timestamp
                loc_job.result_data = updated_job.result_data # Update result data

                if updated_job.status in ["completed", "failed"] and loc_list_name == "active_jobs":
                    self.completed_jobs[jid] = self.active_jobs.pop(jid)
                    print(f"Moved self-submitted job {jid} from active to completed.")
                elif updated_job.status in ["assigning", "running"] and loc_list_name == "pending":
                     # If I submitted it, and it's now being processed by someone else (or me)
                     self.active_jobs[jid] = self.pending_jobs.pop(idx)
                     print(f"Moved self-submitted job {jid} from pending to active.")
            else:
                # If this node submitted it, but doesn't have it. Could be a new job from elsewhere.
                # Or if it's an update for a job this node is processing for someone else (already handled by process_pending_jobs)
                 print(f"Received status for job {jid} I submitted, but not in my local tracking lists. Storing in completed.")
                 self.completed_jobs[jid] = updated_job # Store it as completed to have the record
        else:
            # This is a status update for a job this node *didn't* submit.
            # This means this node is the *assignee* (worker) and is receiving an update about a job it's managing.
            # The primary recipient of JOB_STATUS_UPDATE is the original submitter.
            # The assignee updates its state in `process_pending_jobs`.
            # If the job was cancelled by the submitter, this node (assignee) might receive a JOB_STATUS_UPDATE
            # with status="cancelled". `process_pending_jobs` should ideally check `job.status` before intensive work.
            # For now, this log indicates the message was received, but no specific action on lists here.
            print(f"Received status update for job {jid} (not submitted by me). Current local status for this job (if any): {self.active_jobs.get(jid, self.completed_jobs.get(jid))!r}")


    async def announce_departure_and_shutdown(self):
        print("Announcing departure and initiating shutdown...")
        self.shutting_down = True # Signal other async tasks like job_processor

        leaving_msg = {"type": "NODE_LEAVING"}
        # Create a list of tasks for all send_message calls
        departure_tasks = []
        # Notify peers
        for peer_node in list(self.peers.values()): # Iterate over a copy
            print(f"Notifying peer {peer_node.node_id[:8]} of departure.")
            departure_tasks.append(self.send_message(peer_node.ip_address, peer_node.port, leaving_msg))

        # Notify bootstrap node if it's known and not already in peers (or if it's a central registry)
        if self.bootstrap_node_addr:
            is_bootstrap_peer = any(p.ip_address == self.bootstrap_node_addr[0] and p.port == self.bootstrap_node_addr[1] for p in self.peers.values())
            if not is_bootstrap_peer:
                print(f"Notifying bootstrap node {self.bootstrap_node_addr[0]}:{self.bootstrap_node_addr[1]} of departure.")
                departure_tasks.append(self.send_message(self.bootstrap_node_addr[0], self.bootstrap_node_addr[1], leaving_msg))

        # Wait for all departure messages to be sent (fire and forget, but wait for socket ops)
        if departure_tasks:
            await asyncio.gather(*departure_tasks, return_exceptions=True) # Allow errors for unreachable nodes

        # Cancel job processor task
        if self.job_processor_task and not self.job_processor_task.done():
            print("Cancelling job processor task...")
            self.job_processor_task.cancel()
            try:
                await self.job_processor_task
            except asyncio.CancelledError:
                print("Job processor task successfully cancelled.")
            except Exception as e:
                print(f"Error during job processor task cancellation: {e!r}")

        # Close the server
        if self.server_instance:
            print("Closing server...")
            self.server_instance.close()
            try:
                await asyncio.wait_for(self.server_instance.wait_closed(), timeout=5.0)
                print("Server closed.")
            except asyncio.TimeoutError:
                print("Timeout waiting for server to close.")
            except Exception as e:
                print(f"Error closing server: {e!r}")
            self.server_instance = None # Mark as closed

        print("Node has completed network shutdown procedures.")

    async def request_job_cancellation(self, job_id_to_cancel: str):
        # Check local lists first
        job_ref, list_name = None, None

        # Check pending jobs
        pending_idx = -1
        for i, pj in enumerate(self.pending_jobs):
            if pj.job_id == job_id_to_cancel:
                pending_idx = i; job_ref = pj; list_name = "pending"; break

        if pending_idx != -1: # Found in pending
            if job_ref.submitter_node_id == self.self_node.node_id or job_ref.assigned_node_id == self.self_node.node_id or not job_ref.assigned_node_id :
                # If I submitted it and it's pending my processing, or assigned to me and pending.
                # Or if it's pending and not yet assigned to anyone (e.g. I am just holding it).
                job_to_cancel = self.pending_jobs.pop(pending_idx)
                job_to_cancel.status = "cancelled"
                job_to_cancel.end_timestamp = datetime.now(timezone.utc)
                self.completed_jobs[job_to_cancel.job_id] = job_to_cancel
                print(f"Job {job_id_to_cancel} cancelled locally from pending queue.")
                if job_to_cancel.submitter_node_id != self.self_node.node_id and job_to_cancel.assigned_node_id == self.self_node.node_id:
                    # I was assigned it, but it was pending, now cancelled. Notify submitter.
                    await self.send_job_status_update(job_to_cancel)
                elif job_to_cancel.submitter_node_id == self.self_node.node_id and job_to_cancel.assigned_node_id and job_to_cancel.assigned_node_id != self.self_node.node_id:
                    # I submitted it, it was assigned elsewhere, but I was still treating it as pending locally (e.g. waiting for active status)
                    # This is complex. The primary cancellation should go to the assigned node.
                    # This path indicates a potential state mismatch or that it's okay to cancel before it went active on remote.
                    # For now, assume if it's in my pending, I can try to stop it before it's processed.
                    pass # Handled by forwarding logic below if assigned_node_id is set.

                return {"type": "JOB_CANCEL_ACK", "job_id": job_id_to_cancel, "status": "cancelled_locally_pending", "node_id": self.self_node.node_id}

        # Check active jobs (only if this node is the one executing it)
        if job_id_to_cancel in self.active_jobs:
            job_ref = self.active_jobs[job_id_to_cancel]
            if job_ref.assigned_node_id == self.self_node.node_id:
                print(f"Attempting to cancel locally active job {job_id_to_cancel} (simulated).")
                # Simulate cancellation: move to completed_jobs with status "cancelled"
                cancelled_job = self.active_jobs.pop(job_id_to_cancel)
                cancelled_job.status = "cancelled" # Or "cancelling" then "cancelled"
                cancelled_job.end_timestamp = datetime.now(timezone.utc)
                self.completed_jobs[cancelled_job.job_id] = cancelled_job
                # Notify the original submitter that it's now cancelled
                if cancelled_job.submitter_node_id != self.self_node.node_id:
                    await self.send_job_status_update(cancelled_job)
                else: # If I was processing my own job
                    self.handle_job_status_update_message(cancelled_job.to_dict()) # Update my own view
                return {"type": "JOB_CANCEL_ACK", "job_id": job_id_to_cancel, "status": "cancelled_locally_active", "node_id": self.self_node.node_id}
            else: # Active but assigned elsewhere (this node is likely submitter)
                list_name = "active" # Fall through to forwarding logic

        # If job was submitted by this node and is running on another node
        if not job_ref: # If not found in pending or active (locally assigned)
            if job_id_to_cancel in self.completed_jobs : job_ref = self.completed_jobs[job_id_to_cancel]; list_name = "completed"
            # also check pending again if it's a job submitted by me but not processed by me
            if not job_ref:
                 for pj in self.pending_jobs:
                     if pj.job_id == job_id_to_cancel and pj.submitter_node_id == self.self_node.node_id:
                         job_ref = pj; list_name = "pending_submitted_by_me"; break


        if job_ref and job_ref.submitter_node_id == self.self_node.node_id and \
           job_ref.assigned_node_id and job_ref.assigned_node_id != self.self_node.node_id and \
           job_ref.status not in ["completed", "failed", "cancelled"]:

            assigned_node_info = self.peers.get(job_ref.assigned_node_id)
            if assigned_node_info:
                print(f"Job {job_id_to_cancel} was submitted by this node and is assigned to {job_ref.assigned_node_id[:8]}. Forwarding cancellation request.")
                cancel_req_msg = {"type": "REQUEST_JOB_CANCEL", "job_id": job_id_to_cancel}
                # The response from send_message will be the JOB_CANCEL_ACK from the remote node
                ack = await self.send_message(assigned_node_info.ip_address, assigned_node_info.port, cancel_req_msg)
                if ack and ack.get("type") == "JOB_CANCEL_ACK":
                    # Update local job status based on remote ack
                    if ack.get("status") in ["cancelled_pending", "cancelled_active", "cancelled_completed"]:
                         job_ref.status = "cancelled"
                         job_ref.end_timestamp = datetime.now(timezone.utc) # approx
                         if list_name == "active_jobs": self.completed_jobs[job_id_to_cancel] = self.active_jobs.pop(job_id_to_cancel)
                         elif list_name == "pending_submitted_by_me": self.completed_jobs[job_id_to_cancel] = job_ref # if it was just in pending
                         # else it might be already in completed_jobs but being re-cancelled
                return ack
            else:
                print(f"Assigned node {job_ref.assigned_node_id[:8]} for job {job_id_to_cancel} is not a current peer. Cannot forward cancellation.")
                return {"type": "JOB_CANCEL_ACK", "job_id": job_id_to_cancel, "status": "error_forwarding_peer_not_found", "node_id": self.self_node.node_id}

        # If job already completed or cancelled locally
        if job_ref and job_ref.status in ["completed", "failed", "cancelled"]:
            return {"type": "JOB_CANCEL_ACK", "job_id": job_id_to_cancel, "status": f"already_{job_ref.status}", "node_id": self.self_node.node_id}

        print(f"Job {job_id_to_cancel} not found, already terminal, or cannot be cancelled by this node under current conditions. Local ref: {job_ref!r}")
        return {"type": "JOB_CANCEL_ACK", "job_id": job_id_to_cancel, "status": "not_actionable", "node_id": self.self_node.node_id}


    async def request_remote_node_status(self, target_node_id_or_addr: str):
        target_ip, target_port = None, None
        if ':' in target_node_id_or_addr: # Treat as ip:port
            try:
                target_ip, port_str = target_node_id_or_addr.split(':')
                target_port = int(port_str)
            except ValueError:
                print(f"Invalid address format: {target_node_id_or_addr}. Use ip:port or a valid node ID.")
                return None
        else: # Treat as node_id
            peer = self.peers.get(target_node_id_or_addr)
            if peer:
                target_ip, target_port = peer.ip_address, peer.port
            else:
                # Could also check if it's self.self_node.node_id, but CLI handles local status separately.
                print(f"Node ID {target_node_id_or_addr} not found in known peers.")
                return None

        if target_ip and target_port:
            message = {"type": "GET_NODE_STATUS"}
            print(f"Requesting node status from {target_ip}:{target_port} (target: {target_node_id_or_addr})")
            response = await self.send_message(target_ip, target_port, message)
            if response and response.get("type") == "NODE_STATUS_RESPONSE":
                return response.get("status_data")
            else:
                print(f"Failed to get status from {target_node_id_or_addr}. Response: {response!r}")
                return None
        else: # Should be caught by earlier checks
            print(f"Could not determine target for status request: {target_node_id_or_addr}")
            return None

    async def request_job_result(self, job_id_to_request):
        job_obj, source_list = None, None
        # Find job locally to determine who was assigned (or if it's self-processed)
        if job_id_to_request in self.completed_jobs:
            job_obj = self.completed_jobs[job_id_to_request]; source_list = "completed"
        elif job_id_to_request in self.active_jobs:
            job_obj = self.active_jobs[job_id_to_request]; source_list = "active"
        else:
            for job in self.pending_jobs: # Search list
                if job.job_id == job_id_to_request: job_obj = job; source_list = "pending"; break

        if not job_obj:
            print(f"Job {job_id_to_request} not found locally. Cannot determine assigned node to request result from."); return None

        print(f"Requesting result for job {job_id_to_request}. Local status: {job_obj.status} (in {source_list}). Assigned to: {job_obj.assigned_node_id[:8] if job_obj.assigned_node_id else 'N/A'}")

        if job_obj.status != "completed":
            print(f"Job {job_id_to_request} is not yet completed (status: {job_obj.status}). Cannot fetch result."); return None

        if job_obj.assigned_node_id == self.self_node.node_id: # Processed by this node
            if job_obj.result_data:
                print(f"Retrieving result for job {job_id_to_request} locally."); return job_obj.result_data
            else:
                print(f"Job {job_id_to_request} was completed locally, but result_data is missing."); return None

        if job_obj.assigned_node_id: # Processed by another node
            assigned_peer_info = self.peers.get(job_obj.assigned_node_id)
            if not assigned_peer_info:
                print(f"Node {job_obj.assigned_node_id[:8]} (assigned to job {job_id_to_request}) is not a direct peer."); return None

            print(f"Requesting result for job {job_id_to_request} from assigned node {assigned_peer_info.node_id[:8]} at {assigned_peer_info.ip_address}:{assigned_peer_info.port}")
            message = {"type": "REQUEST_JOB_RESULT", "job_id": job_id_to_request}
            response = await self.send_message(assigned_peer_info.ip_address, assigned_peer_info.port, message)

            if response and response.get("type") == "JOB_RESULT_RESPONSE":
                print(f"Received result for job {job_id_to_request} from {assigned_peer_info.node_id[:8]}.")
                # Optionally, update local job_obj with this result_data if it wasn't already set by a status update
                if not job_obj.result_data: job_obj.result_data = response.get("result_data")
                return response.get("result_data")
            else:
                print(f"Failed to get result for job {job_id_to_request} from {assigned_peer_info.node_id[:8]}. Response: {response!r}"); return None
        else: # No assigned node ID
            print(f"Job {job_id_to_request} is marked completed but has no assigned_node_id. Cannot fetch result."); return None

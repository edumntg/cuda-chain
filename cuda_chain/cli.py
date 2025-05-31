import click
import asyncio
from .node import Node
from .network import NetworkManager
# from .job import parse_dim_str # Not strictly needed here if NetworkManager handles parsing for submit_new_job

# Global instance of NetworkManager
network_manager_instance = None

@click.group()
def main():
    """cuda-chain: A P2P network for distributed CUDA computing."""
    pass

@click.group(name='node')
def node_cli():
    """Manage network nodes."""
    pass
main.add_command(node_cli, name="node")


# Node CLI commands (start, list, ping - assuming they are mostly the same as provided in the prompt)
# ... start_node_sync, start_node_async, list_nodes, ping_node_sync, ping_node_async ...
# Make sure they are correctly defined as per the prompt if they were to be copy-pasted.
# For this diff, I will assume they exist and focus on the new/modified parts.

# New command for node_cli
@node_cli.command(name="list-pending")
def list_pending_jobs_cli():
    """Lists pending jobs on the current node's queue."""
    global network_manager_instance
    if network_manager_instance and hasattr(network_manager_instance, 'pending_jobs'):
        if not network_manager_instance.pending_jobs:
            click.echo("No pending jobs on this node.")
            return
        click.echo(click.style("Pending jobs on this node:", fg="cyan"))
        for i, job in enumerate(network_manager_instance.pending_jobs):
            click.echo(f"  {i+1}. ID: {job.job_id}")
            click.echo(f"     Kernel: {job.kernel_file_path}")
            click.echo(f"     Submitted by: {job.submitter_node_id[:8]}") # Show short ID
            click.echo(f"     Status: {job.status}")
    else:
        click.echo("Node not started or job data not available on this instance.", err=True)

@node_cli.command(name='start')
@click.option('--port', default=8000, type=int, show_default=True, help='Port to listen on.')
@click.option('--ip-address', default="0.0.0.0", show_default=True, help='IP address to bind to. Use 0.0.0.0 for all interfaces.')
@click.option('--bootstrap-node', help='Address of an existing node (ip:port) to connect to for peer discovery.')
@click.option('--node-id', help='Specify a Node ID. If not provided, one will be generated.')
def start_node_sync(port, ip_address, bootstrap_node, node_id):
    """Starts a cuda-chain node, listening for peers and jobs."""
    try:
        asyncio.run(start_node_async(port, ip_address, bootstrap_node, node_id))
    except KeyboardInterrupt:
        print("\nNode shutting down...")
        if network_manager_instance and network_manager_instance.server_instance:
            # This is a bit tricky as server_instance.close() and wait_closed() are async
            # and asyncio event loop is already stopped by KeyboardInterrupt in asyncio.run()
            # For a cleaner shutdown, specific signal handling would be needed.
            print("Server was running, may need manual process cleanup if not fully stopped.")
    except OSError as e: # Catches errors from NetworkManager.start_server (e.g. address in use)
        click.echo(f"Could not start node: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e!r}", err=True)


async def start_node_async(port, ip_address, bootstrap_node_address, node_id_arg):
    global network_manager_instance

    network_manager_instance = NetworkManager(self_node_ip=ip_address, self_node_port=port, node_id=node_id_arg)

    click.echo(f"Initializing Node ID: {network_manager_instance.self_node.node_id}")

    # start_server now also starts the job_processor_task internally
    server_task = asyncio.create_task(network_manager_instance.start_server())

    if bootstrap_node_address:
        # Give server a moment to fully start, especially when running locally.
        # This helps prevent race condition where bootstrap client tries to connect before server is ready.
        await asyncio.sleep(0.2)
        try:
            bootstrap_ip, bootstrap_port_str = bootstrap_node_address.split(':')
            bootstrap_port = int(bootstrap_port_str)
            await network_manager_instance.connect_to_bootstrap(bootstrap_ip, bootstrap_port)
        except ValueError:
            click.echo(f"Invalid bootstrap node address format: {bootstrap_node_address}. Use ip:port.", err=True)
            server_task.cancel()
            try: await server_task
            except asyncio.CancelledError: click.echo("Node startup cancelled due to bootstrap format error.")
            return
        except Exception as e: # Covers connection errors during bootstrap
            click.echo(f"Error connecting to bootstrap node {bootstrap_node_address}: {e!r}", err=True)
            server_task.cancel()
            try: await server_task
            except asyncio.CancelledError: click.echo("Node startup cancelled due to bootstrap connection error.")
            return

    click.echo(f"Node {network_manager_instance.self_node.node_id} is running. Listening on {network_manager_instance.self_node.ip_address}:{network_manager_instance.self_node.port}. Press Ctrl+C to stop.")

    try:
        await server_task
    except asyncio.CancelledError:
        click.echo("Node server was cancelled.")
    # OSError from start_server will propagate and be caught by sync wrapper if it happens before server_task is awaited nicely
    # Add finally block to start_node_async for cleanup
    finally:
        if network_manager_instance and network_manager_instance.job_processor_task and \
           not network_manager_instance.job_processor_task.done():
            print("CLI: start_node_async ending, ensuring job processor is cancelled.")
            network_manager_instance.job_processor_task.cancel()
            try:
                await network_manager_instance.job_processor_task
            except asyncio.CancelledError:
                print("CLI: Job processor task successfully cancelled on node stop.")
        print("CLI: Node event loop has finished.")

@node_cli.command(name='leave')
def node_leave_sync():
    """Announces departure to the network and shuts down the node."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started or already left.", err=True)
        return

    click.echo("Node leave initiated...")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() and not loop.is_closed() : # Check if current loop is active
             # This is the complex case: `node leave` called when `node start` is active.
             # We schedule `node_leave_async` which should cancel the server task from `start_node_async`.
             click.echo("Event loop is running. Scheduling leave task.")
             asyncio.ensure_future(node_leave_async(), loop=loop)
             # The CLI command will return, but the node will shut down in the background.
             # To make `node leave` blocking until shutdown, `start_node_sync` would need to
             # await a signal or the `server_task` in a way that `node_leave_async` can trigger completion.
             # This current approach is non-blocking for the `node leave` CLI command itself.
        else: # No loop running or it's closed, so run directly (e.g. in tests or if node start failed)
            click.echo("No active event loop or loop closed. Running leave task directly.")
            asyncio.run(node_leave_async())
    except RuntimeError: # No event loop, run directly
         click.echo("RuntimeError getting event loop. Running leave task directly.")
         asyncio.run(node_leave_async())

async def node_leave_async():
    global network_manager_instance
    if not network_manager_instance or network_manager_instance.shutting_down:
        # click.echo("Node already shutting down or not started.") # Can be too verbose
        return

    await network_manager_instance.announce_departure_and_shutdown()
    # The server_task in start_node_async should now be cancelled, leading to its completion.
    # This will allow the asyncio.run() call in start_node_sync to finish.
    click.echo("Node shutdown process completed from `node_leave_async`.")


@node_cli.command(name='status')
@click.argument('node_id_or_address', required=False)
def node_status_sync(node_id_or_address):
    """Displays status for the current node or a specified remote node."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Network manager not initialized. Start this node instance first.", err=True)
        return
    asyncio.run(node_status_async(node_id_or_address))

async def node_status_async(node_id_or_address):
    global network_manager_instance

    is_self_request = not node_id_or_address or \
                      node_id_or_address == network_manager_instance.self_node.node_id or \
                      node_id_or_address == f"{network_manager_instance.self_node.ip_address}:{network_manager_instance.self_node.port}"

    if is_self_request:
        click.echo(click.style("Status for Current Node (Self):", fg="blue"))
        status_data = network_manager_instance.self_node.to_dict()
        status_data['pending_jobs_count'] = len(network_manager_instance.pending_jobs)
        status_data['active_jobs_count'] = len(network_manager_instance.active_jobs)
        # status_data['completed_jobs_count'] = len(network_manager_instance.completed_jobs) # Optional
    else:
        click.echo(click.style(f"Requesting status for Remote Node: {node_id_or_address}", fg="blue"))
        status_data = await network_manager_instance.request_remote_node_status(node_id_or_address)

    if status_data:
        click.echo(f"  Node ID: {status_data.get('node_id')}")
        click.echo(f"  Address: {status_data.get('ip_address')}:{status_data.get('port')}")
        click.echo(f"  Status: {status_data.get('status', 'N/A')}") # Node's own status attribute
        click.echo(f"  Resources: {status_data.get('resources', {})}")
        click.echo(f"  Pending Jobs: {status_data.get('pending_jobs_count', 'N/A')}")
        click.echo(f"  Active Jobs: {status_data.get('active_jobs_count', 'N/A')}")
        # click.echo(f"  Completed Jobs: {status_data.get('completed_jobs_count', 'N/A')}") # If added
    else:
        # Only show error if a remote target was specified and failed
        if not is_self_request:
            click.echo(click.style(f"Could not retrieve status for node: {node_id_or_address}", fg="red"), err=True)
        # If it was a local status check that failed (which is unlikely here as it's constructed directly)
        # this 'else' block wouldn't be hit as status_data would be populated.

@node_cli.command(name='list')
def list_nodes():
    """Lists known peers and self node information."""
    global network_manager_instance
    if network_manager_instance:
        click.echo(click.style("Current Node (Self):", fg="cyan"))
        click.echo(f"  ID: {network_manager_instance.self_node.node_id}")
        click.echo(f"  Address: {network_manager_instance.self_node.ip_address}:{network_manager_instance.self_node.port}")
        click.echo(f"  Status: {network_manager_instance.self_node.status}")
        click.echo(f"  Resources: {network_manager_instance.self_node.resources}")

        peers = network_manager_instance.get_all_peers()
        if peers:
            click.echo(click.style("\nKnown Peers:", fg="cyan"))
            for i, peer_node in enumerate(peers): # Renamed to avoid conflict with peers module
                click.echo(f"  Peer {i+1}:")
                click.echo(f"    ID: {peer_node.node_id}")
                click.echo(f"    Address: {peer_node.ip_address}:{peer_node.port}")
                click.echo(f"    Status: {peer_node.status}")
                click.echo(f"    Resources: {peer_node.resources if peer_node.resources else 'Not available'}")
        else:
            click.echo("\nNo known peers.")
    else:
        click.echo("Network manager not initialized. Start a node first using 'node start'.")

@node_cli.command(name='ping')
@click.argument('target_address')
def ping_node_sync(target_address):
    """Sends a PING to a target node (ip:port)."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Network manager not initialized. Start this node instance first using 'node start' to use ping.", err=True)
        return
    asyncio.run(ping_node_async(target_address))

async def ping_node_async(target_address):
    global network_manager_instance
    try:
        target_ip, target_port_str = target_address.split(':')
        target_port = int(target_port_str)
    except ValueError:
        click.echo("Invalid target address format. Use ip:port.", err=True)
        return

    click.echo(f"Pinging {target_address} from node {network_manager_instance.self_node.node_id}...")
    ping_message = {"type": "PING"}
    response = await network_manager_instance.send_message(target_ip, target_port, ping_message)

    if response and response.get("type") == "PONG":
        click.echo(click.style(f"PONG received from {target_address} (Node ID: {response.get('sender_node_id', 'N/A')})", fg="green"))
    else:
        click.echo(click.style(f"No PONG (or unexpected response) from {target_address}. Response: {response!r}", fg="red"))

@click.group(name='job')
def job_cli():
    """Manage compute jobs."""
    pass
main.add_command(job_cli, name="job")


@job_cli.command(name="submit")
@click.argument('kernel_file', type=click.Path(exists=True, dir_okay=False))
@click.option('--input-file', type=click.Path(exists=True, dir_okay=False), help="Path to input data for the kernel.")
@click.option('--grid-dim', default="1,1,1", show_default=True, help="Grid dimensions (e.g., 'x,y,z' or 'x').")
@click.option('--block-dim', default="1,1,1", show_default=True, help="Block dimensions (e.g., 'x,y,z' or 'x').")
@click.option('--target-node', help="Optional target node address (ip:port) to send the job to.")
def submit_job_sync(kernel_file, input_file, grid_dim, block_dim, target_node):
    """Submits a CUDA kernel job to the network."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started. Please start the node using 'node start' first.", err=True)
        return
    # Ensure event loop is available for asyncio.run
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If an event loop is already running (e.g. from node start in same process, though unlikely with Click),
            # we might need a more complex setup or to run this in a new thread.
            # For now, assuming this CLI command is run when node might not be running in this exact process's loop.
            click.echo("An event loop is already running. Submitting job might behave unexpectedly.", err=True)
    except RuntimeError: # No event loop set
        pass # This is fine, asyncio.run will create one.

    asyncio.run(submit_job_async(kernel_file, input_file, grid_dim, block_dim, target_node))

async def submit_job_async(kernel_file, input_file, grid_dim_str, block_dim_str, target_node_addr_str):
    global network_manager_instance
    # Dimensions are parsed by submit_new_job in NetworkManager
    click.echo(f"CLI: Submitting job: Kernel='{kernel_file}', Input='{input_file}', Grid='{grid_dim_str}', Block='{block_dim_str}'")
    if target_node_addr_str:
        click.echo(f"CLI: Attempting to send directly to target node: {target_node_addr_str}")
    else:
        click.echo("CLI: No target node specified, NetworkManager will pick a peer or bootstrap.")

    job_ack = await network_manager_instance.submit_new_job(
        kernel_file_path=kernel_file,
        input_file_path=input_file,
        grid_dim_str=grid_dim_str, # Pass as string
        block_dim_str=block_dim_str, # Pass as string
        target_node_addr_str=target_node_addr_str
    )

    if job_ack and job_ack.get('type') == 'JOB_ACK' and job_ack.get('job_id'):
        click.echo(click.style(f"Job '{job_ack['job_id']}' submitted and acknowledged by node '{job_ack.get('receiver_node_id')[:8]}'. Status: {job_ack['status']}.", fg="green"))
    elif job_ack: # Some other response
        click.echo(click.style(f"Received unexpected acknowledgement: {job_ack!r}", fg="yellow"), err=True)
    else: # None response (error occurred)
        click.echo(click.style("Job submission failed or was not acknowledged.", fg="red"), err=True)

@job_cli.command(name="status")
@click.argument("job_id")
def job_status_sync(job_id):
    """Checks the status of a specific job known to this node."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started. Please start the node using 'node start' first.", err=True)
        return
    # This command is currently synchronous and checks local lists.
    # For a full network query, it would need to be async and potentially send messages.

    job_to_display = None
    source_list_name = ""

    # Check local job stores
    if job_id in network_manager_instance.completed_jobs:
        job_to_display = network_manager_instance.completed_jobs[job_id]
        source_list_name = "completed_jobs"
    elif job_id in network_manager_instance.active_jobs:
        job_to_display = network_manager_instance.active_jobs[job_id]
        source_list_name = "active_jobs"
    else: # Check pending_jobs (which is a list)
        for job in network_manager_instance.pending_jobs:
            if job.job_id == job_id:
                job_to_display = job
                source_list_name = "pending_jobs"
                break

    if job_to_display:
        click.echo(click.style(f"Status for Job ID: {job_to_display.job_id} (found in local {source_list_name})", fg="cyan"))
        click.echo(f"  Kernel: {job_to_display.kernel_file_path}")
        click.echo(f"  Input: {job_to_display.input_file_path if job_to_display.input_file_path else 'N/A'}")
        click.echo(f"  Grid Dim: {job_to_display.grid_dim}")
        click.echo(f"  Block Dim: {job_to_display.block_dim}")
        click.echo(f"  Status: {job_to_display.status}")
        click.echo(f"  Submitter Node ID: {job_to_display.submitter_node_id[:8]}")
        click.echo(f"  Assigned Node ID: {job_to_display.assigned_node_id[:8] if job_to_display.assigned_node_id else 'N/A'}")
        click.echo(f"  Assigned Timestamp: {job_to_display.assigned_timestamp.isoformat() if job_to_display.assigned_timestamp else 'N/A'}")
        click.echo(f"  Start Timestamp: {job_to_display.start_timestamp.isoformat() if job_to_display.start_timestamp else 'N/A'}")
        click.echo(f"  End Timestamp: {job_to_display.end_timestamp.isoformat() if job_to_display.end_timestamp else 'N/A'}")
    else:
        click.echo(f"Job with ID '{job_id}' not found in this node's pending, active, or completed lists.")

def print_job_details(job, list_name):
    click.echo(f"  Job ID: {job.job_id} (Status: {job.status})")
    click.echo(f"    Kernel: {job.kernel_file_path}, Input: {job.input_file_path if job.input_file_path else 'N/A'}")
    click.echo(f"    Dims: Grid={job.grid_dim}, Block={job.block_dim}")
    click.echo(f"    Submitter: {job.submitter_node_id[:8]}")
    if job.assigned_node_id:
        click.echo(f"    Assigned to: {job.assigned_node_id[:8]} at {job.assigned_timestamp.isoformat() if job.assigned_timestamp else 'N/A'}")
    if job.start_timestamp:
        click.echo(f"    Started: {job.start_timestamp.isoformat()}")
    if job.end_timestamp:
        click.echo(f"    Ended: {job.end_timestamp.isoformat()}")
    click.echo(f"    (Found in local list: {list_name})")


@job_cli.command(name="list")
def list_jobs_sync():
    """Lists all jobs known to this node, grouped by status."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started. Please start the node using 'node start' first.", err=True)
        return

    click.echo(click.style("Pending Jobs:", fg="yellow"))
    if network_manager_instance.pending_jobs:
        for job in network_manager_instance.pending_jobs:
            print_job_details(job, "pending_jobs")
    else:
        click.echo("  No pending jobs.")

    click.echo(click.style("\nActive Jobs:", fg="blue"))
    if network_manager_instance.active_jobs:
        for job_id, job in network_manager_instance.active_jobs.items():
            print_job_details(job, "active_jobs")
    else:
        click.echo("  No active jobs.")

    click.echo(click.style("\nCompleted Jobs:", fg="green"))
    if network_manager_instance.completed_jobs:
        for job_id, job in network_manager_instance.completed_jobs.items():
            print_job_details(job, "completed_jobs")
    else:
        click.echo("  No completed jobs.")

@job_cli.command(name="results")
@click.argument("job_id")
@click.option('--output-file', type=click.Path(dir_okay=False, writable=True), help="Optional file to save results to.")
def job_results_sync(job_id, output_file):
    """Retrieves and displays the result of a completed job."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started. Please start the node using 'node start' first.", err=True)
        return

    # Ensure event loop is available for asyncio.run, similar to submit_job_sync
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() and not network_manager_instance.job_processor_task.done(): # Check if our main loop is running
             # If node start created the loop, we can't just call asyncio.run again.
             # This command needs to be scheduled or handled carefully if the node is active.
             # For simplicity now, we'll assume it's okay or the user runs it when node is idle or from a different client.
             # A more robust solution would use network_manager_instance's loop to run the async part.
             click.echo("Attempting to run async job results while node event loop might be active.", fg="yellow")
    except RuntimeError: # No event loop set
        pass

    asyncio.run(job_results_async(job_id, output_file))

async def job_results_async(job_id, output_file):
    global network_manager_instance
    click.echo(f"Attempting to retrieve result for job ID: {job_id}...")

    result_content = await network_manager_instance.request_job_result(job_id)

    if result_content is not None:
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    f.write(result_content)
                click.echo(click.style(f"Result for job {job_id} saved to: {output_file}", fg="green"))
            except IOError as e:
                click.echo(click.style(f"Error writing result to file {output_file}: {e}", fg="red"), err=True)
        else:
            click.echo(click.style(f"Result for job {job_id}:", fg="cyan"))
            click.echo(result_content)
    else:
        click.echo(click.style(f"Could not retrieve result for job {job_id}.", fg="red"), err=True)

@job_cli.command(name="cancel")
@click.argument("job_id")
def job_cancel_sync(job_id):
    """Requests cancellation of a specific job."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started. Please start the node using 'node start' first.", err=True)
        return
    asyncio.run(job_cancel_async(job_id))

async def job_cancel_async(job_id):
    global network_manager_instance
    click.echo(f"Requesting cancellation for job ID: {job_id}...")

    ack = await network_manager_instance.request_job_cancellation(job_id)

    if ack:
        status = ack.get("status", "unknown_ack_format")
        acked_job_id = ack.get("job_id", "N/A")
        ack_node_id = ack.get("node_id", "N/A") # Node that processed the cancel ACK
        msg = ack.get("message", "")

        if status.startswith("cancelled_locally"):
            click.echo(click.style(f"Job {acked_job_id} successfully cancelled locally on node {ack_node_id[:8]}.", fg="green"))
        elif status == "cancelled_pending" or status == "cancelled_active": # From remote node
             click.echo(click.style(f"Cancellation of job {acked_job_id} acknowledged by node {ack_node_id[:8]} with status: {status}.", fg="green"))
        elif status.startswith("already_"):
            click.echo(click.style(f"Job {acked_job_id} was already in state '{status.split('_')[1]}' on node {ack_node_id[:8]}.", fg="yellow"))
        elif status == "not_found":
            click.echo(click.style(f"Job {acked_job_id} not found on node {ack_node_id[:8]} for cancellation.", fg="red"))
        elif status == "error_forwarding_peer_not_found":
            click.echo(click.style(f"Failed to forward cancellation for job {acked_job_id}: Assigned node not a peer.", fg="red"))
        elif status == "not_actionable":
            click.echo(click.style(f"Job {acked_job_id} could not be cancelled by node {ack_node_id[:8]}. Reason: {msg or 'Not actionable'}.", fg="yellow"))
        else: # Generic ACK or unexpected status
            click.echo(click.style(f"Cancellation ACK for job {acked_job_id} from node {ack_node_id[:8]}: Status '{status}'. {msg}", fg="blue"))
    else:
        click.echo(click.style(f"No acknowledgement received for job {job_id} cancellation request.", fg="red"), err=True)

@click.group(name='network')
def network_cli():
    """Network-wide information and commands."""
    pass
main.add_command(network_cli, name="network")

@network_cli.command(name="status")
def network_status_sync():
    """Displays an overview of the network from this node's perspective."""
    global network_manager_instance
    if not network_manager_instance:
        click.echo("Node not started. Please start the node using 'node start' first.", err=True)
        return

    # This is a synchronous command as it primarily accesses local data.
    # An async version could be created if, for example, it tried to ping all peers.

    click.echo(click.style("Network Status Overview:", fg="magenta"))
    click.echo(f"  Current Node ID: {network_manager_instance.self_node.node_id[:12]}...") # Shortened ID
    click.echo(f"  Listening Address: {network_manager_instance.self_node.ip_address}:{network_manager_instance.self_node.port}")

    peers = network_manager_instance.get_all_peers()
    click.echo(f"  Total Known Peers: {len(peers)}")

    if peers:
        click.echo(click.style("\n  Known Peers Details:", fg="cyan"))
        for i, peer_node in enumerate(peers):
            click.echo(f"    Peer {i+1}:")
            click.echo(f"      ID: {peer_node.node_id[:12]}...")
            click.echo(f"      Address: {peer_node.ip_address}:{peer_node.port}")
            click.echo(f"      Status: {peer_node.status}") # Assuming Node object has a status
            # Could add more details if available, e.g., from a periodic status ping (future work)
    else:
        click.echo("  No other peers are currently known to this node.")

    if network_manager_instance.bootstrap_node_addr:
        click.echo(f"\n  Connected via Bootstrap Node: {network_manager_instance.bootstrap_node_addr[0]}:{network_manager_instance.bootstrap_node_addr[1]}")
    else:
        click.echo("\n  Not connected via a bootstrap node (or bootstrap was self/local).")

    # Placeholder for more advanced network health checks
    # For example, one could iterate `network_manager_instance.get_all_peers()`
    # and try to `await network_manager_instance.request_remote_node_status(peer.node_id)` for each
    # to get a live view, but that would make this command async.

if __name__ == '__main__': # For running cli.py directly
    main()

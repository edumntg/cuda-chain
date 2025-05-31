import click
import requests
import json # For potential payload construction if needed, though not for current simple updates
from main import load_config # For getting token and server URL
from requester_commands import get_auth_headers # Reuse helper for auth

@click.group('worker')
def worker_group():
    """Commands for Workers (list jobs, take jobs, update status)."""
    pass

@worker_group.command('list-requests')
@click.option('--skip', default=0, help="Number of requests to skip (for pagination).")
@click.option('--limit', default=10, help="Maximum number of requests to return.")
@click.pass_context
def list_available_requests(ctx, skip, limit):
    """List available training requests from the server."""
    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/worker/requests/available" # Corrected endpoint

    headers = get_auth_headers()
    if not headers:
        return

    params = {"skip": skip, "limit": limit}

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()

        requests_data = response.json()

        if not requests_data:
            click.echo("No available training requests found.")
            return

        click.echo("Available Training Requests:")
        for req in requests_data:
            click.echo(f"  Request ID: {req.get('id')}")
            click.echo(f"    Status: {req.get('status')}")
            click.echo(f"    Created At: {req.get('created_at')}")
            click.echo(f"    Total Batches: {req.get('num_batches')}") # num_batches from TrainingRequestSimple schema
            # Metadata could be fetched via another call if needed, or added to TrainingRequestSimple
            click.echo("-" * 20)

    except requests.exceptions.HTTPError as e:
        error_detail = "Failed to list available requests."
        try:
            error_detail = e.response.json().get('detail', error_detail)
        except json.JSONDecodeError:
            pass
        click.echo(f"Error listing requests: {e.response.status_code} - {error_detail}", err=True)
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}", err=True)


@worker_group.command('take-request')
@click.argument('request_id', type=int)
@click.pass_context
def take_request(ctx, request_id):
    """Take an available batch from a specific training request."""
    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/worker/requests/{request_id}/take_batch" # Corrected endpoint

    headers = get_auth_headers()
    if not headers:
        return

    try:
        response = requests.post(api_url, headers=headers) # No JSON payload needed for this POST
        response.raise_for_status()

        batch_data = response.json()
        click.echo("Successfully assigned to batch:")
        click.echo(f"  Batch ID: {batch_data.get('id')}")
        click.echo(f"  Batch Number: {batch_data.get('batch_number')}")
        click.echo(f"  For Request ID: {batch_data.get('request_id')}")
        click.echo(f"  Status: {batch_data.get('status')}")
        click.echo(f"  Assigned Worker ID (You): {batch_data.get('worker_id')}")
        # You might want to display part of the metadata relevant to this batch if available

    except requests.exceptions.HTTPError as e:
        error_detail = "Failed to take request batch."
        try:
            error_detail = e.response.json().get('detail', error_detail)
        except json.JSONDecodeError:
            pass
        click.echo(f"Error taking request {request_id}: {e.response.status_code} - {error_detail}", err=True)
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}", err=True)


@worker_group.command('update-batch-status')
@click.argument('batch_id', type=int)
@click.argument('status', type=click.Choice(['completed', 'failed'], case_sensitive=False))
@click.pass_context
def update_batch_status(ctx, batch_id, status):
    """Update the status of an assigned batch (completed or failed)."""
    server_url = ctx.obj['SERVER_URL']
    # Endpoint changes based on status
    api_url = f"{server_url}/worker/batch/{batch_id}/{status.lower()}" # Corrected endpoint

    headers = get_auth_headers()
    if not headers:
        return

    try:
        response = requests.post(api_url, headers=headers) # No JSON payload
        response.raise_for_status()

        batch_data = response.json()
        click.echo(f"Batch {batch_id} status successfully updated to '{status}'.")
        click.echo(f"  New Batch Status: {batch_data.get('status')}")
        if status.lower() == 'failed':
            click.echo("  Note: This batch should now be available for other workers if re-queued as PENDING.")

    except requests.exceptions.HTTPError as e:
        error_detail = f"Failed to update batch {batch_id} to '{status}'."
        try:
            error_detail = e.response.json().get('detail', error_detail)
        except json.JSONDecodeError:
            pass
        click.echo(f"Error updating batch status: {e.response.status_code} - {error_detail}", err=True)
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}", err=True)

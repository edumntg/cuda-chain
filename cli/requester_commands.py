import click
import requests
import json # For reading metadata file
import os   # For path joining
from main import load_config # For getting token and server URL

# Helper function to get stored token (could be in a shared utils.py later)
def get_auth_headers():
    config = load_config()
    token = config.get('access_token')
    if not token:
        click.echo("Error: You are not logged in. Please run 'cpchain auth login' first.", err=True)
        return None
    return {"Authorization": f"Bearer {token}"}

@click.group('request')
def requester_group():
    """Commands for Requesters (submit jobs, check status)."""
    pass

@requester_group.command('submit')
@click.argument('metadata_filepath', type=click.Path(exists=True, dir_okay=False, readable=True))
@click.pass_context
def submit_request(ctx, metadata_filepath):
    """Submit a new training request using a JSON metadata file."""
    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/requests/" # This is the POST endpoint for submitting requests

    headers = get_auth_headers()
    if not headers:
        return

    try:
        with open(metadata_filepath, 'r') as f:
            metadata = json.load(f)
    except json.JSONDecodeError:
        click.echo(f"Error: Invalid JSON in metadata file: {metadata_filepath}", err=True)
        return
    except Exception as e:
        click.echo(f"Error reading metadata file {metadata_filepath}: {e}", err=True)
        return

    # The backend expects {"metadata": {...actual_metadata...}}
    # The TrainingRequestCreate schema has an alias "metadata" for "metadata_json"
    payload = {"metadata": metadata}

    try:
        response = requests.post(api_url, json=payload, headers=headers)
        response.raise_for_status()

        request_data = response.json()
        click.echo(f"Training request submitted successfully!")
        click.echo(f"Request ID: {request_data.get('id')}")
        click.echo(f"Status: {request_data.get('status')}")
        click.echo(f"Number of batches created: {len(request_data.get('batches', []))}")

    except requests.exceptions.HTTPError as e:
        error_detail = "Submission failed."
        try:
            error_detail = e.response.json().get('detail', error_detail)
        except json.JSONDecodeError:
            pass # Use default error_detail
        click.echo(f"Error submitting request: {e.response.status_code} - {error_detail}", err=True)
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}", err=True)


@requester_group.command('status')
@click.argument('request_id', type=int)
@click.pass_context
def request_status(ctx, request_id):
    """Check the status of a submitted training request."""
    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/requests/{request_id}/status"

    headers = get_auth_headers()
    if not headers:
        return

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        status_data = response.json()
        click.echo(f"Status for Request ID: {status_data.get('id')}")
        click.echo(f"  Overall Status: {status_data.get('status')}")
        click.echo(f"  Created At: {status_data.get('created_at')}")
        click.echo(f"  Updated At: {status_data.get('updated_at', 'N/A')}")
        click.echo(f"  Metadata: {json.dumps(status_data.get('metadata_json', {}), indent=2)}")

        batches = status_data.get('batches', [])
        if batches:
            click.echo(f"  Batches ({len(batches)} total):")
            for batch in batches:
                worker_id_display = batch.get('worker_id', 'N/A')
                click.echo(f"    - Batch Number: {batch.get('batch_number')}")
                click.echo(f"      Batch ID: {batch.get('id')}")
                click.echo(f"      Status: {batch.get('status')}")
                click.echo(f"      Assigned Worker ID: {worker_id_display}")
                click.echo(f"      Assigned At: {batch.get('assigned_at', 'N/A')}")
                click.echo(f"      Completed At: {batch.get('completed_at', 'N/A')}")
        else:
            click.echo("  No batch details found for this request.")

    except requests.exceptions.HTTPError as e:
        error_detail = "Failed to get status."
        try:
            error_detail = e.response.json().get('detail', error_detail)
        except json.JSONDecodeError:
            pass
        click.echo(f"Error getting status for request {request_id}: {e.response.status_code} - {error_detail}", err=True)
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}", err=True)

import click
import requests
import os # For main.py load_config, save_config if directly used, though better via ctx
from main import save_config, load_config # Import config functions

@click.group('auth')
def auth_group():
    """Commands for user authentication (register, login, logout)."""
    pass

@auth_group.command('register')
@click.option('--username', prompt=True, help="Username for registration.")
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help="Password for registration.")
@click.pass_context
def register(ctx, username, password):
    """Register a new user with the CPChain server."""
    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/auth/register"

    payload = {
        "username": username,
        "password": password
    }

    try:
        response = requests.post(api_url, json=payload)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        user_data = response.json()
        click.echo(f"User '{user_data.get('username')}' registered successfully with ID: {user_data.get('id')}.")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            click.echo(f"Error: {e.response.json().get('detail', 'Registration failed. Username might be taken.')}")
        else:
            click.echo(f"Error registering user: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}")


@auth_group.command('login')
@click.option('--username', prompt=True, help="Your username.")
@click.option('--password', prompt=True, hide_input=True, help="Your password.")
@click.pass_context
def login(ctx, username, password):
    """Login to the CPChain server and store the session token."""
    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/auth/login"

    payload = {
        "username": username,
        "password": password
    } # FastAPI's OAuth2PasswordRequestForm expects form data

    try:
        response = requests.post(api_url, data=payload) # Use data for form submission
        response.raise_for_status()

        token_data = response.json()
        access_token = token_data.get('access_token')

        if not access_token:
            click.echo("Error: No access token received from server.")
            return

        # Store the token in the config
        config = ctx.obj['CONFIG'] # load_config() already called in cli()
        config['access_token'] = access_token
        config['logged_in_user'] = username # Store username for reference
        save_config(config) # Use the save_config from main.py via ctx or direct import

        click.echo(f"Login successful. Token stored for user '{username}'.")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            click.echo(f"Error: {e.response.json().get('detail', 'Login failed. Incorrect username or password.')}")
        else:
            click.echo(f"Error during login: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server at {api_url}: {e}")

@auth_group.command('logout')
@click.pass_context
def logout(ctx):
    """Logout from the CPChain server by clearing the stored session token."""
    config = ctx.obj['CONFIG']
    logged_in_user = config.get('logged_in_user')

    if 'access_token' in config:
        del config['access_token']
    if 'logged_in_user' in config:
        del config['logged_in_user']

    save_config(config)

    if logged_in_user:
        click.echo(f"User '{logged_in_user}' logged out successfully.")
    else:
        click.echo("Logged out. No active session was found.")

@auth_group.command('whoami')
@click.pass_context
def whoami(ctx):
    """Check the currently logged-in user and test token validity."""
    config = ctx.obj['CONFIG']
    token = config.get('access_token')
    logged_in_user = config.get('logged_in_user')

    if not token or not logged_in_user:
        click.echo("You are not logged in.")
        return

    server_url = ctx.obj['SERVER_URL']
    api_url = f"{server_url}/auth/users/me" # Protected route on backend
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        user_data = response.json()
        click.echo(f"Logged in as: {user_data.get('username')} (ID: {user_data.get('id')})")
        click.echo(f"Token is valid.")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            click.echo(f"Token for user '{logged_in_user}' is invalid or expired. Please login again.")
            # Optionally clear the bad token here
            # if 'access_token' in config: del config['access_token']
            # if 'logged_in_user' in config: del config['logged_in_user']
            # save_config(config)
        else:
            click.echo(f"Error verifying token: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        click.echo(f"Error connecting to server: {e}")

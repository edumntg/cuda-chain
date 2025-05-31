import click
import os
import json

CONFIG_DIR = os.path.expanduser("~/.cpchain")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_SERVER_URL = "http://127.0.0.1:8000" # Default backend server URL

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

def load_config():
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {} # Return empty if config is corrupted
    return {} # Return empty if no config file

def save_config(config):
    ensure_config_dir()
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
    os.chmod(CONFIG_FILE, 0o600) # Secure the config file (read/write for user only)


@click.group()
@click.option('--server-url', help='Override the backend server URL.', envvar='CPCHAIN_SERVER_URL')
@click.pass_context
def cli(ctx, server_url):
    """CPChain: Decentralized AI Model Training Network CLI"""
    ctx.ensure_object(dict)
    config = load_config()

    # Priority: CLI option > Environment Variable > Config file > Default
    if server_url:
        ctx.obj['SERVER_URL'] = server_url
    elif os.getenv('CPCHAIN_SERVER_URL'):
        ctx.obj['SERVER_URL'] = os.getenv('CPCHAIN_SERVER_URL')
    elif 'server_url' in config:
        ctx.obj['SERVER_URL'] = config['server_url']
    else:
        ctx.obj['SERVER_URL'] = DEFAULT_SERVER_URL
        config['server_url'] = DEFAULT_SERVER_URL # Save default if not set
        save_config(config)

    ctx.obj['CONFIG'] = config


@cli.command()
@click.argument('url', required=False)
@click.pass_context
def configure(ctx, url):
    """Set or view the backend server URL."""
    config = ctx.obj['CONFIG']
    if url:
        config['server_url'] = url
        save_config(config)
        click.echo(f"Server URL configured to: {url}")
    else:
        server_url_to_display = ctx.obj.get('SERVER_URL', "Not set. Use 'configure <URL>' to set.")
        click.echo(f"Current Server URL: {server_url_to_display}")

# Placeholder for future command groups
from auth_commands import auth_group
from requester_commands import requester_group
from worker_commands import worker_group

cli.add_command(auth_group)
cli.add_command(requester_group)
cli.add_command(worker_group)

if __name__ == '__main__':
    cli()

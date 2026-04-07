"""
Authentication commands: login, logout, status.
"""

import asyncio
import base64
import datetime
import json

import click
from rich.console import Console
from rich.table import Table

from asta.auth.storage import TokenStorage
from asta.auth.token_manager import TokenManager
from asta.utils.auth_config import get_auth_settings

console = Console()


def _build_token_manager(service_name: str) -> TokenManager:
    settings = get_auth_settings(service_name=service_name)
    return TokenManager(
        auth0_domain=settings.auth0_domain,
        client_id=settings.auth0_client_id,
        audience=settings.auth0_audience,
        scopes=settings.auth0_scopes,
        callback_host=settings.auth0_callback_host,
        callback_port=settings.auth0_callback_port,
        callback_path=settings.auth0_callback_path,
        gateway_url=settings.gateway_url,
        service_name=service_name,
    )


def _has_refresh_token(storage: TokenStorage, service: str = "asta") -> bool:
    session = storage.load_session() or {}
    if session.get("refresh_token"):
        return True

    tokens = storage.load_tokens(service=service) or {}
    return bool(tokens.get("refresh_token"))


@click.group()
def auth():
    """Manage authentication."""
    pass


@auth.command()
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def login(no_browser):
    """Login to Asta using your browser."""
    console.print("🔐 [bold]Authenticating with Asta...[/bold]\n")

    token_manager = _build_token_manager("asta")

    try:
        asyncio.run(token_manager.login(open_browser=not no_browser))
        console.print("✅ [green]Authentication successful![/green]")

        user_info = token_manager.get_user_info()
        if user_info:
            console.print()
            console.print(
                f"   Logged in as: [cyan]{user_info.get('email', 'unknown')}[/cyan]"
            )
        console.print(
            "   Service-specific tokens will be fetched automatically as needed."
        )
    except Exception as e:
        console.print(f"❌ [red]Authentication failed: {e}[/red]")
        raise click.Abort()


@auth.command()
def logout():
    """Logout and remove stored credentials."""
    TokenStorage().delete_tokens()
    console.print("✅ [green]Logged out successfully[/green]")


@auth.command()
def status():
    """Show authentication status."""
    import time

    token_manager = _build_token_manager("asta")
    user_info = token_manager.get_user_info()

    if not user_info:
        console.print("❌ [red]Not authenticated[/red]")
        console.print("   Run [cyan]asta auth login[/cyan] to authenticate")
        return

    storage = TokenStorage()
    tokens = storage.load_tokens(service="asta")

    table = Table(title="Authentication Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    verification_result = token_manager.verify_token_with_gateway()

    if tokens:
        expires_at = tokens.get("expires_at", 0)
        has_refresh_token = _has_refresh_token(storage)
        current_time = time.time()

        if current_time >= expires_at:
            if has_refresh_token:
                token_status = "⚠️  [yellow]Expired (will auto-refresh)[/yellow]"
            else:
                token_status = "❌ [red]Expired (re-login required)[/red]"
        elif current_time >= expires_at - 300:
            token_status = "⏳ [yellow]Expiring soon (will auto-refresh)[/yellow]"
        else:
            token_status = "✅ [green]Valid[/green]"

        table.add_row("Local Token Status", token_status)

        if verification_result["valid"]:
            table.add_row("Server Verification", "✅ [green]Valid[/green]")
        else:
            error_msg = verification_result.get("error", "Unknown error")
            table.add_row(
                "Server Verification", f"❌ [red]Invalid[/red]\n   {error_msg}"
            )

        table.add_row("Email", user_info.get("email", "unknown"))
        table.add_row("Name", user_info.get("name", "unknown"))

        if expires_at:
            exp_time = datetime.datetime.fromtimestamp(expires_at)
            time_left = expires_at - current_time
            if time_left > 0:
                hours = int(time_left // 3600)
                minutes = int((time_left % 3600) // 60)
                exp_str = (
                    f"{exp_time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"({hours}h {minutes}m left)"
                )
            else:
                exp_str = f"{exp_time.strftime('%Y-%m-%d %H:%M:%S')} (expired)"
            table.add_row("Access Token Expires", exp_str)

        if has_refresh_token:
            table.add_row("Refresh Token", "✅ [green]Available[/green]")
            table.add_row("Auto-Refresh", "✅ [green]Enabled[/green]")
        else:
            table.add_row("Refresh Token", "❌ [red]Not available[/red]")
            table.add_row("Auto-Refresh", "❌ [red]Disabled[/red]")
    else:
        table.add_row("Status", "✅ Authenticated")
        table.add_row("Email", user_info.get("email", "unknown"))
        table.add_row("Name", user_info.get("name", "unknown"))

    console.print(table)

    if tokens:
        expires_at = tokens.get("expires_at", 0)
        has_refresh_token = _has_refresh_token(storage)
        current_time = time.time()

        if current_time >= expires_at and not has_refresh_token:
            console.print()
            console.print(
                "⚠️  [yellow]Your access token has expired and no refresh token is available.[/yellow]"
            )
            console.print("   Run [cyan]asta auth login[/cyan] to re-authenticate.")

        if not verification_result["valid"]:
            console.print()
            console.print(
                "⚠️  [yellow]Token verification failed with gateway server.[/yellow]"
            )
            console.print(
                "   You may need to run [cyan]asta auth login[/cyan] to re-authenticate."
            )


@auth.command(name="print-token")
@click.option("--raw", is_flag=True, help="Print raw base64-encoded token")
@click.option(
    "--refresh", is_flag=True, help="Refresh the token if expired before printing"
)
def print_token(raw, refresh):
    """Print the stored access token."""
    if refresh:
        from asta.auth.exceptions import AuthenticationError

        try:
            manager = _build_token_manager("asta")
            access_token = asyncio.run(manager.get_valid_access_token())
        except AuthenticationError as e:
            console.print(f"❌ [red]{e}[/red]")
            raise click.Abort()
    else:
        storage = TokenStorage()
        tokens = storage.load_tokens(service="asta")

        if not tokens or not tokens.get("access_token"):
            console.print("❌ [red]No token found[/red]")
            console.print("   Run [cyan]asta auth login[/cyan] to authenticate")
            raise click.Abort()

        access_token = tokens["access_token"]

    if raw:
        click.echo(access_token)
        return

    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            console.print("❌ [red]Invalid JWT format[/red]")
            raise click.Abort()

        def decode_base64url(data):
            """Decode base64url, adding padding if necessary."""
            padding = 4 - (len(data) % 4)
            if padding != 4:
                data += "=" * padding
            data = data.replace("-", "+").replace("_", "/")
            return base64.b64decode(data)

        header = json.loads(decode_base64url(parts[0]))
        payload = json.loads(decode_base64url(parts[1]))

        console.print("[bold]JWT Header:[/bold]")
        console.print(json.dumps(header, indent=2))
        console.print()
        console.print("[bold]JWT Payload:[/bold]")
        console.print(json.dumps(payload, indent=2))
    except Exception as e:
        console.print(f"❌ [red]Failed to decode token: {e}[/red]")
        console.print()
        console.print(
            "[yellow]Tip:[/yellow] Use [cyan]--raw[/cyan] to see the encoded token"
        )
        raise click.Abort()

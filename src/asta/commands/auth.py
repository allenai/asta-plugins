"""
Authentication commands: login, logout, status.
"""

import asyncio
import datetime

import click
from rich.console import Console
from rich.table import Table

from asta.auth.storage import TokenStorage
from asta.auth.token_manager import TokenManager
from asta.utils.auth_config import get_auth_settings

console = Console()


@click.group()
def auth():
    """Manage authentication."""
    pass


@auth.command()
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def login(no_browser):
    """Login to Asta using your browser."""
    console.print("🔐 [bold]Authenticating with Asta...[/bold]\n")

    settings = get_auth_settings()

    token_manager = TokenManager(
        auth0_domain=settings.auth0_domain,
        client_id=settings.auth0_client_id,
        audience=settings.auth0_audience,
        gateway_url=settings.gateway_url,
    )

    try:
        asyncio.run(token_manager.login(open_browser=not no_browser))
        console.print("✅ [green]Authentication successful![/green]\n")

        # Show user info
        user_info = token_manager.get_user_info()
        if user_info:
            console.print(
                f"   Logged in as: [cyan]{user_info.get('email', 'unknown')}[/cyan]"
            )

    except Exception as e:
        console.print(f"❌ [red]Authentication failed: {e}[/red]")
        raise click.Abort()


@auth.command()
def logout():
    """Logout and remove stored credentials."""
    settings = get_auth_settings()

    token_manager = TokenManager(
        auth0_domain=settings.auth0_domain,
        client_id=settings.auth0_client_id,
        audience=settings.auth0_audience,
        gateway_url=settings.gateway_url,
    )

    token_manager.logout()
    console.print("✅ [green]Logged out successfully[/green]")


@auth.command()
def status():
    """Show authentication status."""
    import time

    settings = get_auth_settings()

    token_manager = TokenManager(
        auth0_domain=settings.auth0_domain,
        client_id=settings.auth0_client_id,
        audience=settings.auth0_audience,
        gateway_url=settings.gateway_url,
    )

    user_info = token_manager.get_user_info()

    if not user_info:
        console.print("❌ [red]Not authenticated[/red]")
        console.print("   Run [cyan]asta auth login[/cyan] to authenticate")
        return

    # Get token details
    storage = TokenStorage()
    tokens = storage.load_tokens()

    # Create status table
    table = Table(title="Authentication Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    # Verify token with gateway server
    verification_result = token_manager.verify_token_with_gateway()

    # Check token status
    if tokens:
        expires_at = tokens.get("expires_at", 0)
        has_refresh_token = bool(tokens.get("refresh_token"))
        current_time = time.time()

        # Determine local token status
        if current_time >= expires_at:
            # Token is expired
            if has_refresh_token:
                token_status = "⚠️  [yellow]Expired (will auto-refresh)[/yellow]"
            else:
                token_status = "❌ [red]Expired (re-login required)[/red]"
        elif current_time >= expires_at - 300:
            # Token expiring soon (within 5 min)
            token_status = "⏳ [yellow]Expiring soon (will auto-refresh)[/yellow]"
        else:
            # Token is valid
            token_status = "✅ [green]Valid[/green]"

        table.add_row("Local Token Status", token_status)

        # Show server verification status
        if verification_result["valid"]:
            table.add_row("Server Verification", "✅ [green]Valid[/green]")
        else:
            error_msg = verification_result.get("error", "Unknown error")
            table.add_row(
                "Server Verification", f"❌ [red]Invalid[/red]\n   {error_msg}"
            )

        table.add_row("Email", user_info.get("email", "unknown"))
        table.add_row("Name", user_info.get("name", "unknown"))

        # Show token expiration
        if expires_at:
            exp_time = datetime.datetime.fromtimestamp(expires_at)
            time_left = expires_at - current_time
            if time_left > 0:
                hours = int(time_left // 3600)
                minutes = int((time_left % 3600) // 60)
                exp_str = f"{exp_time.strftime('%Y-%m-%d %H:%M:%S')} ({hours}h {minutes}m left)"
            else:
                exp_str = f"{exp_time.strftime('%Y-%m-%d %H:%M:%S')} (expired)"
            table.add_row("Access Token Expires", exp_str)

        # Show refresh token status
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

    # Show helpful message if action needed
    if tokens:
        expires_at = tokens.get("expires_at", 0)
        has_refresh_token = bool(tokens.get("refresh_token"))
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

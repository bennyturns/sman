"""sman CLI - AI-powered sysadmin agent."""

from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from sman import __version__
from sman.config import load_config
from sman.agent.agent import SmanAgent
from sman.tools.runner import CommandRisk

app = typer.Typer(
    name="sman",
    help="AI-powered sysadmin agent for Fedora/RHEL systems",
    no_args_is_help=True,
)
console = Console()


async def cli_approval(command: str, risk: CommandRisk) -> bool:
    """Prompt user for command approval in the terminal."""
    risk_color = "yellow" if risk == CommandRisk.NEEDS_APPROVAL else "red"
    console.print()
    console.print(Panel(
        Text(command, style="bold"),
        title=f"[{risk_color}]{risk.value.upper()}[/{risk_color}]",
        subtitle="approve? (y/n)",
        border_style=risk_color,
    ))
    return Confirm.ask("  Execute", default=True)


def run_async(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


@app.command()
def ask(
    request: str = typer.Argument(..., help="Natural language request"),
    local: bool = typer.Option(False, "--local", "-l", help="Force local model"),
    cloud: bool = typer.Option(False, "--cloud", "-c", help="Force cloud model"),
    config_path: str = typer.Option(None, "--config", "-C", help="Config file path"),
):
    """Send a one-shot request to sman."""
    from pathlib import Path

    cfg = load_config(Path(config_path) if config_path else None)

    if not cfg.llm.api_key and not cfg.llm.local_provider:
        console.print("[red]No API key configured.[/red]")
        console.print("Set ANTHROPIC_API_KEY env var or configure in ~/.config/sman/sman.toml")
        raise typer.Exit(1)

    force = None
    if local:
        force = "local"
    elif cloud:
        force = "cloud"

    agent = SmanAgent(cfg, approval_callback=cli_approval)

    async def _run():
        async for chunk in agent.ask(request, force_route=force):
            console.print(Markdown(chunk))

    run_async(_run())


@app.command()
def chat(
    config_path: str = typer.Option(None, "--config", "-C", help="Config file path"),
):
    """Start an interactive chat session with sman."""
    from pathlib import Path

    cfg = load_config(Path(config_path) if config_path else None)

    if not cfg.llm.api_key and not cfg.llm.local_provider:
        console.print("[red]No API key configured.[/red]")
        console.print("Set ANTHROPIC_API_KEY env var or configure in ~/.config/sman/sman.toml")
        raise typer.Exit(1)

    agent = SmanAgent(cfg, approval_callback=cli_approval)

    console.print(Panel(
        "[bold]sman[/bold] - AI Sysadmin Agent\n"
        "Type your request in natural language. Type 'exit' or 'quit' to leave.",
        border_style="blue",
    ))

    async def _run():
        while True:
            try:
                console.print()
                user_input = console.input("[bold blue]sman>[/bold blue] ").strip()

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    console.print("[dim]Goodbye.[/dim]")
                    break

                async for chunk in agent.ask(user_input):
                    console.print(Markdown(chunk))

            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye.[/dim]")
                break

    run_async(_run())


@app.command()
def status(
    config_path: str = typer.Option(None, "--config", "-C", help="Config file path"),
):
    """Show system status overview."""
    from pathlib import Path

    cfg = load_config(Path(config_path) if config_path else None)
    agent = SmanAgent(cfg)

    async def _run():
        result = await agent.diagnostics.system_overview()
        console.print(Panel(result.stdout, title="System Overview", border_style="green"))

        failed = await agent.diagnostics.failed_services()
        if failed.stdout.strip() and "0 loaded" not in failed.stdout:
            console.print(Panel(failed.stdout, title="Failed Services", border_style="red"))
        else:
            console.print("[green]No failed services.[/green]")

    run_async(_run())


@app.command()
def version():
    """Show sman version."""
    console.print(f"sman v{__version__}")


def main():
    app()


if __name__ == "__main__":
    main()

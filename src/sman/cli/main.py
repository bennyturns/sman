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
def monitor(
    config_path: str = typer.Option(None, "--config", "-C", help="Config file path"),
):
    """Run all health checks and show results."""
    from pathlib import Path
    from rich.table import Table

    cfg = load_config(Path(config_path) if config_path else None)

    async def _run():
        from sman.monitor.manager import MonitorManager
        mgr = MonitorManager(cfg)
        results = await mgr.run_all_checks()

        # SSH summary
        ssh = results.get("ssh_recent", {})
        if ssh:
            ssh_table = Table(title=f"SSH Activity (last {ssh.get('period_hours', 1)}h)")
            ssh_table.add_column("IP", style="red")
            ssh_table.add_column("Attempts", justify="right")
            ssh_table.add_column("Usernames")
            for offender in ssh.get("top_offenders", [])[:10]:
                ssh_table.add_row(
                    offender["ip"],
                    str(offender["count"]),
                    ", ".join(offender["usernames"][:5]),
                )
            console.print(ssh_table)
            console.print(f"Total: [red]{ssh['total_failures']}[/red] failures from [yellow]{ssh['unique_ips']}[/yellow] IPs | [green]{ssh['total_accepted']}[/green] accepted")
            console.print()

        # Disk space
        disks = results.get("disk_space", [])
        if disks:
            disk_table = Table(title="Disk Space")
            disk_table.add_column("Mount")
            disk_table.add_column("Size")
            disk_table.add_column("Used")
            disk_table.add_column("Avail")
            disk_table.add_column("Use%", justify="right")
            for d in disks:
                pct = d["use_percent"]
                style = "red" if pct >= 90 else "yellow" if pct >= 80 else "green"
                disk_table.add_row(
                    d["mount"], d["size"], d["used"], d["avail"],
                    f"[{style}]{pct}%[/{style}]",
                )
            console.print(disk_table)
            console.print()

        # SMART
        smart = results.get("disk_smart", [])
        if smart:
            for drive in smart:
                health_style = "green" if drive["health"] == "PASSED" else "red"
                issues = ", ".join(drive["issues"]) if drive["issues"] else "None"
                temp = f"{drive['temperature']}C" if drive["temperature"] else "N/A"
                console.print(f"SMART {drive['device']}: [{health_style}]{drive['health']}[/{health_style}] | {drive['model']} | Temp: {temp} | Issues: {issues}")
            console.print()

        # Services
        services = results.get("services", [])
        if services:
            svc_table = Table(title="Watched Services")
            svc_table.add_column("Service")
            svc_table.add_column("State")
            svc_table.add_column("Memory")
            svc_table.add_column("Restarts", justify="right")
            for s in services:
                state = s.get("active_state", "unknown")
                state_style = "green" if state == "active" else "red" if state == "failed" else "yellow"
                svc_table.add_row(
                    s["unit"],
                    f"[{state_style}]{state}[/{state_style}]",
                    s.get("memory_mb", "N/A") + (" MB" if s.get("memory_mb") else ""),
                    str(s.get("restarts", 0)),
                )
            console.print(svc_table)
            console.print()

        # Recent alerts
        alerts = results.get("alerts", [])
        if alerts:
            console.print(Panel(
                "\n".join(f"[{a['severity'].upper()}] {a['title']}: {a['message'][:100]}" for a in alerts[-5:]),
                title="Recent Alerts",
                border_style="red",
            ))

    run_async(_run())


@app.command()
def version():
    """Show sman version."""
    console.print(f"sman v{__version__}")


def main():
    app()


if __name__ == "__main__":
    main()

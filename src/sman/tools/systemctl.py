"""systemd service management tools."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class SystemctlTool:
    """Manage systemd services."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def status(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl status {unit} --no-pager -l")

    async def start(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl start {unit}")

    async def stop(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl stop {unit}")

    async def restart(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl restart {unit}")

    async def reload(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl reload {unit}")

    async def enable(self, unit: str, now: bool = False) -> CommandResult:
        cmd = f"systemctl enable {unit}"
        if now:
            cmd += " --now"
        return await self.runner.execute(cmd)

    async def disable(self, unit: str, now: bool = False) -> CommandResult:
        cmd = f"systemctl disable {unit}"
        if now:
            cmd += " --now"
        return await self.runner.execute(cmd)

    async def is_active(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl is-active {unit}")

    async def is_enabled(self, unit: str) -> CommandResult:
        return await self.runner.execute(f"systemctl is-enabled {unit}")

    async def list_units(self, state: str | None = None) -> CommandResult:
        cmd = "systemctl list-units --no-pager"
        if state:
            cmd += f" --state={state}"
        return await self.runner.execute(cmd)

    async def list_failed(self) -> CommandResult:
        return await self.runner.execute("systemctl list-units --failed --no-pager")

    async def daemon_reload(self) -> CommandResult:
        return await self.runner.execute("systemctl daemon-reload")

    async def show(self, unit: str, properties: list[str] | None = None) -> CommandResult:
        cmd = f"systemctl show {unit} --no-pager"
        if properties:
            cmd += f" --property={','.join(properties)}"
        return await self.runner.execute(cmd)

    async def logs(self, unit: str, lines: int = 50, since: str | None = None) -> CommandResult:
        cmd = f"journalctl -u {unit} --no-pager -n {lines}"
        if since:
            cmd += f" --since '{since}'"
        return await self.runner.execute(cmd)

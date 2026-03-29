"""Package management tools (dnf)."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class PackageTool:
    """Manage packages via dnf."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def install(self, packages: list[str]) -> CommandResult:
        pkgs = " ".join(packages)
        return await self.runner.execute(f"dnf install -y {pkgs}")

    async def remove(self, packages: list[str]) -> CommandResult:
        pkgs = " ".join(packages)
        return await self.runner.execute(f"dnf remove -y {pkgs}")

    async def update(self, packages: list[str] | None = None, exclude: list[str] | None = None) -> CommandResult:
        cmd = "dnf update -y"
        if exclude:
            for pkg in exclude:
                cmd += f" --exclude={pkg}"
        if packages:
            cmd += " " + " ".join(packages)
        return await self.runner.execute(cmd, timeout=600)

    async def search(self, query: str) -> CommandResult:
        return await self.runner.execute(f"dnf search {query}")

    async def info(self, package: str) -> CommandResult:
        return await self.runner.execute(f"dnf info {package}")

    async def list_installed(self, pattern: str | None = None) -> CommandResult:
        cmd = "dnf list installed"
        if pattern:
            cmd += f" {pattern}"
        return await self.runner.execute(cmd)

    async def check_update(self) -> CommandResult:
        return await self.runner.execute("dnf check-update", timeout=120)

    async def history(self, count: int = 20) -> CommandResult:
        return await self.runner.execute(f"dnf history list --reverse 2>/dev/null | tail -n {count}")

    async def history_undo(self, transaction_id: int) -> CommandResult:
        return await self.runner.execute(f"dnf history undo {transaction_id} -y")

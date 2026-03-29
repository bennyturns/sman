"""File system tools for reading, writing, and searching files."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class FileTool:
    """File system operations with safety controls."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def read(self, path: str) -> CommandResult:
        return await self.runner.read_file(path)

    async def write(self, path: str, content: str) -> CommandResult:
        return await self.runner.write_file(path, content)

    async def search(self, pattern: str, path: str = "/etc") -> CommandResult:
        return await self.runner.execute(f"grep -rn '{pattern}' {path} 2>/dev/null | head -50")

    async def find(self, path: str, name: str) -> CommandResult:
        return await self.runner.execute(f"find {path} -name '{name}' 2>/dev/null | head -50")

    async def list_dir(self, path: str) -> CommandResult:
        return await self.runner.execute(f"ls -la {path}")

    async def disk_usage(self, path: str = "/") -> CommandResult:
        return await self.runner.execute(f"df -h {path}")

    async def dir_size(self, path: str) -> CommandResult:
        return await self.runner.execute(f"du -sh {path}")

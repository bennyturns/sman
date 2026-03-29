"""Firewall management tools (firewalld)."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class FirewallTool:
    """Manage firewalld rules."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def list_all(self) -> CommandResult:
        return await self.runner.execute("firewall-cmd --list-all")

    async def list_ports(self) -> CommandResult:
        return await self.runner.execute("firewall-cmd --list-ports")

    async def list_services(self) -> CommandResult:
        return await self.runner.execute("firewall-cmd --list-services")

    async def add_port(self, port: str, protocol: str = "tcp", permanent: bool = True) -> CommandResult:
        cmd = f"firewall-cmd --add-port={port}/{protocol}"
        if permanent:
            cmd += " --permanent"
        result = await self.runner.execute(cmd)
        if permanent and result.success:
            await self.reload()
        return result

    async def remove_port(self, port: str, protocol: str = "tcp", permanent: bool = True) -> CommandResult:
        cmd = f"firewall-cmd --remove-port={port}/{protocol}"
        if permanent:
            cmd += " --permanent"
        result = await self.runner.execute(cmd)
        if permanent and result.success:
            await self.reload()
        return result

    async def add_service(self, service: str, permanent: bool = True) -> CommandResult:
        cmd = f"firewall-cmd --add-service={service}"
        if permanent:
            cmd += " --permanent"
        result = await self.runner.execute(cmd)
        if permanent and result.success:
            await self.reload()
        return result

    async def remove_service(self, service: str, permanent: bool = True) -> CommandResult:
        cmd = f"firewall-cmd --remove-service={service}"
        if permanent:
            cmd += " --permanent"
        result = await self.runner.execute(cmd)
        if permanent and result.success:
            await self.reload()
        return result

    async def add_rich_rule(self, rule: str, permanent: bool = True) -> CommandResult:
        cmd = f"firewall-cmd --add-rich-rule='{rule}'"
        if permanent:
            cmd += " --permanent"
        result = await self.runner.execute(cmd)
        if permanent and result.success:
            await self.reload()
        return result

    async def remove_rich_rule(self, rule: str, permanent: bool = True) -> CommandResult:
        cmd = f"firewall-cmd --remove-rich-rule='{rule}'"
        if permanent:
            cmd += " --permanent"
        result = await self.runner.execute(cmd)
        if permanent and result.success:
            await self.reload()
        return result

    async def reload(self) -> CommandResult:
        return await self.runner.execute("firewall-cmd --reload")

    async def get_zones(self) -> CommandResult:
        return await self.runner.execute("firewall-cmd --get-zones")

    async def get_default_zone(self) -> CommandResult:
        return await self.runner.execute("firewall-cmd --get-default-zone")

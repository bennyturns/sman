"""Network management tools (nmcli, ip, ss)."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class NetworkTool:
    """Manage network configuration."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def connections(self) -> CommandResult:
        return await self.runner.execute("nmcli connection show")

    async def connection_details(self, name: str) -> CommandResult:
        return await self.runner.execute(f"nmcli connection show '{name}'")

    async def devices(self) -> CommandResult:
        return await self.runner.execute("nmcli device status")

    async def set_static_ip(
        self, connection: str, ip: str, gateway: str, dns: str = "8.8.8.8,8.8.4.4"
    ) -> CommandResult:
        cmds = [
            f"nmcli connection modify '{connection}' ipv4.addresses {ip}",
            f"nmcli connection modify '{connection}' ipv4.gateway {gateway}",
            f"nmcli connection modify '{connection}' ipv4.dns '{dns}'",
            f"nmcli connection modify '{connection}' ipv4.method manual",
            f"nmcli connection up '{connection}'",
        ]
        return await self.runner.execute(" && ".join(cmds))

    async def set_dhcp(self, connection: str) -> CommandResult:
        cmds = [
            f"nmcli connection modify '{connection}' ipv4.method auto",
            f"nmcli connection modify '{connection}' ipv4.addresses ''",
            f"nmcli connection modify '{connection}' ipv4.gateway ''",
            f"nmcli connection up '{connection}'",
        ]
        return await self.runner.execute(" && ".join(cmds))

    async def ip_addresses(self) -> CommandResult:
        return await self.runner.execute("ip addr show")

    async def routes(self) -> CommandResult:
        return await self.runner.execute("ip route show")

    async def listening_ports(self) -> CommandResult:
        return await self.runner.execute("ss -tlnp")

    async def all_connections(self) -> CommandResult:
        return await self.runner.execute("ss -tnp")

    async def dns_lookup(self, hostname: str) -> CommandResult:
        return await self.runner.execute(f"dig +short {hostname}")

    async def ping(self, host: str, count: int = 4) -> CommandResult:
        return await self.runner.execute(f"ping -c {count} {host}", timeout=30)

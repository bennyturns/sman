"""System diagnostics and health check tools."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class DiagnosticTool:
    """System health and diagnostic operations."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def system_overview(self) -> CommandResult:
        """Get a comprehensive system overview."""
        cmd = (
            "echo '=== HOSTNAME ===' && hostname && "
            "echo '=== UPTIME ===' && uptime && "
            "echo '=== OS ===' && cat /etc/os-release | head -4 && "
            "echo '=== KERNEL ===' && uname -r && "
            "echo '=== CPU ===' && nproc && "
            "echo '=== MEMORY ===' && free -h && "
            "echo '=== DISK ===' && df -h / /home 2>/dev/null && "
            "echo '=== LOAD ===' && cat /proc/loadavg"
        )
        return await self.runner.execute(cmd)

    async def top_processes(self, count: int = 10) -> CommandResult:
        return await self.runner.execute(
            f"ps aux --sort=-%mem | head -n {count + 1}"
        )

    async def memory_usage(self) -> CommandResult:
        return await self.runner.execute("free -h")

    async def cpu_usage(self) -> CommandResult:
        return await self.runner.execute(
            "top -bn1 | head -20"
        )

    async def disk_space(self) -> CommandResult:
        return await self.runner.execute("df -h")

    async def disk_inodes(self) -> CommandResult:
        return await self.runner.execute("df -i")

    async def smart_health(self, device: str) -> CommandResult:
        return await self.runner.execute(f"smartctl -a {device}")

    async def smart_all_drives(self) -> CommandResult:
        return await self.runner.execute(
            "lsblk -d -o NAME,SIZE,TYPE,MODEL && echo '---' && "
            "for dev in $(lsblk -dno NAME | grep -E '^sd|^nvme'); do "
            "echo \"=== /dev/$dev ===\" && smartctl -H /dev/$dev 2>/dev/null || echo 'SMART not available'; "
            "done"
        )

    async def journal_errors(self, since: str = "1h ago", priority: str = "err") -> CommandResult:
        return await self.runner.execute(
            f"journalctl --since '{since}' -p {priority} --no-pager -n 100"
        )

    async def failed_services(self) -> CommandResult:
        return await self.runner.execute("systemctl list-units --failed --no-pager")

    async def selinux_denials(self, since: str = "1h ago") -> CommandResult:
        return await self.runner.execute(
            f"ausearch -m avc --start recent 2>/dev/null | tail -50 || "
            f"journalctl -t setroubleshoot --since '{since}' --no-pager 2>/dev/null || "
            f"echo 'No SELinux denials found or audit not available'"
        )

    async def network_connections(self) -> CommandResult:
        return await self.runner.execute("ss -tnp | head -50")

    async def sensors(self) -> CommandResult:
        return await self.runner.execute("sensors 2>/dev/null || echo 'lm-sensors not installed'")

    async def swap_usage(self) -> CommandResult:
        return await self.runner.execute(
            "free -h | grep -i swap && echo '---' && "
            "cat /proc/swaps"
        )

    async def recent_auth_failures(self, count: int = 30) -> CommandResult:
        return await self.runner.execute(
            f"journalctl -u sshd --no-pager -n {count} | grep -i 'failed\\|invalid\\|refused' || "
            f"echo 'No recent auth failures'"
        )

    async def certificate_check(self, path: str) -> CommandResult:
        return await self.runner.execute(
            f"openssl x509 -in {path} -noout -subject -issuer -dates 2>/dev/null || "
            f"echo 'Could not read certificate at {path}'"
        )

    async def load_average(self) -> CommandResult:
        return await self.runner.execute("cat /proc/loadavg && echo '' && nproc")

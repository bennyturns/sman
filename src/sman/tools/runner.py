"""Safe command execution with classification, approval, backup, and audit logging."""

from __future__ import annotations

import asyncio
import datetime
import json
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Awaitable

from sman.config import SmanConfig


class CommandRisk(Enum):
    SAFE = "safe"  # read-only, no side effects
    NEEDS_APPROVAL = "needs_approval"  # write operations
    DANGEROUS = "dangerous"  # destructive, hard to reverse


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    approved: bool = True
    risk: CommandRisk = CommandRisk.SAFE

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """Combined output for display."""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        return "\n".join(parts) if parts else "(no output)"


# Commands that are always safe (read-only)
SAFE_PATTERNS = [
    r"^systemctl\s+(status|is-active|is-enabled|is-failed|list-units|list-timers|show)\b",
    r"^journalctl\b",
    r"^cat\s+",
    r"^ls\b",
    r"^df\b",
    r"^du\b",
    r"^free\b",
    r"^uptime$",
    r"^hostname$",
    r"^uname\b",
    r"^whoami$",
    r"^id\b",
    r"^ps\b",
    r"^top\s+-bn1",
    r"^ss\b",
    r"^ip\s+(addr|route|link)\s+show",
    r"^ip\s+(addr|route|link)$",
    r"^firewall-cmd\s+--list",
    r"^firewall-cmd\s+--get",
    r"^firewall-cmd\s+--info",
    r"^firewall-cmd\s+--query",
    r"^nmcli\s+(general|device|connection)\s+show",
    r"^nmcli\s+(general|device|connection)$",
    r"^dnf\s+(list|info|search|repolist|check-update)\b",
    r"^rpm\s+-q",
    r"^smartctl\b",
    r"^lsblk\b",
    r"^blkid\b",
    r"^mount$",
    r"^findmnt\b",
    r"^getent\b",
    r"^grep\b",
    r"^find\b",
    r"^head\b",
    r"^tail\b",
    r"^wc\b",
    r"^sort\b",
    r"^date\b",
    r"^timedatectl\s*(status)?$",
    r"^hostnamectl\s*(status)?$",
    r"^sestatus$",
    r"^getenforce$",
    r"^nginx\s+-t$",
    r"^nginx\s+-T$",
    r"^httpd\s+-t$",
    r"^pg_isready\b",
    r"^openssl\s+(s_client|x509|verify)\b",
    r"^curl\s+",
    r"^dig\b",
    r"^nslookup\b",
    r"^ping\s+-c\s+\d+\s+",
    r"^traceroute\b",
    r"^sensors$",
]

# Commands that are dangerous (destructive, hard to reverse)
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/[^.]",  # rm -rf /anything (but not /./relative)
    r"mkfs\b",
    r"dd\s+if=",
    r">\s*/dev/sd",
    r"chmod\s+-R\s+777\s+/",
    r":\(\)\{\s*:\|:&\s*\};:",  # fork bomb
    r"shred\b",
    r"wipefs\b",
    r"sgdisk\s+--zap",
    r"fdisk\b",
    r"parted\b",
    r"lvremove\b",
    r"vgremove\b",
    r"pvremove\b",
]


class CommandClassifier:
    """Classifies commands by risk level."""

    def __init__(self, config: SmanConfig):
        self.blocked = config.safety.blocked_patterns
        self._safe_re = [re.compile(p) for p in SAFE_PATTERNS]
        self._dangerous_re = [re.compile(p) for p in DANGEROUS_PATTERNS]
        self._blocked_re = [re.compile(re.escape(p)) for p in self.blocked]

    def classify(self, command: str) -> CommandRisk:
        cmd = command.strip()

        # Check blocked patterns first
        for pattern in self._blocked_re:
            if pattern.search(cmd):
                return CommandRisk.DANGEROUS

        # Check dangerous patterns
        for pattern in self._dangerous_re:
            if pattern.search(cmd):
                return CommandRisk.DANGEROUS

        # Check safe patterns
        for pattern in self._safe_re:
            if pattern.search(cmd):
                return CommandRisk.SAFE

        # Default to needs approval
        return CommandRisk.NEEDS_APPROVAL

    def is_blocked(self, command: str) -> bool:
        for pattern in self._blocked_re:
            if pattern.search(command.strip()):
                return True
        return False


class ToolRunner:
    """Executes system commands with safety controls."""

    def __init__(
        self,
        config: SmanConfig,
        approval_callback: Callable[[str, CommandRisk], Awaitable[bool]] | None = None,
    ):
        self.config = config
        self.classifier = CommandClassifier(config)
        self.approval_callback = approval_callback
        self.audit_log = config.data_dir / "audit.log"

    async def execute(
        self,
        command: str,
        timeout: int = 60,
        force_approve: bool = False,
    ) -> CommandResult:
        """Execute a command with safety checks and approval flow."""
        risk = self.classifier.classify(command)

        # Block dangerous commands
        if risk == CommandRisk.DANGEROUS and not force_approve:
            result = CommandResult(
                command=command,
                exit_code=1,
                stdout="",
                stderr=f"BLOCKED: Command classified as dangerous. Use --force to override.",
                approved=False,
                risk=risk,
            )
            await self._audit(result)
            return result

        # Check approval for write operations
        if (
            risk == CommandRisk.NEEDS_APPROVAL
            and self.config.safety.require_approval
            and not force_approve
        ):
            if self.approval_callback:
                approved = await self.approval_callback(command, risk)
                if not approved:
                    result = CommandResult(
                        command=command,
                        exit_code=1,
                        stdout="",
                        stderr="Command denied by user.",
                        approved=False,
                        risk=risk,
                    )
                    await self._audit(result)
                    return result
            # If no callback set, default to approve (daemon mode handles via API)

        # Execute
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            result = CommandResult(
                command=command,
                exit_code=proc.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                approved=True,
                risk=risk,
            )
        except asyncio.TimeoutError:
            result = CommandResult(
                command=command,
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                approved=True,
                risk=risk,
            )
        except Exception as e:
            result = CommandResult(
                command=command,
                exit_code=1,
                stdout="",
                stderr=str(e),
                approved=True,
                risk=risk,
            )

        await self._audit(result)
        return result

    async def backup_file(self, path: str) -> str | None:
        """Create a backup of a file before modifying it. Returns backup path."""
        src = Path(path)
        if not src.exists():
            return None

        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = src.with_suffix(f"{src.suffix}.sman-backup-{timestamp}")
        shutil.copy2(src, backup)

        await self._audit_entry(f"BACKUP: {path} -> {backup}")
        return str(backup)

    async def write_file(self, path: str, content: str) -> CommandResult:
        """Write content to a file with backup."""
        backup = await self.backup_file(path)
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content)
            msg = f"Written to {path}"
            if backup:
                msg += f" (backup: {backup})"
            return CommandResult(
                command=f"write_file({path})",
                exit_code=0,
                stdout=msg,
                stderr="",
                risk=CommandRisk.NEEDS_APPROVAL,
            )
        except Exception as e:
            return CommandResult(
                command=f"write_file({path})",
                exit_code=1,
                stdout="",
                stderr=str(e),
                risk=CommandRisk.NEEDS_APPROVAL,
            )

    async def read_file(self, path: str) -> CommandResult:
        """Read a file's contents."""
        try:
            content = Path(path).read_text()
            return CommandResult(
                command=f"read_file({path})",
                exit_code=0,
                stdout=content,
                stderr="",
                risk=CommandRisk.SAFE,
            )
        except Exception as e:
            return CommandResult(
                command=f"read_file({path})",
                exit_code=1,
                stdout="",
                stderr=str(e),
                risk=CommandRisk.SAFE,
            )

    async def _audit(self, result: CommandResult) -> None:
        """Log command execution to audit trail."""
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "command": result.command,
            "risk": result.risk.value,
            "approved": result.approved,
            "exit_code": result.exit_code,
            "success": result.success,
        }
        await self._audit_entry(json.dumps(entry))

    async def _audit_entry(self, line: str) -> None:
        """Append a line to the audit log."""
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_log, "a") as f:
            f.write(line + "\n")

"""General journal watcher for system events."""

from __future__ import annotations

import asyncio
import logging
import re

from sman.config import SmanConfig
from sman.alerts.dispatcher import Alert, AlertDispatcher, Severity

log = logging.getLogger(__name__)

# Patterns to watch for in journal output
OOM_RE = re.compile(r"Out of memory: Killed process (\d+) \((.+?)\)")
SUDO_FAIL_RE = re.compile(r"(\S+) : .*authentication failure.*; logname=\S* uid=\d+ .* user=(\S+)")
NEW_UNIT_RE = re.compile(r"(Created|Started) (.+\.(?:service|timer))")


class JournalMonitor:
    """Watches journald for critical system events."""

    def __init__(self, config: SmanConfig, dispatcher: AlertDispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self._running = False

    async def start(self) -> None:
        """Start tailing the journal for critical events."""
        self._running = True
        log.info("Journal monitor started")

        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-f", "--no-pager", "-p", "warning", "-o", "short-iso",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            while self._running and proc.stdout:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                await self._process_line(line)
        except asyncio.CancelledError:
            pass
        finally:
            proc.terminate()
            try:
                await proc.wait()
            except Exception:
                pass
            log.info("Journal monitor stopped")

    def stop(self) -> None:
        self._running = False

    async def _process_line(self, line: str) -> None:
        """Process a journal line and generate alerts."""
        # OOM killer
        match = OOM_RE.search(line)
        if match:
            pid, process = match.groups()
            await self.dispatcher.dispatch(Alert(
                title=f"OOM killer: {process} killed",
                message=f"Out of memory: process {process} (PID {pid}) was killed by the OOM killer.",
                severity=Severity.CRITICAL,
                source="journal_monitor",
                details={"pid": pid, "process": process},
                recommendation="Check memory usage: free -h && ps aux --sort=-%mem | head -10",
            ))
            return

        # Sudo auth failures
        match = SUDO_FAIL_RE.search(line)
        if match:
            pam_user, target_user = match.groups()
            await self.dispatcher.dispatch(Alert(
                title=f"Sudo auth failure: {target_user}",
                message=f"Failed sudo authentication for user '{target_user}'",
                severity=Severity.WARNING,
                source="journal_monitor",
                details={"user": target_user},
            ))
            return

        # Disk I/O errors
        if "I/O error" in line or "Buffer I/O error" in line:
            await self.dispatcher.dispatch(Alert(
                title="Disk I/O error detected",
                message=f"Disk I/O error in journal: {line}",
                severity=Severity.CRITICAL,
                source="journal_monitor",
                recommendation="Check disk health: smartctl -a /dev/sdX",
            ))
            return

        # Filesystem errors
        if "EXT4-fs error" in line or "XFS error" in line or "BTRFS error" in line:
            await self.dispatcher.dispatch(Alert(
                title="Filesystem error detected",
                message=f"Filesystem error: {line}",
                severity=Severity.CRITICAL,
                source="journal_monitor",
                recommendation="Check filesystem: dmesg | grep -i error",
            ))
            return

        # Segfaults
        if "segfault" in line.lower():
            await self.dispatcher.dispatch(Alert(
                title="Process segfault",
                message=f"Segmentation fault detected: {line}",
                severity=Severity.WARNING,
                source="journal_monitor",
            ))
            return

        # Kernel panic indicators
        if "kernel panic" in line.lower() or "BUG:" in line:
            await self.dispatcher.dispatch(Alert(
                title="Kernel error detected",
                message=f"Kernel error: {line}",
                severity=Severity.EMERGENCY,
                source="journal_monitor",
                recommendation="Review dmesg output and consider a reboot if system is unstable.",
            ))
            return

"""SSH brute force detection monitor."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sman.config import SmanConfig
from sman.alerts.dispatcher import Alert, AlertDispatcher, Severity

log = logging.getLogger(__name__)

# Regex patterns for sshd journal entries
FAILED_RE = re.compile(
    r"Failed (?:password|publickey) for (?:invalid user )?(\S+) from (\S+) port (\d+)"
)
ACCEPTED_RE = re.compile(
    r"Accepted (?:password|publickey) for (\S+) from (\S+) port (\d+)"
)


@dataclass
class AttackTracker:
    """Tracks failed attempts per IP within a sliding window."""
    ip: str
    count: int = 0
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    usernames: set = field(default_factory=set)
    alerted: bool = False


class SSHMonitor:
    """Monitors SSH authentication events from journald."""

    def __init__(self, config: SmanConfig, dispatcher: AlertDispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self.threshold = config.monitor.ssh_brute_force_threshold
        self.window = config.monitor.ssh_brute_force_window  # seconds
        self._trackers: dict[str, AttackTracker] = defaultdict(
            lambda: AttackTracker(ip="")
        )
        self._running = False

    async def start(self) -> None:
        """Start monitoring SSH logs via journalctl --follow."""
        self._running = True
        log.info(f"SSH monitor started (threshold={self.threshold}, window={self.window}s)")

        # Run journalctl -u sshd -f and parse output
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", "sshd", "-f", "--no-pager", "-o", "short-iso",
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
            log.info("SSH monitor stopped")

    def stop(self) -> None:
        self._running = False

    async def _process_line(self, line: str) -> None:
        """Process a single journal line."""
        # Check for failed auth
        match = FAILED_RE.search(line)
        if match:
            username, ip, port = match.groups()
            await self._record_failure(ip, username)
            return

        # Check for successful auth from suspicious IP
        match = ACCEPTED_RE.search(line)
        if match:
            username, ip, port = match.groups()
            tracker = self._trackers.get(ip)
            if tracker and tracker.count >= self.threshold:
                # Successful login from a brute-forcing IP — very bad
                await self.dispatcher.dispatch(Alert(
                    title=f"Successful login from brute-force IP",
                    message=f"User '{username}' logged in from {ip} which has {tracker.count} failed attempts. This may indicate a compromised account.",
                    severity=Severity.EMERGENCY,
                    source="ssh_monitor",
                    details={"ip": ip, "username": username, "prior_failures": tracker.count},
                    recommendation=f"Immediately investigate: check 'last {username}', review what commands were run, consider locking the account with 'usermod -L {username}' and blocking the IP with 'firewall-cmd --add-rich-rule=\"rule family=ipv4 source address={ip} reject\" --permanent && firewall-cmd --reload'",
                ))

    async def _record_failure(self, ip: str, username: str) -> None:
        """Record a failed auth attempt and check threshold."""
        now = datetime.now()
        tracker = self._trackers.get(ip)

        if tracker is None:
            tracker = AttackTracker(ip=ip, first_seen=now)
            self._trackers[ip] = tracker

        # Reset if outside window
        if (now - tracker.first_seen).total_seconds() > self.window:
            tracker.count = 0
            tracker.first_seen = now
            tracker.usernames = set()
            tracker.alerted = False

        tracker.count += 1
        tracker.last_seen = now
        tracker.usernames.add(username)

        # Check threshold
        if tracker.count >= self.threshold and not tracker.alerted:
            tracker.alerted = True
            usernames_str = ", ".join(sorted(tracker.usernames))
            window_secs = (tracker.last_seen - tracker.first_seen).total_seconds()

            await self.dispatcher.dispatch(Alert(
                title=f"SSH brute force from {ip}",
                message=f"{tracker.count} failed login attempts from {ip} in {window_secs:.0f}s. Targeted users: {usernames_str}",
                severity=Severity.CRITICAL,
                source="ssh_monitor",
                details={
                    "ip": ip,
                    "attempts": tracker.count,
                    "window_seconds": window_secs,
                    "usernames": sorted(tracker.usernames),
                },
                recommendation=f"Block this IP: firewall-cmd --add-rich-rule='rule family=ipv4 source address={ip} reject' --permanent && firewall-cmd --reload",
            ))

    async def scan_recent(self, hours: int = 1) -> dict:
        """One-shot scan of recent SSH logs. Returns summary."""
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", "sshd", "--since", f"{hours}h ago",
            "--no-pager", "-o", "short-iso",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        failures_by_ip: dict[str, dict] = defaultdict(lambda: {"count": 0, "usernames": set()})
        total_failures = 0
        total_accepted = 0

        for line in stdout.decode("utf-8", errors="replace").splitlines():
            match = FAILED_RE.search(line)
            if match:
                username, ip, port = match.groups()
                failures_by_ip[ip]["count"] += 1
                failures_by_ip[ip]["usernames"].add(username)
                total_failures += 1

            match = ACCEPTED_RE.search(line)
            if match:
                total_accepted += 1

        # Sort by count descending
        top_offenders = sorted(
            [{"ip": ip, "count": d["count"], "usernames": sorted(d["usernames"])}
             for ip, d in failures_by_ip.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        return {
            "period_hours": hours,
            "total_failures": total_failures,
            "total_accepted": total_accepted,
            "unique_ips": len(failures_by_ip),
            "top_offenders": top_offenders[:20],
        }

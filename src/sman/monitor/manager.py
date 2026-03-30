"""Monitor manager — orchestrates all monitoring tasks."""

from __future__ import annotations

import asyncio
import logging

from sman.config import SmanConfig
from sman.alerts.dispatcher import AlertDispatcher
from sman.monitor.ssh import SSHMonitor
from sman.monitor.disk import DiskMonitor
from sman.monitor.services import ServiceMonitor
from sman.monitor.journal import JournalMonitor

log = logging.getLogger(__name__)


class MonitorManager:
    """Async orchestrator for all system monitors."""

    def __init__(self, config: SmanConfig):
        self.config = config
        self.dispatcher = AlertDispatcher(config)

        self.ssh = SSHMonitor(config, self.dispatcher)
        self.disk = DiskMonitor(config, self.dispatcher)
        self.services = ServiceMonitor(config, self.dispatcher)
        self.journal = JournalMonitor(config, self.dispatcher)

        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Start all monitors."""
        if not self.config.monitor.enabled:
            log.info("Monitoring disabled in config")
            return

        self._running = True
        log.info("Starting all monitors...")

        # Real-time streaming monitors
        self._tasks.append(asyncio.create_task(self.ssh.start(), name="ssh_monitor"))
        self._tasks.append(asyncio.create_task(self.journal.start(), name="journal_monitor"))

        # Periodic check monitors
        self._tasks.append(asyncio.create_task(
            self._periodic(self.disk.check_space, self.config.monitor.disk_check_interval, "disk_space"),
            name="disk_space_monitor",
        ))
        self._tasks.append(asyncio.create_task(
            self._periodic(self.disk.check_smart, self.config.monitor.smart_check_interval, "disk_smart"),
            name="disk_smart_monitor",
        ))
        self._tasks.append(asyncio.create_task(
            self._periodic(self.services.check, self.config.monitor.service_check_interval, "service_health"),
            name="service_monitor",
        ))

        log.info(f"Started {len(self._tasks)} monitor tasks")

    async def stop(self) -> None:
        """Stop all monitors."""
        self._running = False
        self.ssh.stop()
        self.journal.stop()

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()
        log.info("All monitors stopped")

    async def _periodic(self, check_fn, interval: int, name: str) -> None:
        """Run a check function on a periodic interval."""
        log.info(f"Periodic monitor '{name}' started (interval={interval}s)")
        # Run immediately on start
        try:
            await check_fn()
        except Exception as e:
            log.error(f"Monitor '{name}' initial check failed: {e}")

        while self._running:
            try:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                await check_fn()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Monitor '{name}' check failed: {e}")

    async def run_all_checks(self) -> dict:
        """Run all checks once and return results. For CLI/API use."""
        results = {}

        try:
            results["disk_space"] = await self.disk.check_space()
        except Exception as e:
            results["disk_space_error"] = str(e)

        try:
            results["disk_smart"] = await self.disk.check_smart()
        except Exception as e:
            results["disk_smart_error"] = str(e)

        try:
            results["services"] = await self.services.check()
        except Exception as e:
            results["services_error"] = str(e)

        try:
            results["ssh_recent"] = await self.ssh.scan_recent(hours=1)
        except Exception as e:
            results["ssh_error"] = str(e)

        results["alerts"] = self.dispatcher.get_recent_alerts(count=10)

        return results

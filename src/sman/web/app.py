"""Web UI routes for sman dashboard."""

from __future__ import annotations

import json
import platform
import subprocess

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from sman.config import SmanConfig
from sman.agent.agent import SmanAgent
from sman.monitor.manager import MonitorManager

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

router = APIRouter()


def _get_system_info() -> dict:
    """Get basic system info for the dashboard."""
    info = {"hostname": platform.node(), "os_name": "Linux", "uptime": "unknown"}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("NAME="):
                    info["os_name"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass
    try:
        result = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            info["uptime"] = result.stdout.strip().replace("up ", "")
    except Exception:
        pass
    return info


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(name="dashboard.html", context={"request": request, "page": "dashboard"})


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    return templates.TemplateResponse(name="alerts.html", context={"request": request, "page": "alerts"})


@router.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard_data(request: Request):
    """HTMX endpoint: returns dashboard content partial."""
    monitors: MonitorManager = request.app.state.monitors

    # Run all checks
    results = await monitors.run_all_checks()

    ssh = results.get("ssh_recent", {"total_failures": 0, "unique_ips": 0, "top_offenders": []})
    disks = results.get("disk_space", [])
    services = results.get("services", [])
    alerts = results.get("alerts", [])

    active_count = sum(1 for s in services if s.get("active_state") == "active")
    failed_count = sum(1 for s in services if s.get("active_state") == "failed")
    sys_info = _get_system_info()

    return templates.TemplateResponse(name="partials/dashboard_content.html", context={
        "request": request,
        "ssh": ssh,
        "disks": disks,
        "services": services,
        "alerts": alerts,
        "active_count": active_count,
        "failed_count": failed_count,
        "total_services": len(services),
        "hostname": sys_info["hostname"],
        "os_name": sys_info["os_name"],
        "uptime": sys_info["uptime"],
    })


@router.get("/api/alerts", response_class=HTMLResponse)
async def alerts_data(request: Request):
    """HTMX endpoint: returns alert list partial."""
    monitors: MonitorManager = request.app.state.monitors
    alerts = monitors.dispatcher.get_recent_alerts(count=50)

    return templates.TemplateResponse(name="partials/alert_list.html", context={
        "request": request,
        "alerts": alerts,
    })


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket chat with command display."""
    await websocket.accept()

    config: SmanConfig = websocket.app.state.config
    agent = SmanAgent(config)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_input = msg.get("message", "")

            if not user_input:
                continue

            async for chunk in agent.ask(user_input):
                await websocket.send_json({"type": "chunk", "content": chunk})

            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass

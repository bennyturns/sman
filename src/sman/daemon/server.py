"""sman daemon server - FastAPI on Unix socket + TCP."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sman.config import load_config, SmanConfig
from sman.agent.agent import SmanAgent
from sman.monitor.manager import MonitorManager


class AskRequest(BaseModel):
    message: str
    force_route: str | None = None


class AskResponse(BaseModel):
    response: str
    route: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    config_path = os.environ.get("SMAN_CONFIG")
    config = load_config(Path(config_path) if config_path else None)

    app.state.config = config
    app.state.agent = SmanAgent(config)
    app.state.monitors = MonitorManager(config)

    await app.state.monitors.start()

    yield

    await app.state.monitors.stop()


app = FastAPI(
    title="sman daemon",
    description="AI-powered sysadmin agent",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
static_dir = Path(__file__).parent.parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount web UI routes
from sman.web.app import router as web_router
app.include_router(web_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    """System status overview."""
    agent = app.state.agent
    result = await agent.diagnostics.system_overview()
    failed = await agent.diagnostics.failed_services()

    return {
        "system": result.stdout,
        "failed_services": failed.stdout if "0 loaded" not in failed.stdout else None,
    }


@app.get("/api/monitors")
async def monitors():
    """Run all monitor checks and return results."""
    results = await app.state.monitors.run_all_checks()
    return results


@app.post("/api/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """One-shot request to the agent."""
    agent = SmanAgent(app.state.config)
    response = await agent.ask_oneshot(request.message, force_route=request.force_route)
    return AskResponse(response=response)


@app.websocket("/api/chat")
async def chat(websocket: WebSocket):
    """WebSocket chat session with the agent."""
    await websocket.accept()

    agent = SmanAgent(app.state.config)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_input = msg.get("message", "")

            if not user_input:
                continue

            async for chunk in agent.ask(user_input, force_route=msg.get("force_route")):
                await websocket.send_json({"type": "chunk", "content": chunk})

            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


def main():
    """Run the daemon server."""
    config_path = os.environ.get("SMAN_CONFIG")
    config = load_config(Path(config_path) if config_path else None)

    uvicorn.run(
        "sman.daemon.server:app",
        host=config.daemon.host,
        port=config.daemon.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

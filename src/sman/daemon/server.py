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
from pydantic import BaseModel

from sman.config import load_config, SmanConfig
from sman.agent.agent import SmanAgent


class AskRequest(BaseModel):
    message: str
    force_route: str | None = None


class AskResponse(BaseModel):
    response: str
    route: str | None = None


# Global state
_config: SmanConfig | None = None
_agent: SmanAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global _config, _agent

    config_path = os.environ.get("SMAN_CONFIG")
    _config = load_config(Path(config_path) if config_path else None)
    _agent = SmanAgent(_config)

    yield

    _agent = None
    _config = None


app = FastAPI(
    title="sman daemon",
    description="AI-powered sysadmin agent",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def status():
    """System status overview."""
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not initialized"})

    result = await _agent.diagnostics.system_overview()
    failed = await _agent.diagnostics.failed_services()

    return {
        "system": result.stdout,
        "failed_services": failed.stdout if "0 loaded" not in failed.stdout else None,
    }


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """One-shot request to the agent."""
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not initialized"})

    # Create a fresh agent for one-shot requests (no shared history)
    agent = SmanAgent(_config)
    response = await agent.ask_oneshot(request.message, force_route=request.force_route)

    return AskResponse(response=response)


@app.websocket("/chat")
async def chat(websocket: WebSocket):
    """WebSocket chat session with the agent."""
    await websocket.accept()

    if not _config:
        await websocket.send_json({"error": "Agent not initialized"})
        await websocket.close()
        return

    # Each websocket connection gets its own agent with conversation history
    agent = SmanAgent(_config)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_input = msg.get("message", "")

            if not user_input:
                continue

            # Stream response chunks
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

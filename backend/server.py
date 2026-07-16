from __future__ import annotations

import asyncio
import os

import uvicorn

from .main import app


async def serve() -> None:
    config = uvicorn.Config(
        app,
        host=os.getenv("AGENT_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENT_PORT", "0")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.01)
    if task.done():
        await task
        return
    sockets = next(iter(server.servers)).sockets if server.servers else []
    if not sockets:
        raise RuntimeError("后端未创建监听端口。")
    port = sockets[0].getsockname()[1]
    print(f"AI_WORKBENCH_BACKEND_READY={port}", flush=True)
    await task


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()

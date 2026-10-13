"""
WebSocket endpoints:
    /ws          -- stats + job updates (publisher loop in create_app)
    /ws/logs     -- live tail
    /ws/console  -- interactive command execution
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from lib.auth import PERM_LOGS_VIEW, PERM_CONSOLE_USE
from lib.webui.console_session import ConsoleSession
from lib.webui.deps import WebUIState
from lib.webui.ws import get_hub


def build_router(state: WebUIState) -> APIRouter:
    router = APIRouter()
    hub = get_hub()

    # ─────────── /ws ───────────

    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        user = state.user_from_ws(websocket)
        if not user:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        if not user.has_perm(PERM_LOGS_VIEW):
            await websocket.close(code=4403, reason="Forbidden")
            return

        await hub.subscribe(websocket)
        try:
            storage = state.get_storage()
            try:
                stats = storage.stats()
            finally:
                storage.close()
            await websocket.send_json({"type": "stats.updated", "stats": stats})
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unsubscribe(websocket)

    # ─────────── /ws/logs ───────────

    @router.websocket("/ws/logs")
    async def ws_logs(websocket: WebSocket,
                      command: str,
                      date_: Optional[str] = None):
        user = state.user_from_ws(websocket)
        if not user:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        if not user.has_perm(PERM_LOGS_VIEW):
            await websocket.close(code=4403, reason="Forbidden")
            return

        await websocket.accept()
        target_date = date_ or date.today().isoformat()
        reader = state.logs_reader

        try:
            for e in reader.read(command, target_date, limit=200):
                await websocket.send_json({
                    "ts": e.ts.isoformat() if e.ts else None,
                    "level": e.level,
                    "message": e.message,
                })

            path = reader.logs_dir / command / f"{target_date}.log"
            offset = path.stat().st_size if path.exists() else 0

            while True:
                await asyncio.sleep(0.5)
                today = date.today().isoformat()
                if today != target_date:
                    target_date = today
                    offset = 0
                new_offset, lines = reader.tail_lines(command, target_date, offset)
                if new_offset != offset:
                    offset = new_offset
                    for line in lines:
                        entry = reader._parse_line(line, command)
                        if entry:
                            await websocket.send_json({
                                "ts": entry.ts.isoformat() if entry.ts else None,
                                "level": entry.level,
                                "message": entry.message,
                            })
        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({"error": str(e)})
            except Exception:
                pass

    # ─────────── /ws/console ───────────

    @router.websocket("/ws/console")
    async def ws_console(websocket: WebSocket):
        user = state.user_from_ws(websocket)
        if not user:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        if not user.has_perm(PERM_CONSOLE_USE):
            await websocket.close(code=4403, reason="Forbidden")
            return

        await websocket.accept()
        try:
            init = await websocket.receive_json()
        except Exception:
            await websocket.close(code=4400, reason="JSON message expected")
            return

        command = init.get("command")
        args = init.get("args") or {}
        if not command:
            await websocket.send_json({"type": "error", "message": "command is required"})
            await websocket.close()
            return

        allow = state.config.get("webui.console.allow_commands") or []
        if allow and command not in allow:
            await websocket.send_json({"type": "error", "message": "Command not allowed"})
            await websocket.close()
            return

        cmd_logger = state.logger
        if cmd_logger is None:
            from lib.logger import Logger
            cmd_logger = Logger(state.config, state.root_dir)

        session = ConsoleSession(
            context={
                "config": state.config,
                "logger": cmd_logger,
                "root_dir": state.root_dir,
            },
            command=command,
            args=args,
            history=state.get_history(),
            user=user.username,
            client_ip=websocket.client.host if websocket.client else None,
            user_agent=websocket.headers.get("user-agent"),
            session_id=init.get("history_id") or str(uuid.uuid4()),
        )
        session.start()

        async def pump_output():
            while session.is_alive or not session._messages.empty():
                msg = session.get_message(timeout=0.2)
                if msg is None:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    await websocket.send_json(msg)
                except Exception:
                    return

        pump_task = asyncio.create_task(pump_output())
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                except WebSocketDisconnect:
                    break
                except Exception:
                    continue
                t = data.get("type")
                if t == "input_response":
                    session.send_input(data.get("id", ""), data.get("value", ""))
                elif t == "signal" and data.get("signal") == "SIGINT":
                    session.stop()
        except WebSocketDisconnect:
            pass
        finally:
            session.stop()
            pump_task.cancel()

    return router

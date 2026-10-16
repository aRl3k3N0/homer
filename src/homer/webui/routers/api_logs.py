"""
Logs API: list, download, bundle.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from homer.auth import PERM_LOGS_VIEW, PERM_LOGS_DOWNLOAD
from homer.webui.deps import Dependencies, WebUIState


def build_router(state: WebUIState, deps: Dependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/logs/files",
                dependencies=[Depends(deps.require_perm(PERM_LOGS_VIEW))])
    def api_logs_files():
        reader = deps.get_logs_reader()
        return [
            {"command": f.command, "date": f.date.isoformat(), "size": f.size}
            for f in reader.list_files()
        ]

    @router.get("/api/logs",
                dependencies=[Depends(deps.require_perm(PERM_LOGS_VIEW))])
    def api_logs(command: str, date_: str,
                 level: Optional[str] = None,
                 grep: Optional[str] = None,
                 limit: int = 500):
        reader = deps.get_logs_reader()
        entries = reader.read(command, date_, level=level, grep=grep, limit=limit)
        return [
            {
                "ts": e.ts.isoformat() if e.ts else None,
                "level": e.level,
                "command": e.command,
                "message": e.message,
                "extra": e.extra,
            }
            for e in entries
        ]

    @router.get("/api/logs/download",
                dependencies=[Depends(deps.require_perm(PERM_LOGS_DOWNLOAD))])
    def download_logs(
        command: str,
        date_: str,
        level: Optional[str] = None,
        grep: Optional[str] = None,
        format: str = "log",
    ):
        reader = deps.get_logs_reader()
        entries = reader.read(command, date_, level=level, grep=grep,
                              limit=10_000_000, tail=False)

        base = f"{command}_{date_}"
        if level:
            base += f"_{level}"
        if grep:
            base += "_filtered"

        if format == "log":
            path = reader.logs_dir / f"{command}_{date_}.log"
            if not path.exists():
                raise HTTPException(404, "Log file not found")
            return FileResponse(
                str(path),
                media_type="text/plain; charset=utf-8",
                filename=f"{base}.log",
            )

        rows = [
            {
                "ts": e.ts.isoformat() if e.ts else None,
                "level": e.level,
                "command": e.command,
                "message": e.message,
                "extra": e.extra,
            }
            for e in entries
        ]

        if format == "json":
            body = json.dumps(rows, ensure_ascii=False, indent=2)
            return Response(
                body,
                media_type="application/json; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{base}.json"'},
            )

        if format == "jsonl":
            buf = io.StringIO()
            for r in rows:
                buf.write(json.dumps(r, ensure_ascii=False) + "\n")
            return Response(
                buf.getvalue(),
                media_type="application/x-ndjson; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{base}.jsonl"'},
            )

        if format == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["ts", "level", "command", "message"])
            for r in rows:
                w.writerow([r["ts"], r["level"], r["command"], r["message"]])
            return Response(
                buf.getvalue(),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{base}.csv"'},
            )

        raise HTTPException(400, "format: log|json|jsonl|csv")

    @router.get("/api/logs/bundle",
                dependencies=[Depends(deps.require_perm(PERM_LOGS_DOWNLOAD))])
    def download_logs_bundle(date_: str,
                             command: Optional[str] = None,
                             format: str = "log"):
        reader = deps.get_logs_reader()
        files = [f for f in reader.list_files()
                 if f.date.isoformat() == date_]
        if command:
            files = [f for f in files if f.command == command]
        if not files:
            raise HTTPException(404, "No files to export")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if format == "log":
                    zf.write(f.path, arcname=f.path.name)
                else:
                    entries = reader.read(f.command, f.date, tail=False)
                    data = json.dumps(
                        [
                            {
                                "ts": e.ts.isoformat() if e.ts else None,
                                "level": e.level,
                                "message": e.message,
                            }
                            for e in entries
                        ],
                        ensure_ascii=False, indent=2,
                    )
                    zf.writestr(
                        f"{f.command}_{f.date.isoformat()}.json", data,
                    )

        buf.seek(0)
        name = f"homer-logs_{date_}"
        if command:
            name += f"_{command}"
        return StreamingResponse(
            buf, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
        )

    return router

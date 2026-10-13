"""
Job-related API: /api/stats, /api/jobs, /api/jobs/{id},
plus form actions: /jobs/{id}/cancel, /jobs/{id}/retry, /jobs/purge.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FPath, Query
from fastapi.responses import JSONResponse, RedirectResponse

from lib.auth import (
    PERM_JOBS_VIEW, PERM_JOBS_CANCEL, PERM_JOBS_RETRY, PERM_JOBS_PURGE,
)
from lib.queue.models import JobStatus
from lib.webui.deps import Dependencies, WebUIState, job_to_dict
from lib.webui.schemas import (
    ErrorResponse, JobSchema, PurgeResponse, StatsSchema,
)


def build_router(state: WebUIState, deps: Dependencies) -> APIRouter:
    router = APIRouter()

    # ─────────── Stats ───────────

    @router.get("/api/stats", response_model=StatsSchema, tags=["stats"],
                summary="Queue statistics",
                dependencies=[Depends(deps.require_perm(PERM_JOBS_VIEW))])
    def api_stats():
        storage = deps.get_storage()
        try:
            return storage.stats()
        finally:
            storage.close()

    # ─────────── Jobs ───────────

    @router.get("/api/jobs", response_model=list[JobSchema], tags=["jobs"],
                summary="List jobs",
                dependencies=[Depends(deps.require_perm(PERM_JOBS_VIEW))])
    def api_jobs(
        status: Optional[str] = Query(
            None,
            description="Filter by status",
            pattern="^(pending|running|done|failed|canceled|timeout)$",
        ),
        limit: int = Query(100, ge=1, le=1000),
    ):
        storage = deps.get_storage()
        try:
            jobs = storage.list(status=status, limit=limit)
            return [job_to_dict(j) for j in jobs]
        finally:
            storage.close()

    @router.get(
        "/api/jobs/{job_id}",
        response_model=JobSchema,
        tags=["jobs"],
        summary="Job detail",
        responses={404: {"model": ErrorResponse, "description": "Not found"}},
        dependencies=[Depends(deps.require_perm(PERM_JOBS_VIEW))],
    )
    def api_job(job_id: int = FPath(..., ge=1)):
        storage = deps.get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            return job_to_dict(job)
        finally:
            storage.close()

    # ─────────── Cancel ───────────

    @router.post(
        "/api/jobs/{job_id}/cancel",
        response_model=JobSchema,
        tags=["actions"],
        summary="Cancel job",
        dependencies=[Depends(deps.require_perm(PERM_JOBS_CANCEL))],
    )
    def api_cancel(
        job_id: int = FPath(..., ge=1),
        cascade: bool = Query(True),
    ):
        storage = deps.get_storage()
        try:
            n = storage.cancel(job_id, cascade=cascade)
            if n == 0:
                raise HTTPException(400, "Cannot cancel")
            return job_to_dict(storage.get(job_id))
        finally:
            storage.close()

    @router.post("/jobs/{job_id}/cancel",
                 dependencies=[Depends(deps.require_perm(PERM_JOBS_CANCEL))])
    def form_cancel(job_id: int, cascade: bool = True):
        storage = deps.get_storage()
        try:
            n = storage.cancel(job_id, cascade=cascade)
            if n == 0:
                raise HTTPException(400, "Cannot cancel")
            return RedirectResponse(f"/jobs/{job_id}", status_code=303)
        finally:
            storage.close()

    # ─────────── Retry ───────────

    @router.post(
        "/api/jobs/{job_id}/retry",
        response_model=JobSchema,
        tags=["actions"],
        summary="Retry job",
        dependencies=[Depends(deps.require_perm(PERM_JOBS_RETRY))],
    )
    def api_retry(job_id: int = FPath(..., ge=1)):
        storage = deps.get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            if job.status not in (
                JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELED
            ):
                raise HTTPException(400, f"Job in status {job.status}")
            storage.retry(job_id)
            return job_to_dict(storage.get(job_id))
        finally:
            storage.close()

    @router.post("/jobs/{job_id}/retry",
                 dependencies=[Depends(deps.require_perm(PERM_JOBS_RETRY))])
    def form_retry(job_id: int):
        storage = deps.get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(404)
            if job.status not in (
                JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELED
            ):
                raise HTTPException(400, f"Job in status {job.status}")
            storage.retry(job_id)
            return RedirectResponse(f"/jobs/{job_id}", status_code=303)
        finally:
            storage.close()

    # ─────────── Purge ───────────

    @router.post(
        "/api/jobs/purge",
        response_model=PurgeResponse,
        tags=["actions"],
        summary="Purge finished jobs",
        dependencies=[Depends(deps.require_perm(PERM_JOBS_PURGE))],
    )
    def api_purge(older: int = Query(86400, ge=0)):
        storage = deps.get_storage()
        try:
            return {"purged": storage.purge(older_than_seconds=older)}
        finally:
            storage.close()

    @router.post("/jobs/purge",
                 dependencies=[Depends(deps.require_perm(PERM_JOBS_PURGE))])
    def form_purge(older: int = 86400):
        storage = deps.get_storage()
        try:
            return JSONResponse(
                {"purged": storage.purge(older_than_seconds=older)}
            )
        finally:
            storage.close()

    return router

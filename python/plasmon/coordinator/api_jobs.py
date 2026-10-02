"""Jobs: create, list, inspect, cancel, download the latest weights."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.jobspec import JobSpec
from . import auth, db
from .deps import Principal, current_user, get_session, get_state, principal_optional
from .engine import EngineError, recent_trainers, waiting_reason

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


class ShardIn(BaseModel):
    index: int
    blob: str = Field(min_length=64, max_length=64)
    n: int


class JobCreate(BaseModel):
    spec: dict[str, Any]
    init_blob: str = Field(min_length=64, max_length=64)
    eval_blob: str = Field(min_length=64, max_length=64)
    shards: list[ShardIn]
    param_count: int = 0


def job_out(job: db.Job, rounds: list[db.Round] | None = None, session: Session | None = None, show_names: bool = True) -> dict[str, Any]:
    out = {
        "id": job.id,
        "name": job.name,
        "owner": job.owner.email if job.owner else job.owner_id,
        "status": job.status,
        "status_detail": job.status_detail,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "round": job.round_index,
        "total_rounds": job.total_rounds,
        "theta": job.theta_blob,
        "param_count": job.param_count,
        "eval_loss": job.last_eval_loss,
        "eval_acc": job.last_eval_acc,
        "credits_spent": job.credits_spent,
        "shards": len(job.shards),
        "spec": job.spec,
    }
    if rounds is not None:
        out["rounds"] = [round_out(r) for r in rounds]
    if session is not None:
        out["waiting_reason"] = waiting_reason(session, job)
        out["trainers"] = recent_trainers(session, job, show_names)
    return out


def round_out(r: db.Round) -> dict[str, Any]:
    return {
        "index": r.index,
        "status": r.status,
        "theta": r.theta_blob,
        "opened_at": r.opened_at,
        "deadline_at": r.deadline_at,
        "closed_at": r.closed_at,
        "accepted": r.accepted,
        "eval_loss": r.eval_loss,
        "eval_acc": r.eval_acc,
        "mean_loss_end": r.mean_loss_end,
        "bytes_in": r.bytes_in,
        "timings": r.timings,
    }


def _visible(job: db.Job, user: db.User) -> bool:
    return job.owner_id == user.id or auth.role_at_least(user.role, "operator")


@router.post("")
def create(body: JobCreate, user: db.User = Depends(current_user), session: Session = Depends(get_session), state=Depends(get_state)):
    if "jobs:write" not in auth.ROLE_SCOPES[user.role]:
        raise HTTPException(403, "your role cannot submit jobs")
    try:
        spec = JobSpec.model_validate(body.spec)
    except ValueError as e:
        raise HTTPException(422, f"invalid job spec: {e}") from e
    try:
        job = state.engine.create_job(session, user, spec, body.init_blob, [s.model_dump() for s in body.shards], body.eval_blob, body.param_count)
    except EngineError as e:
        raise HTTPException(e.status, str(e)) from e
    return job_out(job, session=session)


@router.get("")
def list_jobs(all: bool = False, user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    q = select(db.Job).order_by(db.Job.created_at.desc())
    if not (all and auth.role_at_least(user.role, "operator")):
        q = q.where(db.Job.owner_id == user.id)
    show_names = auth.role_at_least(user.role, "operator")
    return [job_out(j, session=session, show_names=show_names) for j in session.scalars(q).all()]


@router.get("/{job_id}")
def get_job(job_id: str, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    job = session.get(db.Job, job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    if p.user is None and p.machine is None:
        raise HTTPException(401, "login required")
    if p.user is not None and not _visible(job, p.user):
        raise HTTPException(403, "not your job")
    rounds = session.scalars(select(db.Round).where(db.Round.job_id == job.id).order_by(db.Round.index)).all()
    return job_out(job, rounds, session=session, show_names=p.user is not None and auth.role_at_least(p.user.role, "operator"))


@router.get("/{job_id}/updates")
def list_updates(job_id: str, round: int | None = None, user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    job = session.get(db.Job, job_id)
    if job is None or not _visible(job, user):
        raise HTTPException(404, "no such job")
    q = select(db.Update).where(db.Update.job_id == job.id).order_by(db.Update.round_index.desc(), db.Update.id)
    if round is not None:
        q = q.where(db.Update.round_index == round)
    show_names = auth.role_at_least(user.role, "operator")
    return [
        {
            "round": u.round_index,
            "machine": u.machine.name if show_names else u.machine.node_id[:8],
            "node": u.machine.node_id if show_names else u.machine.node_id[:8],
            "shard": u.shard_index,
            "status": u.status,
            "samples": u.samples,
            "loss_start": u.loss_start,
            "loss_end": u.loss_end,
            "frame_bytes": u.frame_bytes,
            "score": u.score,
            "gain_assigned": u.gain_assigned,
            "gain_random": u.gain_random,
            "reject_reason": u.reject_reason,
        }
        for u in session.scalars(q).all()
    ]


@router.post("/{job_id}/cancel")
def cancel(job_id: str, user: db.User = Depends(current_user), session: Session = Depends(get_session), state=Depends(get_state)):
    job = session.get(db.Job, job_id)
    if job is None or not _visible(job, user):
        raise HTTPException(404, "no such job")
    try:
        state.engine.cancel_job(session, job)
    except EngineError as e:
        raise HTTPException(e.status, str(e)) from e
    session.add(db.AuditEvent(actor_id=user.id, action="job.cancel", target=job.id))
    session.commit()
    return job_out(job, session=session)

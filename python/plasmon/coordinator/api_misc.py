"""Blobs, fleet, events (SSE), server status and ledger."""

from __future__ import annotations

import datetime as dt
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..core import hashing
from . import auth, db, ledger
from .api_machines import machine_out
from .blobs import BlobError
from .deps import Principal, current_user, get_session, get_state, principal_optional, require_role

router = APIRouter(prefix="/v1", tags=["misc"])

MAX_BLOB = 2 * 1024 * 1024 * 1024


@router.put("/blobs/{blob_id}")
async def put_blob(blob_id: str, request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session), state=Depends(get_state)):
    if p.user is None and p.machine is None:
        raise HTTPException(401, "login required")
    if not hashing.is_digest(blob_id):
        raise HTTPException(400, "bad blob id")
    if state.blobs.exists(blob_id):
        return {"id": blob_id, "size": state.blobs.size(blob_id), "existed": True}
    data = await request.body()
    if len(data) > MAX_BLOB:
        raise HTTPException(413, "blob too large")
    try:
        state.blobs.put(data, expected_id=blob_id)
    except BlobError as e:
        raise HTTPException(400, str(e)) from e
    if session.get(db.Blob, blob_id) is None:
        session.add(db.Blob(id=blob_id, size=len(data), kind=request.headers.get("x-plasmon-kind", "")))
        session.commit()
    return {"id": blob_id, "size": len(data), "existed": False}


@router.head("/blobs/{blob_id}")
def head_blob(blob_id: str, p: Principal = Depends(principal_optional), state=Depends(get_state)):
    if p.user is None and p.machine is None:
        raise HTTPException(401, "login required")
    if not hashing.is_digest(blob_id) or not state.blobs.exists(blob_id):
        raise HTTPException(404, "no such blob")
    return Response(headers={"content-length": str(state.blobs.size(blob_id))})


@router.get("/blobs/{blob_id}")
def get_blob(blob_id: str, p: Principal = Depends(principal_optional), state=Depends(get_state)):
    if p.user is None and p.machine is None:
        raise HTTPException(401, "login required")
    if not hashing.is_digest(blob_id) or not state.blobs.exists(blob_id):
        raise HTTPException(404, "no such blob")
    return Response(content=state.blobs.get(blob_id), media_type="application/octet-stream")


@router.post("/blobs/check")
def check_blobs(body: dict[str, list[str]], p: Principal = Depends(principal_optional), state=Depends(get_state)):
    if p.user is None and p.machine is None:
        raise HTTPException(401, "login required")
    ids = body.get("ids", [])
    return {"missing": [i for i in ids if not (hashing.is_digest(i) and state.blobs.exists(i))]}


# ----- fleet -------------------------------------------------------------------------

@router.get("/fleet/summary")
def fleet_summary(p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    counts = dict(session.execute(select(db.Machine.status, func.count()).group_by(db.Machine.status)).all())
    running = session.scalar(select(func.count()).select_from(db.Job).where(db.Job.status == "running"))
    since = db.now() - dt.timedelta(hours=1)
    rounds_last_hour = session.scalar(select(func.count()).select_from(db.Round).where(db.Round.status == "closed", db.Round.closed_at >= since))
    total = sum(counts.values())
    return {
        "machines": total,
        "online": total - counts.get("offline", 0),
        "by_status": counts,
        "jobs_running": running,
        "rounds_last_hour": rounds_last_hour,
    }


@router.get("/fleet")
def fleet(status: str | None = None, user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    q = select(db.Machine).order_by(db.Machine.status, db.Machine.name)
    if not auth.role_at_least(user.role, "operator"):
        q = q.where(db.Machine.user_id == user.id)  # members see their own machines
    if status:
        q = q.where(db.Machine.status == status)
    return [machine_out(m) for m in session.scalars(q).all()]


@router.get("/fleet/{node_id}")
def fleet_machine(node_id: str, user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    m = session.scalar(select(db.Machine).where(db.Machine.node_id == node_id))
    if m is None or (m.user_id != user.id and not auth.role_at_least(user.role, "operator")):
        raise HTTPException(404, "no such machine")
    since = db.now() - dt.timedelta(hours=1)
    history = session.scalars(select(db.Heartbeat).where(db.Heartbeat.machine_id == m.id, db.Heartbeat.at >= since).order_by(db.Heartbeat.at)).all()
    return {**machine_out(m), "history": [{"at": h.at, "status": h.status, "metrics": h.metrics} for h in history]}


@router.get("/leaderboard")
def leaderboard(limit: int = 20, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    """Machines by verified samples. Names are visible to everyone who can log in."""
    if p.user is None:
        raise HTTPException(401, "login required")
    from . import credits

    rows = session.scalars(select(db.Machine).where(db.Machine.samples_verified > 0).order_by(db.Machine.samples_verified.desc()).limit(min(limit, 100))).all()
    earned = credits.earned_by_machine(session)
    return [
        {"rank": i + 1, "name": m.name, "node_id": m.node_id[:8], "owner": m.user.email if m.user else None, "samples_verified": m.samples_verified, "rounds_served": m.rounds_served, "honesty": m.honesty, "status": m.status, "credits_earned": earned.get(m.id, 0)}
        for i, m in enumerate(rows)
    ]


# ----- events (SSE) ------------------------------------------------------------------

@router.get("/events")
async def events(request: Request, topics: str = "", p: Principal = Depends(principal_optional), state=Depends(get_state)):
    if p.user is None and p.machine is None:
        raise HTTPException(401, "login required")
    wanted = {t for t in topics.split(",") if t}
    if p.user is not None and not auth.role_at_least(p.user.role, "operator"):
        wanted = {t for t in wanted if not t.startswith("logs:")} or {"jobs"}

    async def stream():
        sub = state.bus.subscribe(wanted)
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                ev = await sub.get(timeout=15)
                yield ev.sse() if ev else ": keepalive\n\n"
        finally:
            sub.close()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


# ----- server and ledger -------------------------------------------------------------

@router.get("/server/status")
def server_status(user: db.User = Depends(require_role("operator")), session: Session = Depends(get_session), state=Depends(get_state)):
    t0 = time.perf_counter()
    session.execute(select(func.count()).select_from(db.User))
    db_ms = (time.perf_counter() - t0) * 1000
    last = session.scalar(select(db.LedgerEntry).order_by(db.LedgerEntry.seq.desc()).limit(1))
    recent = session.scalars(select(db.Round).where(db.Round.status == "closed").order_by(db.Round.closed_at.desc()).limit(20)).all()
    return {
        "version": __version__,
        "mode": state.cfg.mode,
        "started_at": state.started_at,
        "uptime_s": int(time.time() - state.started_ts),
        "db": {"url": _redact(state.cfg.resolved_db_url()), "ping_ms": round(db_ms, 2)},
        "blobs": {"path": str(state.blobs.root), "bytes": state.blobs.total_bytes()},
        "scheduler": {"running": state.scheduler is not None and state.scheduler.is_alive(), "interval_s": state.cfg.tick_interval_s},
        "sse_clients": len(state.bus._subs),
        "ledger": {"entries": last.seq if last else 0, "head": last.hash if last else ledger.GENESIS},
        "round_timings": [{"job": r.job_id, "round": r.index, **r.timings} for r in recent],
        "counts": {
            "users": session.scalar(select(func.count()).select_from(db.User)),
            "machines": session.scalar(select(func.count()).select_from(db.Machine)),
            "jobs": session.scalar(select(func.count()).select_from(db.Job)),
            "jobs_running": session.scalar(select(func.count()).select_from(db.Job).where(db.Job.status == "running")),
        },
    }


def _redact(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url


@router.get("/ledger")
def ledger_list(job: str | None = None, limit: int = 100, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    if p.user is None:
        raise HTTPException(401, "login required")
    q = select(db.LedgerEntry).order_by(db.LedgerEntry.seq.desc()).limit(min(limit, 1000))
    entries = session.scalars(q).all()
    if job:
        entries = [e for e in entries if e.body.get("job") == job]
    return [{"seq": e.seq, "at": e.at, "kind": e.kind, "body": e.body, "prev_hash": e.prev_hash, "hash": e.hash, "signature": e.signature} for e in entries]


@router.get("/ledger/verify")
def ledger_verify(p: Principal = Depends(principal_optional), session: Session = Depends(get_session), state=Depends(get_state)):
    if p.user is None:
        raise HTTPException(401, "login required")
    ok, count, problem = ledger.verify(session, state.server.node_id)
    return {"ok": ok, "entries": count, "problem": problem, "server_node_id": state.server.node_id}


@router.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


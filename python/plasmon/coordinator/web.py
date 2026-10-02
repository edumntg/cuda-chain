"""HTML pages. Server-rendered Jinja2 with HTMX partials polled every few seconds."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from . import api_auth, auth, db, ledger
from .deps import Principal, get_session, get_state, principal_optional

router = APIRouter(include_in_schema=False)


def install_filters(templates: Jinja2Templates) -> None:
    templates.env.filters["ago"] = ago
    templates.env.filters["bytes"] = fmt_bytes
    templates.env.filters["pct"] = lambda v: "" if v is None else f"{100 * v:.1f} %"
    templates.env.filters["num"] = lambda v: "" if v is None else f"{v:,}"
    templates.env.filters["f3"] = lambda v: "" if v is None else f"{v:.3f}"
    templates.env.globals["role_at_least"] = auth.role_at_least
    templates.env.globals["version"] = __version__


def ago(value: dt.datetime | None) -> str:
    if value is None:
        return "never"
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    s = int((db.now() - value).total_seconds())
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} d"


def fmt_bytes(n: int | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def render(request: Request, name: str, p: Principal, **ctx):
    state = request.app.state.plasmon
    return state.templates.TemplateResponse(request, name, {"user": p.user, "org": state.cfg.org_name, "mode": state.cfg.mode, **ctx})


def need_user(p: Principal) -> db.User:
    if p.user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return p.user


# ----- auth pages ----------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", p: Principal = Depends(principal_optional), state=Depends(get_state)):
    if p.user:
        return RedirectResponse(next, status_code=303)
    return render(request, "login.html", p, next=next, error=None, open_registration=state.cfg.auth.open_registration)


@router.post("/login")
def login_submit(request: Request, email: str = Form(), password: str = Form(), next: str = Form("/"), session: Session = Depends(get_session), state=Depends(get_state)):
    user = session.scalar(select(db.User).where(db.User.email == email.lower().strip()))
    if user is None or user.disabled or not auth.verify_password(user.password_hash, password):
        return render(request, "login.html", Principal(), next=next, error="Wrong email or password.", open_registration=state.cfg.auth.open_registration)
    resp = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    state.sessions.write(resp, user.id, secure=request.url.scheme == "https")
    return resp


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, p: Principal = Depends(principal_optional), state=Depends(get_state), session: Session = Depends(get_session)):
    first = session.scalar(select(func.count()).select_from(db.User)) == 0
    if not first and not state.cfg.auth.open_registration:
        return render(request, "register.html", p, error="Registration is closed. Ask an admin for an invite.", closed=True, first=False)
    return render(request, "register.html", p, error=None, closed=False, first=first)


@router.post("/register")
def register_submit(request: Request, email: str = Form(), password: str = Form(), name: str = Form(""), session: Session = Depends(get_session), state=Depends(get_state)):
    try:
        user = api_auth.register_user(session, state, email, password, name)
    except HTTPException as e:
        return render(request, "register.html", Principal(), error=e.detail, closed=False, first=False)
    resp = RedirectResponse("/", status_code=303)
    state.sessions.write(resp, user.id, secure=request.url.scheme == "https")
    return resp


@router.post("/logout")
def logout(state=Depends(get_state)):
    resp = RedirectResponse("/login", status_code=303)
    state.sessions.clear(resp)
    return resp


@router.get("/device", response_class=HTMLResponse)
def device_page(request: Request, code: str = "", p: Principal = Depends(principal_optional)):
    if p.user is None:
        return RedirectResponse(f"/login?next=/device%3Fcode%3D{code}", status_code=303)
    return render(request, "device.html", p, code=code, result=None)


@router.post("/device", response_class=HTMLResponse)
def device_submit(request: Request, code: str = Form(), p: Principal = Depends(principal_optional), session: Session = Depends(get_session), state=Depends(get_state)):
    user = need_user(p)
    try:
        out = api_auth.device_confirm(api_auth.DeviceConfirm(user_code=code), user, session, state)
        result = {"ok": True, "label": out["label"]}
    except HTTPException as e:
        result = {"ok": False, "error": e.detail}
    return render(request, "device.html", p, code=code, result=result)


# ----- dashboard pages -----------------------------------------------------------

def _summary(session: Session) -> dict:
    counts = dict(session.execute(select(db.Machine.status, func.count()).group_by(db.Machine.status)).all())
    total = sum(counts.values())
    since = db.now() - dt.timedelta(hours=1)
    return {
        "machines": total,
        "online": total - counts.get("offline", 0),
        "training": counts.get("training", 0),
        "idle": counts.get("idle", 0),
        "paused": counts.get("paused", 0),
        "unavailable": counts.get("unavailable", 0),
        "offline": counts.get("offline", 0),
        "error": counts.get("error", 0),
        "jobs_running": session.scalar(select(func.count()).select_from(db.Job).where(db.Job.status == "running")),
        "rounds_last_hour": session.scalar(select(func.count()).select_from(db.Round).where(db.Round.status == "closed", db.Round.closed_at >= since)),
    }


@router.get("/", response_class=HTMLResponse)
def overview(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    active = session.scalars(select(db.Job).where(db.Job.status == "running").order_by(db.Job.created_at.desc()).limit(6)).all()
    recent = session.scalars(select(db.Job).where(db.Job.status != "running").order_by(db.Job.finished_at.desc()).limit(5)).all()
    mine = session.scalars(select(db.Machine).where(db.Machine.user_id == user.id)).all()
    last = session.scalar(select(db.LedgerEntry).order_by(db.LedgerEntry.seq.desc()).limit(1))
    return render(request, "overview.html", p, summary=_summary(session), active_jobs=active, recent=recent, mine=mine, last=last)


@router.get("/partials/overview", response_class=HTMLResponse)
def overview_partial(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    need_user(p)
    active = session.scalars(select(db.Job).where(db.Job.status == "running").order_by(db.Job.created_at.desc()).limit(6)).all()
    return render(request, "partials/overview_stats.html", p, summary=_summary(session), active_jobs=active)


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    return render(request, "jobs.html", p, jobs=_jobs_for(session, user), can_see_all=auth.role_at_least(user.role, "operator"))


def _jobs_for(session: Session, user: db.User) -> list[db.Job]:
    q = select(db.Job).order_by(db.Job.created_at.desc())
    if not auth.role_at_least(user.role, "operator"):
        q = q.where(db.Job.owner_id == user.id)
    return session.scalars(q).all()


@router.get("/partials/jobs", response_class=HTMLResponse)
def jobs_partial(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    return render(request, "partials/jobs_table.html", p, jobs=_jobs_for(session, user))


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    job = session.get(db.Job, job_id)
    if job is None or (job.owner_id != user.id and not auth.role_at_least(user.role, "operator")):
        raise HTTPException(404, "no such job")
    rounds = session.scalars(select(db.Round).where(db.Round.job_id == job.id).order_by(db.Round.index)).all()
    updates = session.scalars(select(db.Update).where(db.Update.job_id == job.id).order_by(db.Update.round_index.desc(), db.Update.id).limit(200)).all()
    closed = [r for r in rounds if r.status == "closed"]
    series = {"rounds": [r.index for r in closed], "loss": [r.eval_loss for r in closed], "acc": [r.eval_acc for r in closed]}
    return render(request, "job.html", p, job=job, rounds=rounds, updates=updates, series=series, show_names=auth.role_at_least(user.role, "operator"))


@router.get("/partials/jobs/{job_id}", response_class=HTMLResponse)
def job_partial(request: Request, job_id: str, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    job = session.get(db.Job, job_id)
    if job is None or (job.owner_id != user.id and not auth.role_at_least(user.role, "operator")):
        raise HTTPException(404, "no such job")
    rounds = session.scalars(select(db.Round).where(db.Round.job_id == job.id).order_by(db.Round.index)).all()
    updates = session.scalars(select(db.Update).where(db.Update.job_id == job.id).order_by(db.Update.round_index.desc(), db.Update.id).limit(200)).all()
    closed = [r for r in rounds if r.status == "closed"]
    series = {"rounds": [r.index for r in closed], "loss": [r.eval_loss for r in closed], "acc": [r.eval_acc for r in closed]}
    return render(request, "partials/job_live.html", p, job=job, rounds=rounds, updates=updates, series=series, show_names=auth.role_at_least(user.role, "operator"))


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str, p: Principal = Depends(principal_optional), session: Session = Depends(get_session), state=Depends(get_state)):
    user = need_user(p)
    job = session.get(db.Job, job_id)
    if job is None or (job.owner_id != user.id and not auth.role_at_least(user.role, "operator")):
        raise HTTPException(404, "no such job")
    if job.status == "running":
        state.engine.cancel_job(session, job)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/machine", response_class=HTMLResponse)
def my_machines(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    machines = session.scalars(select(db.Machine).where(db.Machine.user_id == user.id).order_by(db.Machine.name)).all()
    if len(machines) == 1:
        return RedirectResponse(f"/machine/{machines[0].node_id}", status_code=303)
    return render(request, "machines.html", p, machines=machines)


def _machine_for(session: Session, user: db.User, node_id: str) -> db.Machine:
    m = session.scalar(select(db.Machine).where(db.Machine.node_id == node_id))
    if m is None or (m.user_id != user.id and not auth.role_at_least(user.role, "operator")):
        raise HTTPException(404, "no such machine")
    return m


def _machine_ctx(session: Session, m: db.Machine) -> dict:
    since = db.now() - dt.timedelta(hours=1)
    history = session.scalars(select(db.Heartbeat).where(db.Heartbeat.machine_id == m.id, db.Heartbeat.at >= since).order_by(db.Heartbeat.at)).all()
    job = session.get(db.Job, m.current_job_id) if m.current_job_id else None
    recent = session.scalars(select(db.Update).where(db.Update.machine_id == m.id).order_by(db.Update.id.desc()).limit(20)).all()
    logs = session.scalars(select(db.LogLine).where(db.LogLine.machine_id == m.id).order_by(db.LogLine.id.desc()).limit(100)).all()
    spark = {k: [float((h.metrics or {}).get(k) or 0) for h in history] for k in ("cpu_pct", "ram_pct", "gpu_pct")}
    return {"m": m, "job": job, "history": history, "recent": recent, "logs": list(reversed(logs)), "spark": spark}


@router.get("/machine/{node_id}", response_class=HTMLResponse)
def machine_page(request: Request, node_id: str, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    return render(request, "machine.html", p, **_machine_ctx(session, _machine_for(session, user, node_id)))


@router.get("/partials/machine/{node_id}", response_class=HTMLResponse)
def machine_partial(request: Request, node_id: str, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    return render(request, "partials/machine_live.html", p, **_machine_ctx(session, _machine_for(session, user, node_id)))


@router.get("/fleet", response_class=HTMLResponse)
def fleet_page(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    if not auth.role_at_least(user.role, "operator"):
        raise HTTPException(403, "the fleet page needs the operator role")
    machines = session.scalars(select(db.Machine).order_by(db.Machine.status, db.Machine.name)).all()
    return render(request, "fleet.html", p, machines=machines, summary=_summary(session))


@router.get("/partials/fleet", response_class=HTMLResponse)
def fleet_partial(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    user = need_user(p)
    if not auth.role_at_least(user.role, "operator"):
        raise HTTPException(403, "operator role needed")
    machines = session.scalars(select(db.Machine).order_by(db.Machine.status, db.Machine.name)).all()
    return render(request, "partials/fleet_table.html", p, machines=machines, summary=_summary(session))


@router.get("/server", response_class=HTMLResponse)
def server_page(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session), state=Depends(get_state)):
    user = need_user(p)
    if not auth.role_at_least(user.role, "operator"):
        raise HTTPException(403, "the server page needs the operator role")
    from .api_misc import server_status

    return render(request, "server.html", p, status=server_status(user, session, state))


@router.get("/ledger", response_class=HTMLResponse)
def ledger_page(request: Request, p: Principal = Depends(principal_optional), session: Session = Depends(get_session), state=Depends(get_state)):
    need_user(p)
    entries = session.scalars(select(db.LedgerEntry).order_by(db.LedgerEntry.seq.desc()).limit(200)).all()
    ok, count, problem = ledger.verify(session, state.server.node_id)
    return render(request, "ledger.html", p, entries=entries, ok=ok, count=count, problem=problem, server_node_id=state.server.node_id)

"""Fleet control, machine logs, users, invites, audit log, org policy, metrics."""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from . import auth, db, policy
from .api_auth import Email
from .api_machines import machine_out
from .config import OrgPolicy
from .deps import current_user, get_session, get_state, require_role

router = APIRouter(prefix="/v1", tags=["fleet"])


def _machine(session: Session, node_id: str) -> db.Machine:
    m = session.scalar(select(db.Machine).where(db.Machine.node_id == node_id))
    if m is None:
        raise HTTPException(404, "no such machine")
    return m


def _audit(session: Session, actor: db.User, action: str, target: str, **detail) -> None:
    session.add(db.AuditEvent(actor_id=actor.id, action=action, target=target, detail=detail))


class ControlIn(BaseModel):
    reason: str = ""


@router.post("/fleet/{node_id}/pause")
def pause(node_id: str, body: ControlIn, user: db.User = Depends(require_role("operator")), session: Session = Depends(get_session), state=Depends(get_state)):
    m = _machine(session, node_id)
    m.paused_by_admin = True
    _audit(session, user, "fleet.pause", node_id, reason=body.reason)
    session.commit()
    state.bus.publish("fleet", {"event": "pause", "node": node_id})
    return machine_out(m)


@router.post("/fleet/{node_id}/resume")
def resume(node_id: str, user: db.User = Depends(require_role("operator")), session: Session = Depends(get_session), state=Depends(get_state)):
    m = _machine(session, node_id)
    m.paused_by_admin = False
    m.draining = False
    _audit(session, user, "fleet.resume", node_id)
    session.commit()
    state.bus.publish("fleet", {"event": "resume", "node": node_id})
    return machine_out(m)


@router.post("/fleet/{node_id}/drain")
def drain(node_id: str, body: ControlIn, user: db.User = Depends(require_role("operator")), session: Session = Depends(get_session), state=Depends(get_state)):
    """Finish the current round, then stop taking rounds."""
    m = _machine(session, node_id)
    m.draining = True
    _audit(session, user, "fleet.drain", node_id, reason=body.reason)
    session.commit()
    state.bus.publish("fleet", {"event": "drain", "node": node_id})
    return machine_out(m)


class TagsIn(BaseModel):
    tags: list[str] = Field(max_length=20)


@router.post("/fleet/{node_id}/tags")
def set_tags(node_id: str, body: TagsIn, user: db.User = Depends(require_role("operator")), session: Session = Depends(get_session)):
    m = _machine(session, node_id)
    m.tags = sorted({t.strip()[:32] for t in body.tags if t.strip()})
    _audit(session, user, "fleet.tags", node_id, tags=m.tags)
    session.commit()
    return machine_out(m)


@router.delete("/fleet/{node_id}")
def revoke(node_id: str, user: db.User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    """Revoke the machine's tokens. The machine must enrol again to come back."""
    m = _machine(session, node_id)
    for tok in session.scalars(select(db.Token).where(db.Token.machine_id == m.id, db.Token.revoked.is_(False))):
        tok.revoked = True
    m.status = "offline"
    m.status_detail = "revoked by admin"
    _audit(session, user, "fleet.revoke", node_id)
    session.commit()
    return machine_out(m)


@router.get("/fleet/{node_id}/logs")
def machine_logs(node_id: str, since_id: int = 0, limit: int = 200, grep: str | None = None, user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    m = _machine(session, node_id)
    if m.user_id != user.id and not auth.role_at_least(user.role, "operator"):
        raise HTTPException(403, "not your machine")
    q = select(db.LogLine).where(db.LogLine.machine_id == m.id)
    if since_id:
        q = q.where(db.LogLine.id > since_id).order_by(db.LogLine.id).limit(min(limit, 1000))
        rows = session.scalars(q).all()
    else:
        q = q.order_by(db.LogLine.id.desc()).limit(min(limit, 1000))
        rows = list(reversed(session.scalars(q).all()))
    if grep:
        rows = [r for r in rows if grep.lower() in r.message.lower()]
    return [{"id": r.id, "at": r.at, "level": r.level, "message": r.message} for r in rows]


# ----- users and invites -------------------------------------------------------------

def user_row(u: db.User, machines: int = 0) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "disabled": u.disabled, "created_at": u.created_at, "machines": machines}


@router.get("/users")
def list_users(user: db.User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    counts = dict(session.execute(select(db.Machine.user_id, func.count()).group_by(db.Machine.user_id)).all())
    return [user_row(u, counts.get(u.id, 0)) for u in session.scalars(select(db.User).order_by(db.User.created_at)).all()]


class RoleIn(BaseModel):
    role: str = Field(pattern="^(owner|admin|operator|member|viewer)$")


@router.post("/users/{user_id}/role")
def set_role(user_id: str, body: RoleIn, actor: db.User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    target = session.get(db.User, user_id)
    if target is None:
        raise HTTPException(404, "no such user")
    if (body.role == "owner" or target.role == "owner") and actor.role != "owner":
        raise HTTPException(403, "only an owner can give or take the owner role")
    if target.id == actor.id and body.role != actor.role:
        raise HTTPException(409, "you cannot change your own role")
    _audit(session, actor, "user.role", target.id, before=target.role, after=body.role)
    target.role = body.role
    for tok in session.scalars(select(db.Token).where(db.Token.user_id == target.id, db.Token.revoked.is_(False))):
        tok.scopes = ",".join(sorted(auth.ROLE_SCOPES[body.role]))
    session.commit()
    return user_row(target)


class DisableIn(BaseModel):
    disabled: bool


@router.post("/users/{user_id}/disable")
def disable_user(user_id: str, body: DisableIn, actor: db.User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    target = session.get(db.User, user_id)
    if target is None:
        raise HTTPException(404, "no such user")
    if target.role == "owner" and actor.role != "owner":
        raise HTTPException(403, "only an owner can disable an owner")
    if target.id == actor.id:
        raise HTTPException(409, "you cannot disable yourself")
    target.disabled = body.disabled
    if body.disabled:
        for tok in session.scalars(select(db.Token).where(db.Token.user_id == target.id, db.Token.revoked.is_(False))):
            tok.revoked = True
    _audit(session, actor, "user.disable" if body.disabled else "user.enable", target.id)
    session.commit()
    return user_row(target)


class InviteIn(BaseModel):
    email: Email | None = None
    role: str = Field(default="member", pattern="^(admin|operator|member|viewer)$")
    expires_days: int = Field(default=7, ge=1, le=90)


@router.post("/users/invite")
def invite(body: InviteIn, actor: db.User = Depends(require_role("admin")), session: Session = Depends(get_session), state=Depends(get_state)):
    inv = db.Invite(code=secrets.token_urlsafe(16), role=body.role, email=body.email.lower() if body.email else None, created_by=actor.id, expires_at=db.now() + dt.timedelta(days=body.expires_days))
    session.add(inv)
    _audit(session, actor, "user.invite", body.email or "", role=body.role)
    session.commit()
    return {"code": inv.code, "role": inv.role, "email": inv.email, "expires_at": inv.expires_at, "url": f"{state.public_url()}/register?invite={inv.code}"}


@router.get("/users/invites")
def list_invites(actor: db.User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    rows = session.scalars(select(db.Invite).where(db.Invite.used_by.is_(None), db.Invite.expires_at > db.now()).order_by(db.Invite.created_at.desc())).all()
    return [{"code": i.code, "role": i.role, "email": i.email, "expires_at": i.expires_at} for i in rows]


# ----- audit, policy, metrics --------------------------------------------------------

@router.get("/audit")
def audit(since_hours: int = 24, limit: int = 200, user: db.User = Depends(require_role("operator")), session: Session = Depends(get_session)):
    since = db.now() - dt.timedelta(hours=since_hours)
    rows = session.scalars(select(db.AuditEvent).where(db.AuditEvent.at >= since).order_by(db.AuditEvent.at.desc()).limit(min(limit, 1000))).all()
    users = {u.id: u.email for u in session.scalars(select(db.User)).all()}
    return [{"at": r.at, "actor": users.get(r.actor_id, r.actor_id), "action": r.action, "target": r.target, "detail": r.detail} for r in rows]


@router.get("/policy")
def get_policy(user: db.User = Depends(current_user), session: Session = Depends(get_session), state=Depends(get_state)):
    return policy.load(session, state.cfg.policy.defaults).model_dump(mode="json")


@router.put("/policy")
def put_policy(body: OrgPolicy, actor: db.User = Depends(require_role("admin")), session: Session = Depends(get_session), state=Depends(get_state)):
    policy.save(session, body)
    _audit(session, actor, "policy.update", "org", windows=len(body.windows), pause_on_battery=body.pause_on_battery)
    session.commit()
    state.bus.publish("fleet", {"event": "policy"})
    return body.model_dump(mode="json")


@router.get("/metrics", include_in_schema=False)
def metrics(session: Session = Depends(get_session), state=Depends(get_state)):
    """Prometheus text format. No auth: the values are counts, not content."""
    by_status = dict(session.execute(select(db.Machine.status, func.count()).group_by(db.Machine.status)).all())
    lines = [
        "# HELP plasmon_info Build information", "# TYPE plasmon_info gauge", f'plasmon_info{{version="{__version__}",mode="{state.cfg.mode}"}} 1',
        "# TYPE plasmon_machines gauge",
    ]
    for status in ("training", "idle", "paused", "unavailable", "offline", "error"):
        lines.append(f'plasmon_machines{{status="{status}"}} {by_status.get(status, 0)}')
    jobs = dict(session.execute(select(db.Job.status, func.count()).group_by(db.Job.status)).all())
    lines.append("# TYPE plasmon_jobs gauge")
    for status in ("running", "completed", "failed", "cancelled"):
        lines.append(f'plasmon_jobs{{status="{status}"}} {jobs.get(status, 0)}')
    lines.append("# TYPE plasmon_rounds_closed_total counter")
    lines.append(f"plasmon_rounds_closed_total {session.scalar(select(func.count()).select_from(db.Round).where(db.Round.status == 'closed'))}")
    lines.append("# TYPE plasmon_ledger_entries gauge")
    lines.append(f"plasmon_ledger_entries {session.scalar(select(func.count()).select_from(db.LedgerEntry))}")
    lines.append("# TYPE plasmon_sse_clients gauge")
    lines.append(f"plasmon_sse_clients {len(state.bus._subs)}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

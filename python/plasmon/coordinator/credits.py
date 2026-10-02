"""Credit accounting: balances, grants, the per-round settlement."""

from __future__ import annotations

import csv
import datetime as dt
import io

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import db
from .config import CreditsConfig


def balance(session: Session, user_id: str) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(db.CreditEntry.amount), 0)).where(db.CreditEntry.user_id == user_id)) or 0)


def balances(session: Session) -> list[dict]:
    rows = session.execute(
        select(db.User.id, db.User.email, db.User.role, func.coalesce(func.sum(db.CreditEntry.amount), 0))
        .outerjoin(db.CreditEntry, db.CreditEntry.user_id == db.User.id)
        .group_by(db.User.id, db.User.email, db.User.role)
        .order_by(db.User.email)
    ).all()
    fee = int(session.scalar(select(func.coalesce(func.sum(db.CreditEntry.amount), 0)).where(db.CreditEntry.user_id.is_(None))) or 0)
    return [{"user_id": r[0], "email": r[1], "role": r[2], "balance": int(r[3])} for r in rows] + [{"user_id": None, "email": "(fee account)", "role": "", "balance": fee}]


def grant(session: Session, user: db.User, amount: int, memo: str, actor: db.User | None) -> db.CreditEntry:
    entry = db.CreditEntry(user_id=user.id, amount=amount, kind="grant", memo=memo)
    session.add(entry)
    session.add(db.AuditEvent(actor_id=actor.id if actor else None, action="credits.grant", target=user.id, detail={"amount": amount, "memo": memo}))
    return entry


def settle_round(session: Session, cfg: CreditsConfig, job: db.Job, round_index: int, accepted: list[db.Update], price_per_1k: float) -> tuple[int, bool]:
    """Charge the owner for the accepted samples and pay the machines' owners.

    Returns (credits spent, owner can continue). Weights: score × samples, or samples when
    every score is zero. The fee goes to the fee account (user None).
    """
    if not cfg.enabled or price_per_1k <= 0 or not accepted:
        return 0, True
    total_samples = sum(u.samples for u in accepted)
    cost = round(price_per_1k * total_samples / 1000)
    if cost <= 0:
        return 0, True
    available = balance(session, job.owner_id)
    if available <= 0:
        return 0, False
    cost = min(cost, available)
    session.add(db.CreditEntry(user_id=job.owner_id, job_id=job.id, round_index=round_index, amount=-cost, kind="spend", memo=f"{job.name} round {round_index}: {total_samples} samples"))
    fee = round(cost * cfg.fee_pct / 100)
    pool = cost - fee
    weights = [max(u.score or 0.0, 0.0) * max(u.samples, 1) for u in accepted]
    if sum(weights) <= 0:
        weights = [float(max(u.samples, 1)) for u in accepted]
    total_w = sum(weights)
    paid = 0
    for u, w in zip(accepted, weights):
        share = int(pool * w / total_w)
        if share <= 0:
            continue
        u.credits = share
        paid += share
        session.add(db.CreditEntry(user_id=u.machine.user_id, machine_id=u.machine_id, job_id=job.id, round_index=round_index, amount=share, kind="earn", memo=f"{job.name} round {round_index}: {u.samples} samples, score {u.score or 0:.3f}"))
    remainder = cost - paid  # the fee plus rounding
    if remainder:
        session.add(db.CreditEntry(user_id=None, job_id=job.id, round_index=round_index, amount=remainder, kind="fee", memo=f"{job.name} round {round_index}"))
    job.credits_spent += cost
    stop = (job.spec.get("budget", {}).get("max_credits") is not None and job.credits_spent >= job.spec["budget"]["max_credits"]) or available - cost <= 0
    return cost, not stop


def entries_for(session: Session, user_id: str, limit: int = 100) -> list[db.CreditEntry]:
    return session.scalars(select(db.CreditEntry).where(db.CreditEntry.user_id == user_id).order_by(db.CreditEntry.id.desc()).limit(limit)).all()


def earned_by_machine(session: Session) -> dict[str, int]:
    rows = session.execute(select(db.CreditEntry.machine_id, func.sum(db.CreditEntry.amount)).where(db.CreditEntry.kind == "earn").group_by(db.CreditEntry.machine_id)).all()
    return {r[0]: int(r[1]) for r in rows if r[0]}


def export_csv(session: Session, since: dt.datetime) -> str:
    users = {u.id: u.email for u in session.scalars(select(db.User)).all()}
    machines = {m.id: m.name for m in session.scalars(select(db.Machine)).all()}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["at_utc", "user", "machine", "job", "round", "kind", "amount", "memo"])
    for e in session.scalars(select(db.CreditEntry).where(db.CreditEntry.at >= since).order_by(db.CreditEntry.id)).all():
        w.writerow([e.at.isoformat(timespec="seconds"), users.get(e.user_id, "" if e.user_id else "fee account"), machines.get(e.machine_id, ""), e.job_id or "", e.round_index if e.round_index is not None else "", e.kind, e.amount, e.memo])
    return out.getvalue()

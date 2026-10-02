"""Jobs, rounds, assignment, commit-reveal and aggregation.

The engine holds no state of its own except caches. Everything persistent is in the
database and the blob store, so a restarted coordinator continues where it stopped.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import torch
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import assignment, identity
from ..core import frame as fr
from ..core.jobspec import JobSpec
from ..train import compression, data, diloco, weights
from . import db, ledger
from .blobs import LocalBlobStore
from .events import Bus

log = logging.getLogger("plasmon.engine")


class EngineError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Assignment:
    job_id: str
    round_index: int
    theta_blob: str
    shard: dict[str, Any]
    spec: dict[str, Any]
    deadline_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "round": self.round_index,
            "theta": self.theta_blob,
            "shard": self.shard,
            "spec": self.spec,
            "deadline_at": self.deadline_at,
        }


class Engine:
    def __init__(self, blobs: LocalBlobStore, bus: Bus, server: identity.Identity, heartbeat_interval_s: int):
        self.blobs = blobs
        self.bus = bus
        self.server = server
        self.heartbeat_interval_s = heartbeat_interval_s
        self._eval_cache: dict[str, tuple[torch.Tensor, torch.Tensor]] = {}
        self._lock = threading.RLock()

    # ----- jobs -------------------------------------------------------------------

    def create_job(
        self,
        session: Session,
        owner: db.User,
        spec: JobSpec,
        init_blob: str,
        shards: list[dict[str, Any]],
        eval_blob: str,
        param_count: int,
    ) -> db.Job:
        for blob_id in [init_blob, eval_blob, *[s["blob"] for s in shards]]:
            if not self.blobs.exists(blob_id):
                raise EngineError(f"blob {blob_id[:12]} was not uploaded", 409)
        if not shards:
            raise EngineError("a job needs at least one shard")
        job = db.Job(
            owner_id=owner.id,
            name=spec.name,
            spec=spec.model_dump(mode="json"),
            seed=f"{spec.name}:{db.new_id('seed')}",
            total_rounds=spec.budget.rounds,
            theta_blob=init_blob,
            init_blob=init_blob,
            shards=shards,
            eval_blob=eval_blob,
            param_count=param_count,
        )
        session.add(job)
        session.flush()
        self._open_round(session, job, spec)
        ledger.append(
            session,
            self.server,
            "job_created",
            {"job": job.id, "owner": owner.id, "name": job.name, "init": init_blob, "shards": len(shards), "rounds": job.total_rounds},
        )
        session.commit()
        self.bus.publish("jobs", {"event": "created", "job": job.id})
        return job

    def cancel_job(self, session: Session, job: db.Job, reason: str = "cancelled by owner") -> None:
        if job.status != "running":
            raise EngineError(f"job is {job.status}", 409)
        job.status = "cancelled"
        job.status_detail = reason
        job.finished_at = db.now()
        for u in session.scalars(select(db.Update).where(db.Update.job_id == job.id, db.Update.status.in_(("assigned", "committed")))):
            u.status = "expired"
        ledger.append(session, self.server, "job_finished", {"job": job.id, "status": "cancelled", "rounds": job.round_index})
        session.commit()
        self.bus.publish(f"job:{job.id}", {"event": "cancelled", "job": job.id})
        self.bus.publish("jobs", {"event": "cancelled", "job": job.id})

    def _open_round(self, session: Session, job: db.Job, spec: JobSpec) -> db.Round:
        rnd = db.Round(
            job_id=job.id,
            index=job.round_index,
            theta_blob=job.theta_blob,
            deadline_at=db.now() + dt.timedelta(seconds=spec.requirements.round_timeout_s),
        )
        session.add(rnd)
        session.flush()
        return rnd

    @staticmethod
    def current_round(session: Session, job: db.Job) -> db.Round | None:
        return session.scalar(select(db.Round).where(db.Round.job_id == job.id, db.Round.index == job.round_index))

    # ----- assignment -------------------------------------------------------------

    def try_assign(self, session: Session, machine: db.Machine) -> Assignment | None:
        """Give an idle machine the current round of the job that needs it most."""
        if machine.paused_by_admin or machine.draining:
            return None
        busy = session.scalar(
            select(func.count()).select_from(db.Update).where(
                db.Update.machine_id == machine.id, db.Update.status.in_(("assigned", "committed"))
            )
        )
        if busy:
            return None
        jobs = session.scalars(select(db.Job).where(db.Job.status == "running").order_by(db.Job.created_at)).all()
        candidates: list[tuple[int, db.Job, db.Round, JobSpec, db.Update | None]] = []
        for job in jobs:
            spec = JobSpec.model_validate(job.spec)
            if not _machine_fits(machine, spec):
                continue
            rnd = self.current_round(session, job)
            if rnd is None or rnd.status != "open":
                continue
            taken = session.scalar(
                select(func.count()).select_from(db.Update).where(
                    db.Update.job_id == job.id,
                    db.Update.round_index == rnd.index,
                    db.Update.status.in_(("assigned", "committed", "revealed")),
                )
            )
            if taken >= spec.requirements.max_trainers:
                continue
            already = session.scalar(
                select(db.Update).where(
                    db.Update.job_id == job.id, db.Update.round_index == rnd.index, db.Update.machine_id == machine.id
                )
            )
            if already is not None and already.status not in ("expired", "rejected"):
                continue
            candidates.append((taken, job, rnd, spec, already))
        if not candidates:
            return None
        taken, job, rnd, spec, previous = min(candidates, key=lambda c: c[0])
        shard_index = assignment.shard_index(job.seed, rnd.index, machine.node_id, len(job.shards))
        shard = job.shards[shard_index]
        if previous is not None:  # the row is unique per (job, round, machine): reuse it
            previous.status = "assigned"
            previous.assigned_at = db.now()
            previous.commit_blob = previous.signature = None
            previous.committed_at = previous.revealed_at = None
            previous.reject_reason = ""
        else:
            session.add(db.Update(job_id=job.id, round_index=rnd.index, machine_id=machine.id, shard_index=shard_index))
        session.flush()
        self.bus.publish(f"job:{job.id}", {"event": "assigned", "job": job.id, "round": rnd.index, "node": machine.node_id})
        return Assignment(job.id, rnd.index, rnd.theta_blob, {"index": shard_index, **shard}, job.spec, rnd.deadline_at.isoformat())

    # ----- commit and reveal ------------------------------------------------------

    def _update_for(self, session: Session, machine: db.Machine, job_id: str, round_index: int) -> tuple[db.Job, db.Round, db.Update]:
        job = session.get(db.Job, job_id)
        if job is None:
            raise EngineError("unknown job", 404)
        rnd = session.scalar(select(db.Round).where(db.Round.job_id == job_id, db.Round.index == round_index))
        if rnd is None:
            raise EngineError("unknown round", 404)
        upd = session.scalar(
            select(db.Update).where(db.Update.job_id == job_id, db.Update.round_index == round_index, db.Update.machine_id == machine.id)
        )
        if upd is None:
            raise EngineError("this machine is not assigned to that round", 409)
        return job, rnd, upd

    def commit(self, session: Session, machine: db.Machine, job_id: str, round_index: int, blob: str, signature: str) -> db.Update:
        job, rnd, upd = self._update_for(session, machine, job_id, round_index)
        if upd.status not in ("assigned", "expired"):
            raise EngineError(f"update is already {upd.status}", 409)
        if rnd.status != "open":
            raise EngineError("round is closed", 409)
        payload = {"job": job_id, "round": round_index, "node": machine.node_id, "blob": blob}
        if not identity.verify(machine.node_id, payload, signature):
            raise EngineError("bad signature", 401)
        upd.status = "committed"
        upd.commit_blob = blob
        upd.signature = signature
        upd.committed_at = db.now()
        session.commit()
        return upd

    def reveal(self, session: Session, machine: db.Machine, job_id: str, round_index: int, blob: str) -> db.Update:
        job, rnd, upd = self._update_for(session, machine, job_id, round_index)
        if upd.status != "committed":
            raise EngineError(f"update is {upd.status}, expected committed", 409)
        if upd.commit_blob != blob:
            upd.status = "rejected"
            upd.reject_reason = "revealed blob differs from commit"
            session.commit()
            raise EngineError("revealed blob differs from the commit", 409)
        if not self.blobs.exists(blob):
            raise EngineError("frame not uploaded yet", 409)
        try:
            frame = fr.decode(self.blobs.get(blob))
        except fr.FrameError as e:
            upd.status = "rejected"
            upd.reject_reason = f"bad frame: {e}"
            session.commit()
            raise EngineError(f"bad frame: {e}") from e
        problems = []
        if frame.job != job_id:
            problems.append("job")
        if frame.round != round_index:
            problems.append("round")
        if frame.node != machine.node_id:
            problems.append("node")
        if frame.theta != rnd.theta_blob:
            problems.append("theta")
        if problems:
            upd.status = "rejected"
            upd.reject_reason = "frame header mismatch: " + ", ".join(problems)
            session.commit()
            raise EngineError(upd.reject_reason)
        upd.status = "revealed"
        upd.revealed_at = db.now()
        upd.samples = frame.samples
        upd.loss_start = _f(frame.meta.get("loss_start"))
        upd.loss_end = _f(frame.meta.get("loss_end"))
        upd.frame_bytes = self.blobs.size(blob)
        session.commit()
        self.bus.publish(f"job:{job_id}", {"event": "revealed", "job": job_id, "round": round_index, "node": machine.node_id})
        return upd

    # ----- scheduler tick ---------------------------------------------------------

    def tick(self, session: Session) -> None:
        with self._lock:
            self._expire_offline_machines(session)
            for job in session.scalars(select(db.Job).where(db.Job.status == "running")).all():
                try:
                    self._tick_job(session, job)
                except Exception:  # keep other jobs alive; the failure is logged and stored
                    log.exception("job %s failed", job.id)
                    session.rollback()
                    job = session.get(db.Job, job.id)
                    if job is not None:
                        job.status = "failed"
                        job.status_detail = "aggregation error, see server log"
                        job.finished_at = db.now()
                        session.commit()
                        self.bus.publish(f"job:{job.id}", {"event": "failed", "job": job.id})

    def _expire_offline_machines(self, session: Session) -> None:
        cutoff = db.now() - dt.timedelta(seconds=3 * self.heartbeat_interval_s + 10)
        for m in session.scalars(select(db.Machine).where(db.Machine.status != "offline", db.Machine.last_seen_at < cutoff)):
            m.status = "offline"
            m.current_job_id = None
            m.current_round = None
            for u in session.scalars(select(db.Update).where(db.Update.machine_id == m.id, db.Update.status.in_(("assigned", "committed")))):
                u.status = "expired"
                u.reject_reason = "machine went offline"
            self.bus.publish("fleet", {"event": "offline", "node": m.node_id})
        session.commit()

    def _tick_job(self, session: Session, job: db.Job) -> None:
        spec = JobSpec.model_validate(job.spec)
        rnd = self.current_round(session, job)
        if rnd is None or rnd.status != "open":
            return
        counts = dict(
            session.execute(
                select(db.Update.status, func.count()).where(db.Update.job_id == job.id, db.Update.round_index == rnd.index).group_by(db.Update.status)
            ).all()
        )
        revealed = counts.get("revealed", 0)
        in_flight = counts.get("assigned", 0) + counts.get("committed", 0)
        now = db.now()
        if revealed >= spec.requirements.min_trainers and in_flight == 0:
            self._close_round(session, job, rnd, spec)
        elif now >= rnd.deadline_at:
            for u in session.scalars(
                select(db.Update).where(db.Update.job_id == job.id, db.Update.round_index == rnd.index, db.Update.status.in_(("assigned", "committed")))
            ):
                u.status = "expired"
                u.reject_reason = "round deadline passed"
            if revealed >= 1:
                self._close_round(session, job, rnd, spec)
            else:
                rnd.deadline_at = now + dt.timedelta(seconds=spec.requirements.round_timeout_s)
                session.commit()
                self.bus.publish(f"job:{job.id}", {"event": "round_extended", "job": job.id, "round": rnd.index})

    def _eval_tensors(self, job: db.Job) -> tuple[torch.Tensor, torch.Tensor]:
        if job.eval_blob not in self._eval_cache:
            shard = data.Shard.from_bytes(self.blobs.get(job.eval_blob))
            self._eval_cache[job.eval_blob] = data.to_tensors(shard)
        return self._eval_cache[job.eval_blob]

    def _close_round(self, session: Session, job: db.Job, rnd: db.Round, spec: JobSpec) -> None:
        t0 = time.perf_counter()
        rnd.status = "aggregating"
        session.commit()
        updates = session.scalars(
            select(db.Update).where(db.Update.job_id == job.id, db.Update.round_index == rnd.index, db.Update.status == "revealed")
        ).all()
        deltas, weights_, accepted = [], [], []
        for u in updates:
            try:
                frame = fr.decode(self.blobs.get(u.commit_blob))
                deltas.append(compression.decompress(frame.tensors))
                weights_.append(float(max(u.samples, 1)))
                accepted.append(u)
            except (fr.FrameError, FileNotFoundError) as e:
                u.status = "rejected"
                u.reject_reason = f"unreadable frame: {e}"
        if not accepted:
            rnd.status = "open"
            rnd.deadline_at = db.now() + dt.timedelta(seconds=spec.requirements.round_timeout_s)
            session.commit()
            return
        theta = weights.from_bytes(self.blobs.get(job.theta_blob))
        avg = diloco.average(deltas, weights_)
        outer = diloco.Outer(spec.recipe.outer_optimizer)
        if job.outer_state_blob:
            outer.load_state_dict(weights.from_bytes(self.blobs.get(job.outer_state_blob)))
        new_theta = outer.step(theta, avg)
        t_agg = time.perf_counter()
        ex, ey = self._eval_tensors(job)
        eval_loss, eval_acc = diloco.evaluate(spec.model.arch, spec.model.config, new_theta, ex, ey, device=torch.device("cpu"))
        t_eval = time.perf_counter()
        new_blob = self.blobs.put(weights.to_bytes(new_theta))
        state_blob = self.blobs.put(weights.to_bytes(outer.state_dict()))
        session.add(db.Blob(id=new_blob, size=self.blobs.size(new_blob), kind="theta"))
        for u in accepted:
            u.status = "accepted"
            u.score = 1.0
            m = session.get(db.Machine, u.machine_id)
            m.rounds_served += 1
            m.samples_verified += u.samples
        rnd.status = "closed"
        rnd.closed_at = db.now()
        rnd.accepted = len(accepted)
        rnd.eval_loss, rnd.eval_acc = eval_loss, eval_acc
        losses = [u.loss_end for u in accepted if u.loss_end is not None]
        rnd.mean_loss_end = sum(losses) / len(losses) if losses else None
        rnd.bytes_in = sum(u.frame_bytes for u in accepted)
        rnd.timings = {"aggregate_s": round(t_agg - t0, 3), "eval_s": round(t_eval - t_agg, 3)}
        ledger.append(
            session,
            self.server,
            "round",
            {
                "job": job.id,
                "round": rnd.index,
                "theta_in": job.theta_blob,
                "theta_out": new_blob,
                "updates": [{"node": u.machine.node_id, "blob": u.commit_blob, "samples": u.samples} for u in accepted],
                "eval_loss_milli": int(eval_loss * 1000),
                "eval_acc_milli": int(eval_acc * 1000),
            },
        )
        job.theta_blob = new_blob
        job.outer_state_blob = state_blob
        job.last_eval_loss, job.last_eval_acc = eval_loss, eval_acc
        job.round_index += 1
        if job.round_index >= job.total_rounds:
            job.status = "completed"
            job.finished_at = db.now()
            ledger.append(session, self.server, "job_finished", {"job": job.id, "status": "completed", "rounds": job.round_index, "theta": new_blob})
        else:
            self._open_round(session, job, spec)
        session.commit()
        self.bus.publish(
            f"job:{job.id}",
            {"event": "round_closed", "job": job.id, "round": rnd.index, "eval_loss": eval_loss, "eval_acc": eval_acc, "accepted": len(accepted), "status": job.status},
        )
        self.bus.publish("jobs", {"event": "round_closed", "job": job.id, "round": rnd.index, "status": job.status})


def _machine_fits(machine: db.Machine, spec: JobSpec) -> bool:
    hw = machine.hardware or {}
    device = spec.requirements.device
    gpu = hw.get("gpu") or {}
    if device == "cuda" and gpu.get("kind") != "cuda":
        return False
    if device == "mps" and gpu.get("kind") != "mps":
        return False
    if spec.requirements.min_vram_gb and float(gpu.get("vram_gb") or 0) < spec.requirements.min_vram_gb:
        return False
    return True


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


class Scheduler(threading.Thread):
    """Runs `engine.tick` on an interval in its own thread with its own sessions."""

    def __init__(self, engine: Engine, session_factory, interval_s: float):
        super().__init__(name="plasmon-scheduler", daemon=True)
        self.engine = engine
        self.session_factory = session_factory
        self.interval_s = interval_s
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                with self.session_factory() as session:
                    self.engine.tick(session)
            except Exception:
                log.exception("scheduler tick failed")
            self._stop.wait(self.interval_s)

    def stop(self) -> None:
        self._stop.set()

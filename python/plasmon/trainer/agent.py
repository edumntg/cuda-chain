"""The trainer loop.

    heartbeat → assignment → fetch θ and shard → inner round → compress →
    commit (signed) → upload → reveal → heartbeat ...

Control commands arrive in heartbeat replies: pause, drain. The agent never opens an
inbound port.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import torch

from ..client import ApiError, Client
from ..core import frame as fr
from ..core.identity import Identity
from ..core.jobspec import JobSpec
from ..credentials import MachineCredentials, load_machine, machine_path, save_machine
from ..paths import cache_dir
from ..train import compression, data, diloco, weights
from . import telemetry

log = logging.getLogger("plasmon.trainer")


class LogBuffer(logging.Handler):
    """Keeps recent log lines for the next heartbeat."""

    def __init__(self):
        super().__init__()
        self.lines: deque[dict[str, Any]] = deque(maxlen=500)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append({"at": dt.datetime.now(dt.UTC).isoformat(), "level": record.levelname.lower(), "message": record.getMessage()[:2000]})

    def drain(self) -> list[dict[str, Any]]:
        out = list(self.lines)
        self.lines.clear()
        return out


class Agent:
    def __init__(self, server: str, user_token: str | None, identity: Identity, name: str, device: str = "any", max_hours: float | None = None):
        self.server = server
        self.identity = identity
        self.name = name
        self.device_pref = device
        self.device = diloco.pick_device(device)
        self.deadline = time.time() + max_hours * 3600 if max_hours else None
        self.user_client = Client(server, user_token) if user_token else None
        self.client: Client | None = None
        self.creds: MachineCredentials | None = None
        self.state = "idle"
        self.detail = ""
        self.job_id: str | None = None
        self.round: int | None = None
        self.step = 0
        self.steps_total = 0
        self.paused = False
        self.draining = False
        self.stop_event = threading.Event()
        self.compressors: dict[str, compression.Compressor] = {}
        self.buffer = LogBuffer()
        log.addHandler(self.buffer)
        self.blob_cache = cache_dir() / "blobs"
        self.blob_cache.mkdir(parents=True, exist_ok=True)
        self.heartbeat_interval = 3  # the server's value replaces this after the first reply
        self.idle_interval = 3
        self.session_rounds = 0
        self.session_samples = 0
        self.machine_creds_path: Path = machine_path()
        self._lock = threading.Lock()

    # ----- enrolment ---------------------------------------------------------------

    def enrol(self) -> None:
        existing = load_machine(self.machine_creds_path)
        if existing and existing.server == self.server and existing.node_id == self.identity.node_id:
            self.creds = existing
            self.client = Client(self.server, existing.token)
            try:
                self.client.me()
                log.info("machine %s already enrolled", self.identity.node_id[:8])
                return
            except ApiError:
                log.info("machine token rejected, registering again")
        if self.user_client is None:
            raise RuntimeError("not logged in on this machine; run `plasmon login` first")
        me = self.user_client.me()
        user_id = me["user"]["id"]
        body = {
            "node_id": self.identity.node_id,
            "name": self.name,
            "hardware": telemetry.hardware(),
            "versions": telemetry.versions(),
            "signature": self.identity.sign({"node_id": self.identity.node_id, "user": user_id}),
        }
        out = self.user_client.register_machine(body)
        self.creds = MachineCredentials(self.server, self.identity.node_id, out["machine_token"], out["machine"]["id"])
        save_machine(self.creds, self.machine_creds_path)
        self.client = Client(self.server, self.creds.token)
        log.info("enrolled machine %s as %s", self.identity.node_id[:8], self.name)

    # ----- heartbeat ---------------------------------------------------------------

    def heartbeat(self) -> dict[str, Any]:
        assert self.client is not None
        metrics = telemetry.metrics()
        metrics.update({"step": self.step, "steps_total": self.steps_total, "session_rounds": self.session_rounds, "session_samples": self.session_samples})
        with self._lock:
            body = {"status": self.state, "status_detail": self.detail, "job_id": self.job_id, "round": self.round, "metrics": metrics, "logs": self.buffer.drain()}
        reply = self.client.heartbeat(body)
        self.heartbeat_interval = reply.get("interval", 10)
        self.idle_interval = reply.get("idle_interval", 3)
        for cmd in reply.get("commands", []):
            if cmd["type"] == "pause" and not self.paused:
                log.info("paused: %s", cmd.get("reason", ""))
                self.paused = True
            if cmd["type"] == "drain":
                self.draining = True
        if not any(c["type"] == "pause" for c in reply.get("commands", [])) and self.paused:
            log.info("resumed")
            self.paused = False
        return reply

    def _heartbeat_thread(self) -> None:
        while not self.stop_event.is_set():
            if self.state == "training":  # the main loop idles only between rounds
                try:
                    self.heartbeat()
                except ApiError as e:
                    log.warning("heartbeat failed: %s", e)
                except Exception as e:  # network blips
                    log.warning("heartbeat error: %s", e)
            self.stop_event.wait(self.heartbeat_interval)

    # ----- blobs -------------------------------------------------------------------

    def fetch_blob(self, blob_id: str) -> bytes:
        assert self.client is not None
        path = self.blob_cache / blob_id
        if path.exists():
            return path.read_bytes()
        content = self.client.get_blob(blob_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
        return content

    # ----- one round ---------------------------------------------------------------

    def run_assignment(self, a: dict[str, Any]) -> None:
        assert self.client is not None
        spec = JobSpec.model_validate(a["spec"])
        job_id, rnd = a["job_id"], a["round"]
        with self._lock:
            self.state, self.job_id, self.round, self.step, self.steps_total = "training", job_id, rnd, 0, spec.recipe.inner_steps
            self.detail = f"shard {a['shard']['index']}"
        log.info("round %s of %s: shard %s (%s samples)", rnd, spec.name, a["shard"]["index"], a["shard"]["n"])
        t0 = time.perf_counter()
        theta = weights.from_bytes(self.fetch_blob(a["theta"]))
        shard = data.Shard.from_bytes(self.fetch_blob(a["shard"]["blob"]))
        x, y = data.to_tensors(shard)
        t_fetch = time.perf_counter()

        def on_step(i: int) -> None:
            self.step = i + 1

        result = diloco.inner_round(spec.model.arch, spec.model.config, theta, x, y, spec.recipe, seed=(hash((job_id, rnd, self.identity.node_id)) & 0xFFFFFFFF), device=self.device, on_step=on_step)
        t_train = time.perf_counter()
        comp = self.compressors.setdefault(job_id, compression.Compressor(spec.recipe.compression.topk if spec.recipe.compression.name == "topk" else 1.0, spec.recipe.compression.error_feedback))
        entries = comp.compress(result.delta)
        frame = fr.Frame(job_id, rnd, self.identity.node_id, a["theta"], result.samples, entries, {"loss_start": result.loss_start, "loss_end": result.loss_end, "steps": result.steps, "device": str(self.device)})
        encoded = fr.encode(frame)
        blob_id = fr_digest(encoded)
        signature = self.identity.sign({"job": job_id, "round": rnd, "node": self.identity.node_id, "blob": blob_id})
        self.client.commit(job_id, rnd, blob_id, signature)
        self.client.put_blob(encoded, kind="delta")
        self.client.reveal(job_id, rnd, blob_id)
        t_done = time.perf_counter()
        self.session_rounds += 1
        self.session_samples += result.samples
        log.info(
            "round %s done: loss %.3f→%.3f, %s bytes up, fetch %.1fs train %.1fs upload %.1fs",
            rnd, result.loss_start, result.loss_end, f"{len(encoded):,}", t_fetch - t0, t_train - t_fetch, t_done - t_train,
        )

    # ----- main loop ---------------------------------------------------------------

    def run(self) -> None:
        self.enrol()
        hb = threading.Thread(target=self._heartbeat_thread, name="plasmon-heartbeat", daemon=True)
        hb.start()
        log.info("trainer %s on %s, device %s", self.name, self.server, self.device)
        try:
            while not self.stop_event.is_set():
                if self.deadline and time.time() > self.deadline:
                    log.info("max hours reached, stopping")
                    break
                if self.draining:
                    log.info("drained, stopping")
                    break
                with self._lock:
                    self.state = "paused" if self.paused else "idle"
                    self.job_id = self.round = None
                    self.detail = "paused by admin" if self.paused else ""
                try:
                    reply = self.heartbeat()
                except ApiError as e:
                    if e.status == 401:
                        log.warning("machine token rejected; re-enrolling")
                        self.enrol()
                        continue
                    log.warning("heartbeat failed: %s", e)
                    self.stop_event.wait(self.idle_interval)
                    continue
                except Exception as e:
                    log.warning("server unreachable: %s", e)
                    self.stop_event.wait(5)
                    continue
                assignment = reply.get("assignment")
                if assignment and not self.paused:
                    try:
                        self.run_assignment(assignment)
                    except ApiError as e:
                        log.warning("round rejected by server: %s", e)
                    except Exception:
                        log.exception("round failed")
                        with self._lock:
                            self.state, self.detail = "error", "round failed, see log"
                        self.stop_event.wait(self.idle_interval)
                else:
                    self.stop_event.wait(self.idle_interval)
        finally:
            self.stop_event.set()
            with self._lock:
                self.state = "idle"

    def stop(self) -> None:
        self.stop_event.set()


def fr_digest(data: bytes) -> str:
    from ..core import hashing

    return hashing.digest(data)


def default_name() -> str:
    import platform

    return platform.node() or "machine"


def machine_key_or_create(path: Path) -> Identity:
    if path.exists():
        return Identity.load(path)
    ident = Identity.generate()
    ident.save(path)
    return ident


__all__ = ["Agent", "default_name", "machine_key_or_create", "torch"]

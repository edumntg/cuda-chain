"""DiLoCo: local steps with an inner optimizer, a pseudo-gradient per trainer, and one
outer optimizer step on the average.

    inner:  θ_i ← AdamW steps on the trainer's shard, starting from θ_r
    Δ_i    = θ_r − θ_i
    outer:  θ_{r+1} = θ_r − OuterStep(mean_i Δ_i)

The outer optimizer is Nesterov momentum SGD, as in the DiLoCo paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch
from torch import nn

from ..core.jobspec import InnerOptimizer, OuterOptimizer, RecipeSpec
from . import models

State = dict[str, torch.Tensor]


def pick_device(preference: str = "any") -> torch.device:
    if preference in ("any", "cuda") and torch.cuda.is_available():
        return torch.device("cuda")
    if preference in ("any", "mps") and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    if preference in ("cuda", "mps"):
        raise RuntimeError(f"device {preference} requested but not available")
    return torch.device("cpu")


def _make_inner(params, spec: InnerOptimizer) -> torch.optim.Optimizer:
    if spec.name == "adamw":
        return torch.optim.AdamW(params, lr=spec.lr, betas=spec.betas, weight_decay=spec.weight_decay)
    return torch.optim.SGD(params, lr=spec.lr, momentum=0.9, weight_decay=spec.weight_decay)


@dataclass
class RoundResult:
    delta: State
    loss_start: float
    loss_end: float
    samples: int
    steps: int


def inner_round(
    arch: str,
    config: dict,
    theta: State,
    x: torch.Tensor,
    y: torch.Tensor,
    recipe: RecipeSpec,
    seed: int,
    device: torch.device | None = None,
    on_step=None,
) -> RoundResult:
    """Run `recipe.inner_steps` optimizer steps from θ and return Δ = θ − θ_i."""
    device = device or pick_device()
    model = models.build(arch, config).to(device)
    model.load_state_dict({k: v.to(device) for k, v in theta.items()})
    model.train()
    opt = _make_inner(model.parameters(), recipe.inner_optimizer)
    loss_fn = nn.CrossEntropyLoss()
    gen = torch.Generator().manual_seed(seed)
    n = len(y)
    x, y = x.to(device), y.to(device)
    loss_start = loss_end = 0.0
    for step in range(recipe.inner_steps):
        idx = torch.randint(0, n, (min(recipe.batch_size, n),), generator=gen).to(device)
        opt.zero_grad(set_to_none=True)
        loss = loss_fn(model(x[idx]), y[idx])
        loss.backward()
        opt.step()
        value = float(loss.detach())
        if step == 0:
            loss_start = value
        loss_end = value
        if on_step is not None:
            on_step(step)
    new_state = model.state_dict()
    delta = {k: (theta[k].float() - new_state[k].detach().float().cpu()) for k in theta}
    return RoundResult(delta, loss_start, loss_end, recipe.inner_steps * recipe.batch_size, recipe.inner_steps)


@dataclass
class Outer:
    spec: OuterOptimizer
    momentum: State = field(default_factory=dict)

    def step(self, theta: State, avg_delta: State) -> State:
        new = {}
        for name, value in theta.items():
            d = avg_delta[name]
            if self.spec.name == "sgd" or self.spec.momentum == 0:
                new[name] = value - self.spec.lr * d
                continue
            buf = self.momentum.get(name)
            buf = d.clone() if buf is None else buf * self.spec.momentum + d
            self.momentum[name] = buf
            new[name] = value - self.spec.lr * (d + self.spec.momentum * buf)
        return new

    def state_dict(self) -> State:
        return dict(self.momentum)

    def load_state_dict(self, state: State) -> None:
        self.momentum = dict(state)


def average(deltas: list[State], weights: list[float] | None = None) -> State:
    if not deltas:
        raise ValueError("no deltas to average")
    weights = weights or [1.0] * len(deltas)
    total = sum(weights)
    out: State = {}
    for name in deltas[0]:
        out[name] = sum(d[name] * (w / total) for d, w in zip(deltas, weights))
    return out


@torch.no_grad()
def evaluate(arch: str, config: dict, theta: State, x: torch.Tensor, y: torch.Tensor, device=None) -> tuple[float, float]:
    """Return (mean loss, accuracy) of θ on the given tensors."""
    device = device or pick_device()
    model = models.build(arch, config).to(device)
    model.load_state_dict({k: v.to(device) for k, v in theta.items()})
    model.eval()
    loss_fn = nn.CrossEntropyLoss(reduction="sum")
    total_loss, correct = 0.0, 0
    for i in range(0, len(y), 1024):
        xb, yb = x[i : i + 1024].to(device), y[i : i + 1024].to(device)
        logits = model(xb)
        total_loss += float(loss_fn(logits, yb))
        correct += int((logits.argmax(1) == yb).sum())
    return total_loss / len(y), correct / len(y)

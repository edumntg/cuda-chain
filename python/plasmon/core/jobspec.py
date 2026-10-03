"""The job specification (job.yaml) and its validation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Architectures a trainer will instantiate from a config. No user code runs on a trainer.
ALLOWED_ARCHS = ("mnist_cnn", "mlp", "cifar_cnn", "char_lm")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSpec(StrictModel):
    arch: str
    init: str | None = Field(default=None, description="blob id or local path of initial weights")
    config: dict[str, int | float | str | bool] = Field(default_factory=dict)

    @field_validator("arch")
    @classmethod
    def _arch_allowed(cls, v: str) -> str:
        if v not in ALLOWED_ARCHS:
            raise ValueError(f"arch must be one of {', '.join(ALLOWED_ARCHS)}")
        return v


class DatasetSpec(StrictModel):
    source: str = Field(
        description="builtin://mnist, builtin://fashion-mnist, builtin://cifar10, builtin://tinyshakespeare, an https:// URL or a local path of a .csv, .csv.gz, .npz or .txt file, or a directory with the IDX .gz files or .npz shards"
    )
    eval_source: str | None = Field(default=None, description="optional test file (same formats); default: the builtin test split or eval_fraction of the data")
    label_column: Literal["first", "last"] = "first"
    image_shape: tuple[int, int] = (28, 28)
    shard_size: int = Field(default=1000, ge=64)
    eval_fraction: float = Field(default=0.1, gt=0, lt=0.5)
    block_size: int = Field(default=128, ge=16, le=1024, description="characters per training sequence for text sources")


class InnerOptimizer(StrictModel):
    name: Literal["adamw", "sgd"] = "adamw"
    lr: float = 1e-3
    betas: tuple[float, float] = (0.9, 0.95)
    weight_decay: float = 0.0


class OuterOptimizer(StrictModel):
    name: Literal["nesterov", "sgd"] = "nesterov"
    lr: float = 0.7
    momentum: float = 0.9


class Compression(StrictModel):
    name: Literal["topk", "none"] = "topk"
    topk: float = Field(default=0.1, gt=0, le=1)
    error_feedback: bool = True


class RecipeSpec(StrictModel):
    algorithm: Literal["diloco"] = "diloco"
    inner_steps: int = Field(default=50, ge=1)
    batch_size: int = Field(default=64, ge=1)
    inner_optimizer: InnerOptimizer = InnerOptimizer()
    outer_optimizer: OuterOptimizer = OuterOptimizer()
    compression: Compression = Compression()
    seed: int = 0


class Requirements(StrictModel):
    device: Literal["any", "cuda", "mps", "cpu"] = "any"
    min_vram_gb: float = 0
    min_trainers: int = Field(default=1, ge=1)
    max_trainers: int = Field(default=16, ge=1)
    round_timeout_s: int = Field(default=600, ge=30)


class Budget(StrictModel):
    rounds: int = Field(default=20, ge=1)
    max_credits: int | None = Field(default=None, ge=0, description="stop the job when this many credits were spent")
    credits_per_1k_samples: float = Field(default=0.0, ge=0, description="price paid per 1,000 accepted samples; 0 when credits are off")


class JobSpec(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    model: ModelSpec
    dataset: DatasetSpec
    recipe: RecipeSpec = RecipeSpec()
    requirements: Requirements = Requirements()
    budget: Budget = Budget()

    @model_validator(mode="after")
    def _text_model_matches_data(self) -> JobSpec:
        if self.model.arch == "char_lm":
            block = int(self.model.config.get("block_size", 128))
            if block != self.dataset.block_size:
                raise ValueError(f"model.config.block_size ({block}) must equal dataset.block_size ({self.dataset.block_size})")
        return self

    @field_validator("requirements")
    @classmethod
    def _trainer_bounds(cls, v: Requirements) -> Requirements:
        if v.max_trainers < v.min_trainers:
            raise ValueError("max_trainers must be >= min_trainers")
        return v


def load(path: str | Path) -> JobSpec:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return JobSpec.model_validate(data)


def loads(text: str) -> JobSpec:
    return JobSpec.model_validate(yaml.safe_load(text) or {})

"""Argument parsing for `python -m plasmon`. Subcommands register themselves here."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from . import __version__

Handler = Callable[[argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plasmon", description="plasmon engine")
    parser.add_argument("--version", action="version", version=f"plasmon {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command")

    from .core.identity import Identity

    def cmd_init(args: argparse.Namespace) -> int:
        from .paths import machine_key_path

        path = machine_key_path()
        if path.exists() and not args.force:
            ident = Identity.load(path)
            print(f"machine key exists: {path}\nnode id: {ident.node_id}")
            return 0
        ident = Identity.generate()
        ident.save(path)
        print(f"created machine key: {path}\nnode id: {ident.node_id}")
        return 0

    p = sub.add_parser("init", help="create this machine's Ed25519 key")
    p.add_argument("--force", action="store_true", help="replace an existing key")
    p.set_defaults(handler=cmd_init)

    def cmd_bench(args: argparse.Namespace) -> int:
        from .core import jobspec
        from .train import data, simulate

        spec = jobspec.load(args.job) if args.job else jobspec.loads(
            "name: bench\nmodel: {arch: mnist_cnn}\ndataset: {source: builtin://mnist}\n"
            "recipe: {inner_steps: 50, inner_optimizer: {lr: 2.0e-3}}\n"
        )
        train, test = data.load_mnist()
        train = data.Shard(train.x[: args.train_samples], train.y[: args.train_samples])
        test = data.Shard(test.x[:2000], test.y[:2000])
        shards = data.split_shards(train, spec.dataset.shard_size, seed=1)
        sim = simulate.run(spec, shards, test, trainers=args.trainers, rounds=args.rounds)
        steps = args.rounds * spec.recipe.inner_steps
        _, base_acc = simulate.baseline(spec, train, test, steps=steps)
        print(f"{'round':>5} {'eval loss':>9} {'eval acc':>8} {'frame bytes':>11} {'dense bytes':>11}")
        for r in sim.rounds:
            print(f"{r.round:>5} {r.eval_loss:>9.4f} {r.eval_acc:>8.4f} {r.frame_bytes:>11,} {r.dense_bytes:>11,}")
        pct = 100 * sim.total_frame_bytes / sim.total_dense_bytes
        print(f"diloco x{args.trainers}: {sim.final_acc:.4f}   single worker, {steps} steps: {base_acc:.4f}")
        print(f"traffic: {sim.total_frame_bytes:,} B sent vs {sim.total_dense_bytes:,} B dense ({pct:.1f} %)")
        return 0

    p = sub.add_parser("bench-diloco", help="simulate N trainers in one process and compare with one worker")
    p.add_argument("--job", help="job.yaml to use (default: mnist_cnn)")
    p.add_argument("--trainers", type=int, default=2)
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--train-samples", type=int, default=12000)
    p.set_defaults(handler=cmd_bench)
    return parser


def main(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)

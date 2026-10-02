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
    return parser


def main(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)

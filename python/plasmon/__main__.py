"""Python entry point: `python -m plasmon`.

The Rust `plasmon` binary is the primary command. It calls this module for the
steps that need PyTorch (server, trainer, job submit). The same commands work
without the binary, with plain text output.
"""

from __future__ import annotations

import sys

from .cli import main

sys.exit(main(sys.argv[1:]))

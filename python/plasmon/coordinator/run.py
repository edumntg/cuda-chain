"""`python -m plasmon.coordinator`: run the server from plasmon-server.yaml."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import uvicorn

from . import config
from .app import create_app, lan_ip


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else None
    cfg = config.load(path)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = create_app(cfg)
    url = cfg.public_url or f"http://{lan_ip()}:{cfg.port}"
    print(f"plasmon coordinator\n  dashboard  {url}\n  api        {url}/api/docs\n  data       {cfg.resolved_data_dir()}", flush=True)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

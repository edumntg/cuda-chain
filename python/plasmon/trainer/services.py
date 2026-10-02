"""`plasmon trainer enable`: run the trainer at login as a user service.

Linux: a systemd user unit. macOS: a launchd agent. Windows: a scheduled task. The
service runs `python -m plasmon trainer start` as the current user, with no privileges.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "plasmon-trainer"


def _python() -> str:
    return sys.executable


def _args(extra: list[str]) -> list[str]:
    return [_python(), "-m", "plasmon", "trainer", "start", *extra]


def systemd_unit(extra: list[str]) -> str:
    cmd = " ".join(_quote(a) for a in _args(extra))
    return f"""[Unit]
Description=plasmon trainer (offers this machine to the network)
After=network-online.target

[Service]
ExecStart={cmd}
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def launchd_plist(extra: list[str]) -> str:
    items = "\n".join(f"      <string>{a}</string>" for a in _args(extra))
    log = Path.home() / "Library" / "Logs" / "plasmon-trainer.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.plasmon.trainer</string>
  <key>ProgramArguments</key>
  <array>
{items}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def _quote(a: str) -> str:
    return f'"{a}"' if " " in a else a


def enable(extra: list[str], dry_run: bool = False) -> str:
    system = platform.system()
    if system == "Linux":
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user" / f"{NAME}.service"
        text = systemd_unit(extra)
        if dry_run:
            return f"would write {path}:\n{text}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            r = subprocess.run(["systemctl", "--user", "enable", "--now", f"{NAME}.service"], capture_output=True, text=True, check=False)
            if r.returncode != 0:
                return f"wrote {path}\nsystemctl could not start it: {r.stderr.strip()}\nStart it by hand: systemctl --user enable --now {NAME}"
            return f"wrote {path}\nservice enabled and started. Logs: journalctl --user -u {NAME} -f"
        return f"wrote {path}\nsystemctl is not available here; start the service with your init system."
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "dev.plasmon.trainer.plist"
        text = launchd_plist(extra)
        if dry_run:
            return f"would write {path}:\n{text}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
        r = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return f"wrote {path}\nlaunchctl could not load it: {r.stderr.strip()}"
        return f"wrote {path}\nagent loaded; it starts at login. Logs: ~/Library/Logs/plasmon-trainer.log"
    if system == "Windows":
        cmd = " ".join(_quote(a) for a in _args(extra))
        schtasks = ["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", NAME, "/TR", cmd]
        if dry_run:
            return "would run: " + " ".join(schtasks)
        r = subprocess.run(schtasks, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return f"schtasks failed: {r.stderr.strip() or r.stdout.strip()}"
        subprocess.run(["schtasks", "/Run", "/TN", NAME], capture_output=True, check=False)
        return f"scheduled task {NAME} created; it runs at logon and was started now."
    return f"unsupported system {system}"


def disable(dry_run: bool = False) -> str:
    system = platform.system()
    if system == "Linux":
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user" / f"{NAME}.service"
        if dry_run:
            return f"would remove {path}"
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{NAME}.service"], capture_output=True, check=False)
        if path.exists():
            path.unlink()
        return "service removed"
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "dev.plasmon.trainer.plist"
        if dry_run:
            return f"would remove {path}"
        subprocess.run(["launchctl", "unload", "-w", str(path)], capture_output=True, check=False)
        if path.exists():
            path.unlink()
        return "agent removed"
    if system == "Windows":
        if dry_run:
            return f"would run: schtasks /Delete /F /TN {NAME}"
        subprocess.run(["schtasks", "/End", "/TN", NAME], capture_output=True, check=False)
        r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", NAME], capture_output=True, text=True, check=False)
        return "scheduled task removed" if r.returncode == 0 else f"schtasks failed: {r.stderr.strip()}"
    return f"unsupported system {system}"

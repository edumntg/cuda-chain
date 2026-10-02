"""Hardware facts and live metrics for registration and heartbeats."""

from __future__ import annotations

import platform
from typing import Any

import psutil


def _gpu() -> dict[str, Any]:
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {"kind": "cuda", "name": props.name, "vram_gb": round(props.total_memory / 2**30, 1), "count": torch.cuda.device_count()}
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return {"kind": "mps", "name": "Apple GPU", "vram_gb": round(psutil.virtual_memory().total / 2**30, 1), "count": 1}
    except Exception:  # torch missing or broken: report no GPU
        pass
    return {"kind": "none"}


def hardware() -> dict[str, Any]:
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "gpu": _gpu(),
    }


def versions() -> dict[str, str]:
    from .. import __version__

    out = {"plasmon": __version__, "python": platform.python_version()}
    try:
        import torch

        out["torch"] = torch.__version__
    except Exception:
        pass
    return out


class _Nvml:
    def __init__(self):
        self.handle = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self.pynvml = pynvml
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self.pynvml = None

    def read(self) -> dict[str, Any]:
        if self.handle is None:
            return {}
        try:
            util = self.pynvml.nvmlDeviceGetUtilizationRates(self.handle)
            mem = self.pynvml.nvmlDeviceGetMemoryInfo(self.handle)
            out = {"gpu_pct": util.gpu, "vram_used_gb": round(mem.used / 2**30, 2), "vram_total_gb": round(mem.total / 2**30, 2)}
            try:
                out["gpu_temp_c"] = self.pynvml.nvmlDeviceGetTemperature(self.handle, 0)
            except Exception:
                pass
            return out
        except Exception:
            return {}


_nvml = _Nvml()
_last_net = None


def metrics() -> dict[str, Any]:
    global _last_net
    vm = psutil.virtual_memory()
    out: dict[str, Any] = {"cpu_pct": psutil.cpu_percent(interval=None), "ram_pct": vm.percent, "ram_used_gb": round(vm.used / 2**30, 2)}
    try:
        batt = psutil.sensors_battery()
        if batt is not None:
            out["on_battery"] = not batt.power_plugged
            out["battery_pct"] = batt.percent
    except Exception:
        pass
    try:
        net = psutil.net_io_counters()
        import time

        now = time.time()
        if _last_net:
            dt_ = max(now - _last_net[0], 1e-3)
            out["net_up_mbps"] = round(8 * (net.bytes_sent - _last_net[1]) / dt_ / 1e6, 2)
            out["net_down_mbps"] = round(8 * (net.bytes_recv - _last_net[2]) / dt_ / 1e6, 2)
        _last_net = (now, net.bytes_sent, net.bytes_recv)
    except Exception:
        pass
    out.update(_nvml.read())
    return out

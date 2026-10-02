"""Which address `server start` prints: Wi-Fi first, never a VPN tunnel or a VM adapter."""

import socket
from types import SimpleNamespace

import psutil
from plasmon.coordinator import app


def _addr(ip, family=socket.AF_INET):
    return SimpleNamespace(family=family, address=ip)


def test_lan_candidates_skip_tunnels_and_prefer_wifi(monkeypatch):
    fake = {
        "lo0": [_addr("127.0.0.1")],
        "utun3": [_addr("172.16.30.1")],  # corporate VPN
        "vmnet8": [_addr("172.16.5.1")],  # VMware host adapter
        "bridge100": [_addr("192.168.64.1")],  # Apple virtualization
        "awdl0": [_addr("fe80::1", socket.AF_INET6)],
        "en0": [_addr("192.168.1.20"), _addr("fe80::2", socket.AF_INET6)],
        "en5": [_addr("10.0.0.7")],
    }
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: fake)
    cands = app.lan_candidates()
    assert cands[0] == ("en0", "192.168.1.20")
    names = [n for n, _ in cands]
    assert "utun3" not in names and "vmnet8" not in names and "bridge100" not in names and "lo0" not in names
    assert app.lan_ip() == "192.168.1.20"


def test_lan_ip_falls_back_without_candidates(monkeypatch):
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {"lo": [_addr("127.0.0.1")]})
    ip = app.lan_ip()
    assert ip.count(".") == 3

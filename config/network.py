"""
config/network.py — JARVIS lab network registry.

Single source of truth for all machine IPs, MACs, hostnames,
and roles in the local lab topology.

Last verified: 2026-03-17
DO NOT edit without physically verifying with ipconfig/ip addr show.

Import pattern:
    from config.network import NET
    bridge_url = NET.PARROT.bridge_url()
    is_safe    = NET.is_lab_machine(some_ip)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Machine:
    """A physical or virtual machine in the lab."""
    name:     str
    hostname: str
    ip:       str
    mac:      str
    role:     str
    vbox_ip:  Optional[str] = None
    vbox_mac: Optional[str] = None

    def bridge_url(self, port: int = 5000) -> str:
        return f"http://{self.ip}:{port}"

    def is_reachable_from_lan(self) -> bool:
        return self.ip.startswith("192.168.0.")

    def is_isolated(self) -> bool:
        return self.ip.startswith("192.168.56.")


class LabNetwork:
    JARVIS_HOST = Machine(
        name     = "JARVIS Desktop",
        hostname = "Ethical-Hacking-Machine",
        ip       = "192.168.0.111",
        mac      = "88:ae:dd:71:00:b3",
        role     = "JARVIS runtime host. Runs Ollama, GUI, bridge server :5000, OPS :8080.",
        vbox_ip  = "192.168.56.1",
        vbox_mac = "0a:00:27:00:00:15",
    )

    PARROT = Machine(
        name     = "Parrot OS VM",
        hostname = "parrot",
        ip       = "192.168.0.160",
        mac      = "08:00:27:d5:1a:ba",
        role     = "Primary recon VM. Runs subfinder/httpx/nuclei/gau/katana. Polls bridge at JARVIS_HOST.",
    )

    LAPTOP = Machine(
        name     = "Laptop",
        hostname = "DESKTOP-1RF6CD3",
        ip       = "192.168.0.159",
        mac      = "6c:6a:77:16:f1:11",
        role     = "Metasploit2 bridge host. Future second bridge for exploitation workflows.",
        vbox_ip  = "192.168.56.1",
        vbox_mac = "0a:00:27:00:00:04",
    )

    METASPLOITABLE2 = Machine(
        name     = "Metasploit2 VM",
        hostname = "metasploitable",
        ip       = "192.168.56.101",
        mac      = "08:00:27:16:30:e3",
        role     = "Intentionally vulnerable target. Lab use only. ISOLATED — not on 192.168.0.x LAN.",
    )

    IPHONE = Machine(
        name     = "iPhone 16 Pro Max",
        hostname = "iPhone",
        ip       = "",          # DHCP – IP changes
        mac      = "60:81:10:75:6d:78",
        role     = "Operator mobile device. T-Mobile. Used to monitor JARVIS "
                   "OPS graph at 192.168.0.111:5000/ops from anywhere on LAN.",
    )

    BRIDGE_BIND_IP   : str = "192.168.0.111"
    BRIDGE_BIND_PORT : int = 5000
    BRIDGE_CLIENT_URL: str = "http://192.168.0.111:5000"
    BRIDGE_HEALTH_URL: str = "http://192.168.0.111:5000/health"
    OPS_BIND_IP      : str = "127.0.0.1"
    OPS_BIND_PORT    : int = 8080

    def all_lab_ips(self) -> set:
        return {
            self.JARVIS_HOST.ip, self.JARVIS_HOST.vbox_ip,
            self.PARROT.ip,
            self.LAPTOP.ip, self.LAPTOP.vbox_ip,
            self.METASPLOITABLE2.ip,
            "127.0.0.1", "localhost",
        } - {None}

    def all_lab_macs(self) -> set:
        return {
            self.JARVIS_HOST.mac, self.JARVIS_HOST.vbox_mac,
            self.PARROT.mac,
            self.LAPTOP.mac, self.LAPTOP.vbox_mac,
            self.METASPLOITABLE2.mac,
            self.IPHONE.mac,
        } - {None}

    def is_lab_machine(self, ip: str) -> bool:
        return ip in self.all_lab_ips()

    def is_safe_to_scan(self, ip: str) -> bool:
        unsafe = {
            self.JARVIS_HOST.ip, self.JARVIS_HOST.vbox_ip,
            self.PARROT.ip,
            self.LAPTOP.ip, self.LAPTOP.vbox_ip,
        } - {None}
        return ip not in unsafe

    def get_machine(self, ip: str) -> Optional[Machine]:
        for m in [self.JARVIS_HOST, self.PARROT, self.LAPTOP, self.METASPLOITABLE2]:
            if m.ip == ip or m.vbox_ip == ip:
                return m
        return None

    def is_operator_device(self, mac: str) -> bool:
        """True if this is a known operator device (not a target)."""
        operator_macs = {
            self.JARVIS_HOST.mac.lower().replace('-', ':'),
            self.LAPTOP.mac.lower().replace('-', ':') if hasattr(self, 'LAPTOP') else '',
            "60:81:10:75:6d:78",  # iPhone 16 Pro Max
        }
        return mac.lower().replace('-', ':') in operator_macs


NET = LabNetwork()

# Convenience re-exports
JARVIS_HOST_IP    = NET.JARVIS_HOST.ip
PARROT_IP         = NET.PARROT.ip
LAPTOP_IP         = NET.LAPTOP.ip
METASPLOITABLE_IP = NET.METASPLOITABLE2.ip
BRIDGE_URL        = NET.BRIDGE_CLIENT_URL
BRIDGE_BIND       = NET.BRIDGE_BIND_IP
OPS_URL           = f"http://{NET.OPS_BIND_IP}:{NET.OPS_BIND_PORT}"

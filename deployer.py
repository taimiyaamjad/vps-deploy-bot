import asyncio
import logging
import os
import random
import string
import subprocess
import threading
import ipaddress
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import config

log = logging.getLogger("zenvps.deployer")

_lock = threading.Lock()


def _run(cmd: str, timeout: int = 300) -> Tuple[bool, str]:
    """Run a shell command, return (success, output)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def _generate_name() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"{config.VPS_NAME_PREFIX}-{suffix}"


def _next_ip(used_ips: list) -> Optional[str]:
    start = ipaddress.ip_address(config.LXC_IP_RANGE_START)
    end = ipaddress.ip_address(config.LXC_IP_RANGE_END)
    used_set = {ipaddress.ip_address(ip) for ip in used_ips if ip}
    current = start
    while current <= end:
        if current not in used_set:
            return str(current)
        current += 1
    return None


def _next_ssh_port(used_ports: list) -> int:
    base = config.SSH_PORT_BASE
    used_set = set(used_ports)
    port = base
    while port in used_set:
        port += 1
    return port


class Deployer:
    """Unified VPS deployer supporting LXC and mock backends."""

    def __init__(self, db_ref):
        self.db = db_ref
        self.backend = config.DEPLOY_BACKEND

    # ── public API ─────────────────────────────────────────────
    async def deploy(self, owner_id: str, os_key: str,
                     cpu: int, ram: int, disk: int,
                     hours: int = None) -> Dict:
        hours = hours or config.VPS_DEFAULT_EXPIRY_HOURS
        name = _generate_name()
        hostname = name.replace("-", "_")
        expires = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

        # check limits
        count = await self.db.vps_count_for(owner_id)
        user = await self.db.get_or_create_user(owner_id)
        if count >= user["max_vps"]:
            return {"ok": False, "error": "limit", "max": user["max_vps"]}

        if os_key not in config.OS_TEMPLATES:
            return {"ok": False, "error": "invalid_os"}

        vps = await self.db.create_vps(owner_id, name, hostname, os_key, cpu, ram, disk, expires)
        await self.db.add_log(owner_id, "deploy_start", name, f"os={os_key} cpu={cpu} ram={ram} disk={disk}")

        if self.backend == "lxc":
            result = await asyncio.to_thread(self._deploy_lxc, vps)
        else:
            result = await asyncio.to_thread(self._deploy_mock, vps)

        if result["ok"]:
            await self.db.update_vps(name, status="running", ip=result.get("ip"), ssh_port=result.get("ssh_port"))
            await self.db.add_log(owner_id, "deploy_success", name, result.get("ip", ""))
            vps = await self.db.get_vps(name)
            return {"ok": True, "vps": vps}
        else:
            await self.db.update_vps(name, status="failed", notes=result.get("error", ""))
            await self.db.add_log(owner_id, "deploy_fail", name, result.get("error", ""))
            return {"ok": False, "error": result.get("error", "unknown")}

    async def start(self, name: str) -> Dict:
        vps = await self.db.get_vps(name)
        if not vps:
            return {"ok": False, "error": "not_found"}
        if self.backend == "lxc":
            ok, out = await asyncio.to_thread(_run, f"lxc-start -n {name} -d")
            if not ok:
                return {"ok": False, "error": out}
        await self.db.update_vps(name, status="running")
        await self.db.add_log(vps["owner_id"], "start", name)
        return {"ok": True}

    async def stop(self, name: str) -> Dict:
        vps = await self.db.get_vps(name)
        if not vps:
            return {"ok": False, "error": "not_found"}
        if self.backend == "lxc":
            ok, out = await asyncio.to_thread(_run, f"lxc-stop -n {name}")
            if not ok:
                return {"ok": False, "error": out}
        await self.db.update_vps(name, status="stopped")
        await self.db.add_log(vps["owner_id"], "stop", name)
        return {"ok": True}

    async def restart(self, name: str) -> Dict:
        vps = await self.db.get_vps(name)
        if not vps:
            return {"ok": False, "error": "not_found"}
        if self.backend == "lxc":
            _run(f"lxc-stop -n {name}")
            ok, out = _run(f"lxc-start -n {name} -d")
            if not ok:
                return {"ok": False, "error": out}
        await self.db.update_vps(name, status="running")
        await self.db.add_log(vps["owner_id"], "restart", name)
        return {"ok": True}

    async def destroy(self, name: str) -> Dict:
        vps = await self.db.get_vps(name)
        if not vps:
            return {"ok": False, "error": "not_found"}
        if self.backend == "lxc":
            _run(f"lxc-stop -n {name}")
            ok, out = _run(f"lxc-destroy -n {name}")
            if not ok:
                return {"ok": False, "error": out}
            # remove port-forward
            if vps.get("ssh_port"):
                _run(f"iptables -t nat -D PREROUTING -p tcp --dport {vps['ssh_port']} -j DNAT --to-destination {vps['ip']}:22 2>/dev/null")
        await self.db.update_vps(name, status="deleted")
        await self.db.delete_vps(name)
        await self.db.add_log(vps["owner_id"], "delete", name)
        return {"ok": True}

    async def rebuild(self, name: str) -> Dict:
        vps = await self.db.get_vps(name)
        if not vps:
            return {"ok": False, "error": "not_found"}
        owner_id = vps["owner_id"]
        os_key = vps["os_template"]
        cpu, ram, disk = vps["cpu"], vps["ram"], vps["disk"]
        hours_left = 24  # default rebuild gives 24h

        await self.destroy(name)
        result = await self.deploy(owner_id, os_key, cpu, ram, disk, hours_left)
        if result["ok"]:
            await self.db.add_log(owner_id, "rebuild", result["vps"]["name"])
        return result

    async def extend(self, name: str, hours: int) -> Dict:
        vps = await self.db.get_vps(name)
        if not vps:
            return {"ok": False, "error": "not_found"}
        if not vps["expires_at"]:
            new_exp = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            old = datetime.strptime(vps["expires_at"], "%Y-%m-%d %H:%M:%S")
            new_exp = (old + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        await self.db.update_vps(name, expires_at=new_exp)
        await self.db.add_log(vps["owner_id"], "extend", name, f"+{hours}h")
        return {"ok": True, "expires_at": new_exp}

    async def info(self, name: str) -> Optional[Dict]:
        vps = await self.db.get_vps(name)
        if not vps:
            return None
        if self.backend == "lxc" and vps["status"] == "running":
            ok, out = _run(f"lxc-info -n {name} -H")
            if ok:
                vps["lxc_info"] = out
        return vps

    async def cleanup_expired(self) -> int:
        expired = await self.db.get_expired_vps()
        count = 0
        for v in expired:
            await self.destroy(v["name"])
            count += 1
        if count:
            log.info("Cleaned up %d expired VPS", count)
        return count

    # ── LXC backend ────────────────────────────────────────────
    def _deploy_lxc(self, vps: Dict) -> Dict:
        with _lock:
            name = vps["name"]
            tpl = config.OS_TEMPLATES[vps["os_template"]]

            # get IP & port
            all_vps = asyncio.get_event_loop().run_until_complete(self.db.get_all_vps())
            used_ips = [v["ip"] for v in all_vps if v.get("ip")]
            used_ports = [v["ssh_port"] for v in all_vps if v.get("ssh_port")]
            ip = _next_ip(used_ips)
            ssh_port = _next_ssh_port(used_ports)
            if not ip:
                return {"ok": False, "error": "No IP addresses available"}

            # create container
            ok, out = _run(
                f"lxc-create -n {name} -t download -- "
                f"-d {tpl['distro']} -r {tpl['release']} -a {tpl['arch']} --no-validate",
                timeout=600,
            )
            if not ok:
                return {"ok": False, "error": f"lxc-create failed: {out}"}

            # configure
            conf_path = f"/var/lib/lxc/{name}/config"
            extra = f"""
lxc.cgroup2.cpuset.cpus = 0-{vps['cpu']-1}
lxc.cgroup2.memory.max = {vps['ram']}M
lxc.rootfs.size = {vps['disk']}G
lxc.net.0.type = veth
lxc.net.0.link = {config.LXC_BRIDGE}
lxc.net.0.flags = up
lxc.net.0.name = eth0
lxc.net.0.ipv4.address = {ip}/{self._netmask()}
lxc.net.0.ipv4.gateway = {config.LXC_GATEWAY}
"""
            try:
                with open(conf_path, "a") as f:
                    f.write(extra)
            except Exception as e:
                _run(f"lxc-destroy -n {name}")
                return {"ok": False, "error": f"Config write failed: {e}"}

            # set root password
            rootfs = f"/var/lib/lxc/{name}/rootfs"
            ok, _ = _run(f"chroot {rootfs} bash -c 'echo root:{config.SSH_DEFAULT_PASSWORD} | chpasswd'")
            if not ok:
                log.warning("Could not set root password for %s", name)

            # ensure sshd
            _run(f"chroot {rootfs} bash -c 'which sshd || (apt-get update -qq && apt-get install -y -qq openssh-server)' 2>/dev/null", timeout=300)
            _run(f"chroot {rootfs} bash -c 'sed -i \"s/#PermitRootLogin.*/PermitRootLogin yes/\" /etc/ssh/sshd_config 2>/dev/null'")
            _run(f"chroot {rootfs} bash -c 'sed -i \"s/PermitRootLogin no/PermitRootLogin yes/\" /etc/ssh/sshd_config 2>/dev/null'")

            # start
            ok, out = _run(f"lxc-start -n {name} -d")
            if not ok:
                _run(f"lxc-destroy -n {name}")
                return {"ok": False, "error": f"lxc-start failed: {out}"}

            # port-forward
            _run(f"iptables -t nat -A PREROUTING -p tcp --dport {ssh_port} -j DNAT --to-destination {ip}:22")

            return {"ok": True, "ip": ip, "ssh_port": ssh_port}

    def _netmask(self) -> str:
        try:
            net = ipaddress.ip_network(f"{config.LXC_IP_RANGE_START}/{config.LXC_GATEWAY}", strict=False)
            return str(net.netmask)
        except Exception:
            return "255.255.255.0"

    # ── Mock backend ───────────────────────────────────────────
    def _deploy_mock(self, vps: Dict) -> Dict:
        import time
        time.sleep(1)  # simulate work
        fake_ip = f"10.0.3.{random.randint(100, 200)}"
        all_vps = asyncio.get_event_loop().run_until_complete(self.db.get_all_vps())
        used_ports = [v["ssh_port"] for v in all_vps if v.get("ssh_port")]
        ssh_port = _next_ssh_port(used_ports)
        return {"ok": True, "ip": fake_ip, "ssh_port": ssh_port}


# global singleton — set after db is initialised
deployer: Optional[Deployer] = None

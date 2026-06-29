#!/usr/bin/env python3
"""
ZenVPS — Production Discord VPS Deploy Bot
Built by ZenDevelopment  ·  www.zendevelopment.in
"""

import asyncio
import logging
import os
import sys
import threading
import traceback
from datetime import datetime

import discord
from discord import app_commands, Embed, Interaction, ButtonStyle, SelectOption
from discord.ext import commands
from discord.ui import View, Modal, TextInput, Button, Select

import config
from database import db
from deployer import deployer

# ── logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=config.LOG_MAX_SIZE, backupCount=config.LOG_BACKUP_COUNT
        ),
    ],
)
log = logging.getLogger("zenvps.bot")


# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def is_admin(user: discord.User | discord.Member) -> bool:
    return user.id in config.ADMIN_DISCORD_IDS


def is_banned_check(user: discord.User) -> bool:
    # sync check against cached data — we check DB in commands
    return False


def embed_base(title: str = "", **kwargs) -> Embed:
    e = Embed(
        title=title or config.BOT_NAME,
        color=kwargs.pop("color", config.COLOR_PRIMARY),
        **kwargs,
    )
    e.set_footer(text="ZenVPS · zendevelopment.in", icon_url=config.BOT_LOGO)
    e.set_thumbnail(url=config.BOT_LOGO)
    return e


def status_badge(status: str) -> str:
    m = {"running": "🟢", "stopped": "🔴", "creating": "🟡", "failed": "⛔", "deleted": "⚫"}
    return m.get(status, "⚪")


def fmt_expiry(expires_at: str) -> str:
    if not expires_at:
        return "Never"
    try:
        dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        diff = dt - datetime.utcnow()
        if diff.total_seconds() <= 0:
            return "⚠️ Expired"
        hours = int(diff.total_seconds() // 3600)
        mins = int((diff.total_seconds() % 3600) // 60)
        return f"{hours}h {mins}m"
    except Exception:
        return expires_at


# ══════════════════════════════════════════════════════════════════
#  UI COMPONENTS
# ══════════════════════════════════════════════════════════════════

class DeployModal(Modal, title="Deploy New VPS"):
    def __init__(self):
        super().__init__()
        self.add_item(TextInput(
            label="VPS Name (optional, auto-generated if blank)",
            placeholder="my-server",
            required=False,
            max_length=20,
            custom_id="dep_name",
        ))
        self.add_item(TextInput(
            label="OS Template Key",
            placeholder="ubuntu-22.04",
            required=True,
            custom_id="dep_os",
        ))
        self.add_item(TextInput(
            label="CPU Cores",
            placeholder="1",
            required=True,
            custom_id="dep_cpu",
        ))
        self.add_item(TextInput(
            label="RAM (MB)",
            placeholder="512",
            required=True,
            custom_id="dep_ram",
        ))
        self.add_item(TextInput(
            label="Disk (GB)",
            placeholder="5",
            required=True,
            custom_id="dep_disk",
        ))
        self.add_item(TextInput(
            label="Expiry Hours",
            placeholder="72",
            required=True,
            custom_id="dep_hours",
        ))

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        # Check ban
        user = await db.get_or_create_user(uid, interaction.user.name)
        if user["is_banned"]:
            return await interaction.followup.send("❌ You are banned from deploying VPS.", ephemeral=True)

        os_key = self.children[1].value.strip().lower()
        if os_key not in config.OS_TEMPLATES:
            return await interaction.followup.send(
                f"❌ Invalid OS. Available: {', '.join(config.OS_TEMPLATES.keys())}", ephemeral=True
            )

        try:
            cpu = int(self.children[2].value)
            ram = int(self.children[3].value)
            disk = int(self.children[4].value)
            hours = int(self.children[5].value)
        except ValueError:
            return await interaction.followup.send("❌ CPU, RAM, Disk, and Hours must be numbers.", ephemeral=True)

        cpu = max(1, min(cpu, config.VPS_MAX_CPU))
        ram = max(128, min(ram, config.VPS_MAX_RAM))
        disk = max(1, min(disk, config.VPS_MAX_DISK))
        hours = max(1, min(hours, 720))

        await interaction.followup.send(config.MSG_DEPLOYING, ephemeral=True)

        result = await deployer.deploy(uid, os_key, cpu, ram, disk, hours)
        if result["ok"]:
            v = result["vps"]
            e = embed_base("✅ VPS Deployed!", color=config.COLOR_SUCCESS)
            e.add_field(name="Name", value=f"`{v['name']}`", inline=True)
            e.add_field(name="OS", value=config.OS_TEMPLATES.get(v["os_template"], {}).get("display", v["os_template"]), inline=True)
            e.add_field(name="Specs", value=f"{v['cpu']} CPU · {v['ram']}MB RAM · {v['disk']}GB Disk", inline=False)
            e.add_field(name="IP Address", value=f"`{v['ip'] or 'Assigning...'}`", inline=True)
            e.add_field(name="SSH Port", value=f"`{v['ssh_port'] or '...'}`", inline=True)
            e.add_field(name="Expires In", value=fmt_expiry(v["expires_at"]), inline=True)
            if v["ip"] and v["ssh_port"]:
                e.add_field(name="SSH Command", value=f"`ssh root@{config.VPS_HOST_IP} -p {v['ssh_port']}`", inline=False)
                e.add_field(name="Root Password", value=f"`{config.SSH_DEFAULT_PASSWORD}`", inline=False)
            await interaction.followup.send(embed=e, ephemeral=True)
        else:
            err = result.get("error", "unknown")
            if err == "limit":
                await interaction.followup.send(config.MSG_VPS_LIMIT.format(max=result.get("max", "?")), ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Deploy failed: {err}", ephemeral=True)


class VPSControlView(View):
    """Persistent view with VPS control buttons."""
    def __init__(self, vps_name: str, owner_id: str):
        super().__init__(timeout=None)
        self.vps_name = vps_name
        self.owner_id = owner_id

    async def interaction_check(self, interaction: Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id and not is_admin(interaction.user):
            await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
            return False
        return True

    @button(label="Start", style=ButtonStyle.success, custom_id="vps_start")
    async def btn_start(self, interaction: Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        r = await deployer.start(self.vps_name)
        msg = "✅ Started" if r["ok"] else f"❌ {r.get('error','')}"
        await interaction.followup.send(msg, ephemeral=True)

    @button(label="Stop", style=ButtonStyle.danger, custom_id="vps_stop")
    async def btn_stop(self, interaction: Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        r = await deployer.stop(self.vps_name)
        msg = "✅ Stopped" if r["ok"] else f"❌ {r.get('error','')}"
        await interaction.followup.send(msg, ephemeral=True)

    @button(label="Restart", style=ButtonStyle.primary, custom_id="vps_restart")
    async def btn_restart(self, interaction: Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        r = await deployer.restart(self.vps_name)
        msg = "✅ Restarted" if r["ok"] else f"❌ {r.get('error','')}"
        await interaction.followup.send(msg, ephemeral=True)

    @button(label="Info", style=ButtonStyle.secondary, custom_id="vps_info")
    async def btn_info(self, interaction: Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        v = await deployer.info(self.vps_name)
        if not v:
            return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
        e = embed_base(f"Server: {v['name']}", color=config.COLOR_INFO)
        e.add_field(name="Status", value=f"{status_badge(v['status'])} {v['status'].upper()}", inline=True)
        e.add_field(name="OS", value=config.OS_TEMPLATES.get(v["os_template"], {}).get("display", v["os_template"]), inline=True)
        e.add_field(name="Specs", value=f"{v['cpu']}vCPU · {v['ram']}MB · {v['disk']}GB", inline=True)
        e.add_field(name="IP", value=f"`{v['ip'] or 'N/A'}`", inline=True)
        e.add_field(name="SSH Port", value=f"`{v['ssh_port'] or 'N/A'}`", inline=True)
        e.add_field(name="Expires", value=fmt_expiry(v["expires_at"]), inline=True)
        if v.get("lxc_info"):
            e.add_field(name="LXC Info", value=f"```\n{v['lxc_info'][:500]}\n```", inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @button(label="Delete", style=ButtonStyle.danger, custom_id="vps_delete")
    async def btn_delete(self, interaction: Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        r = await deployer.destroy(self.vps_name)
        msg = "✅ Deleted" if r["ok"] else f"❌ {r.get('error','')}"
        await interaction.followup.send(msg, ephemeral=True)
        self.stop()


class VPSSelectView(View):
    """View to select a VPS and open its control panel."""
    def __init__(self, vps_list: list, owner_id: str):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        opts = [
            SelectOption(
                label=f"{v['name']} — {status_badge(v['status'])} {v['status']}",
                value=v["name"],
                description=f"{v['os_template']} · {v['cpu']}vCPU · {v['ram']}MB",
            )
            for v in vps_list[:25]
        ]
        self.add_item(Select(placeholder="Select a VPS…", options=opts, custom_id="vps_select"))

    async def interaction_check(self, interaction: Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id and not is_admin(interaction.user):
            await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: Interaction, select: Select):
        name = select.values[0]
        v = await deployer.info(name)
        if not v:
            return await interaction.response.send_message(config.MSG_VPS_NOT_FOUND, ephemeral=True)
        view = VPSControlView(name, self.owner_id)
        e = embed_base(f"Server: {v['name']}", color=config.COLOR_INFO)
        e.add_field(name="Status", value=f"{status_badge(v['status'])} {v['status'].upper()}", inline=True)
        e.add_field(name="OS", value=config.OS_TEMPLATES.get(v["os_template"], {}).get("display", v["os_template"]), inline=True)
        e.add_field(name="Specs", value=f"{v['cpu']}vCPU · {v['ram']}MB · {v['disk']}GB", inline=True)
        e.add_field(name="IP", value=f"`{v['ip'] or 'N/A'}`", inline=True)
        e.add_field(name="SSH Port", value=f"`{v['ssh_port'] or 'N/A'}`", inline=True)
        e.add_field(name="Expires", value=fmt_expiry(v["expires_at"]), inline=True)
        if v["ip"] and v["ssh_port"]:
            e.add_field(name="SSH", value=f"`ssh root@{config.VPS_HOST_IP} -p {v['ssh_port']}`", inline=False)
            e.add_field(name="Password", value=f"`{config.SSH_DEFAULT_PASSWORD}`", inline=False)
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)

    # This workaround needed because Select callback is on the Select item, not the View in dpy 2.x
    # We handle it by assigning in __init__ — but the proper way:
    # Actually in dpy 2.x, Select callbacks go to the View's callback if decorated.
    # Let me handle it properly:

# Fix: override the select's callback
def _make_select_callback(owner_id: str):
    async def callback(interaction: Interaction, select: Select):
        name = select.values[0]
        v = await deployer.info(name)
        if not v:
            return await interaction.response.send_message(config.MSG_VPS_NOT_FOUND, ephemeral=True)
        view = VPSControlView(name, owner_id)
        e = embed_base(f"Server: {v['name']}", color=config.COLOR_INFO)
        e.add_field(name="Status", value=f"{status_badge(v['status'])} {v['status'].upper()}", inline=True)
        e.add_field(name="OS", value=config.OS_TEMPLATES.get(v["os_template"], {}).get("display", v["os_template"]), inline=True)
        e.add_field(name="Specs", value=f"{v['cpu']}vCPU · {v['ram']}MB · {v['disk']}GB", inline=True)
        e.add_field(name="IP", value=f"`{v['ip'] or 'N/A'}`", inline=True)
        e.add_field(name="SSH Port", value=f"`{v['ssh_port'] or 'N/A'}`", inline=True)
        e.add_field(name="Expires", value=fmt_expiry(v["expires_at"]), inline=True)
        if v["ip"] and v["ssh_port"]:
            e.add_field(name="SSH", value=f"`ssh root@{config.VPS_HOST_IP} -p {v['ssh_port']}`", inline=False)
            e.add_field(name="Password", value=f"`{config.SSH_DEFAULT_PASSWORD}`", inline=False)
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)
    return callback


# ══════════════════════════════════════════════════════════════════
#  BOT SETUP
# ══════════════════════════════════════════════════════════════════

class ZenVPSBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(
            command_prefix=config.BOT_PREFIX,
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=config.BOT_ACTIVITY_TEXT,
            ),
            status=getattr(discord.Status, config.BOT_STATUS, discord.Status.online),
        )

    async def setup_hook(self):
        await self.tree.sync()
        log.info("Slash commands synced")

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user.name, self.user.id)
        log.info("Dashboard: http://%s:%d", config.DASHBOARD_HOST, config.DASHBOARD_PORT)

    async def on_error(self, event, *args, **kwargs):
        log.error("Error in %s: %s", event, traceback.format_exc())


bot = ZenVPSBot()


# ══════════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ══════════════════════════════════════════════════════════════════

# ── /deploy ───────────────────────────────────────────────────────
@bot.tree.command(name="deploy", description="Deploy a new VPS server")
async def cmd_deploy(interaction: Interaction):
    await interaction.response.send_modal(DeployModal())


# ── /panel ────────────────────────────────────────────────────────
@bot.tree.command(name="panel", description="Open your VPS control panel")
async def cmd_panel(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    user = await db.get_or_create_user(uid, interaction.user.name)
    if user["is_banned"]:
        return await interaction.followup.send("❌ You are banned.", ephemeral=True)

    vps_list = await db.get_user_vps(uid)
    if not vps_list:
        e = embed_base("No VPS Found", color=config.COLOR_WARNING)
        e.description = f"You have no VPS. Use `/deploy` to create one.\n**Limit:** {user['vps_count']}/{user['max_vps']}"
        return await interaction.followup.send(embed=e, ephemeral=True)

    view = View(timeout=120)
    opts = [
        SelectOption(
            label=f"{v['name']} — {status_badge(v['status'])} {v['status']}",
            value=v["name"],
            description=f"{v['os_template']} · {v['cpu']}vCPU · {v['ram']}MB",
        )
        for v in vps_list[:25]
    ]
    select = Select(placeholder="Select a VPS to manage…", options=opts)
    cb = _make_select_callback(uid)
    select.callback = cb
    view.add_item(select)

    e = embed_base("VPS Control Panel", color=config.COLOR_PRIMARY)
    e.description = f"Select a server below to manage it.\n**Your VPS:** {user['vps_count']}/{user['max_vps']}"
    await interaction.followup.send(embed=e, view=view, ephemeral=True)


# ── /vps group ────────────────────────────────────────────────────
vps_group = app_commands.Group(name="vps", description="VPS management commands")


@vps_group.command(name="list", description="List all your VPS servers")
async def cmd_vps_list(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    vps_list = await db.get_user_vps(uid)
    if not vps_list:
        e = embed_base("No VPS", color=config.COLOR_WARNING)
        e.description = "You don't have any VPS. Use `/deploy` to create one."
        return await interaction.followup.send(embed=e, ephemeral=True)

    e = embed_base(f"Your VPS ({len(vps_list)})", color=config.COLOR_PRIMARY)
    for v in vps_list:
        os_name = config.OS_TEMPLATES.get(v["os_template"], {}).get("display", v["os_template"])
        e.add_field(
            name=f"{status_badge(v['status'])} `{v['name']}`",
            value=f"{os_name} · {v['cpu']}vCPU · {v['ram']}MB · {v['disk']}GB\nIP: `{v['ip'] or 'N/A'}` · Port: `{v['ssh_port'] or 'N/A'}` · Expires: {fmt_expiry(v['expires_at'])}",
            inline=False,
        )
    await interaction.followup.send(embed=e, ephemeral=True)


@vps_group.command(name="info", description="Get detailed info about a VPS")
@app_commands.describe(name="VPS name")
async def cmd_vps_info(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    v = await deployer.info(name)
    e = embed_base(f"Server: {v['name']}", color=config.COLOR_INFO)
    e.add_field(name="Status", value=f"{status_badge(v['status'])} {v['status'].upper()}", inline=True)
    e.add_field(name="OS", value=config.OS_TEMPLATES.get(v["os_template"], {}).get("display", v["os_template"]), inline=True)
    e.add_field(name="Specs", value=f"{v['cpu']}vCPU · {v['ram']}MB · {v['disk']}GB", inline=True)
    e.add_field(name="IP", value=f"`{v['ip'] or 'N/A'}`", inline=True)
    e.add_field(name="SSH Port", value=f"`{v['ssh_port'] or 'N/A'}`", inline=True)
    e.add_field(name="Created", value=v["created_at"] or "N/A", inline=True)
    e.add_field(name="Expires", value=fmt_expiry(v["expires_at"]), inline=True)
    if v["ip"] and v["ssh_port"]:
        e.add_field(name="SSH", value=f"`ssh root@{config.VPS_HOST_IP} -p {v['ssh_port']}`", inline=False)
        e.add_field(name="Password", value=f"`{config.SSH_DEFAULT_PASSWORD}`", inline=False)
    if v.get("lxc_info"):
        e.add_field(name="LXC Info", value=f"```\n{v['lxc_info'][:800]}\n```", inline=False)
    await interaction.followup.send(embed=e, ephemeral=True)


@vps_group.command(name="start", description="Start a stopped VPS")
@app_commands.describe(name="VPS name")
async def cmd_vps_start(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    r = await deployer.start(name)
    await interaction.followup.send("✅ VPS started." if r["ok"] else f"❌ {r.get('error','')}", ephemeral=True)


@vps_group.command(name="stop", description="Stop a running VPS")
@app_commands.describe(name="VPS name")
async def cmd_vps_stop(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    r = await deployer.stop(name)
    await interaction.followup.send("✅ VPS stopped." if r["ok"] else f"❌ {r.get('error','')}", ephemeral=True)


@vps_group.command(name="restart", description="Restart a VPS")
@app_commands.describe(name="VPS name")
async def cmd_vps_restart(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    r = await deployer.restart(name)
    await interaction.followup.send("✅ VPS restarted." if r["ok"] else f"❌ {r.get('error','')}", ephemeral=True)


@vps_group.command(name="delete", description="Permanently delete a VPS")
@app_commands.describe(name="VPS name")
async def cmd_vps_delete(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    r = await deployer.destroy(name)
    await interaction.followup.send("✅ VPS deleted permanently." if r["ok"] else f"❌ {r.get('error','')}", ephemeral=True)


@vps_group.command(name="rebuild", description="Rebuild a VPS (destroys and redeploys)")
@app_commands.describe(name="VPS name")
async def cmd_vps_rebuild(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    await interaction.followup.send("🔄 Rebuilding VPS…", ephemeral=True)
    r = await deployer.rebuild(name)
    if r["ok"]:
        nv = r["vps"]
        e = embed_base("✅ VPS Rebuilt!", color=config.COLOR_SUCCESS)
        e.add_field(name="New Name", value=f"`{nv['name']}`", inline=True)
        e.add_field(name="IP", value=f"`{nv['ip'] or '...'}`", inline=True)
        e.add_field(name="SSH Port", value=f"`{nv['ssh_port'] or '...'}`", inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Rebuild failed: {r.get('error','')}", ephemeral=True)


@vps_group.command(name="extend", description="Extend VPS expiry time")
@app_commands.describe(name="VPS name", hours="Additional hours")
async def cmd_vps_extend(interaction: Interaction, name: str, hours: int):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    hours = max(1, min(hours, 720))
    r = await deployer.extend(name, hours)
    if r["ok"]:
        await interaction.followup.send(f"✅ Extended by {hours}h. New expiry: {fmt_expiry(r['expires_at'])}", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {r.get('error','')}", ephemeral=True)


@vps_group.command(name="console", description="Get SSH connection details for a VPS")
@app_commands.describe(name="VPS name")
async def cmd_vps_console(interaction: Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    v = await db.get_vps(name)
    if not v or (v["owner_id"] != uid and not is_admin(interaction.user)):
        return await interaction.followup.send(config.MSG_VPS_NOT_FOUND, ephemeral=True)
    e = embed_base(f"Console: {v['name']}", color=config.COLOR_INFO)
    if v["ip"] and v["ssh_port"]:
        e.add_field(name="SSH Command", value=f"`ssh root@{config.VPS_HOST_IP} -p {v['ssh_port']}`", inline=False)
        e.add_field(name="Password", value=f"`{config.SSH_DEFAULT_PASSWORD}`", inline=False)
        e.add_field(name="Direct IP", value=f"`{v['ip']}`", inline=True)
        e.add_field(name="Status", value=f"{status_badge(v['status'])} {v['status']}", inline=True)
    else:
        e.description = "VPS IP/Port not yet assigned. It may still be creating."
    await interaction.followup.send(embed=e, ephemeral=True)


bot.tree.add_command(vps_group)


# ── /stats ────────────────────────────────────────────────────────
@bot.tree.command(name="stats", description="View system resource usage")
async def cmd_stats(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    import psutil
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    stats = await db.stats()
    e = embed_base("System Statistics", color=config.COLOR_PRIMARY)
    e.add_field(name="🟢 CPU", value=f"{cpu}%", inline=True)
    e.add_field(name="🟡 RAM", value=f"{mem.used//1024//1024}MB / {mem.total//1024//1024}MB ({mem.percent}%)", inline=True)
    e.add_field(name="🔴 Disk", value=f"{disk.used//1024//1024//1024}GB / {disk.total//1024//1024//1024}GB ({disk.percent}%)", inline=True)
    e.add_field(name="Total VPS", value=str(stats["total_vps"]), inline=True)
    e.add_field(name="Active VPS", value=str(stats["active_vps"]), inline=True)
    e.add_field(name="Users", value=str(stats["total_users"]), inline=True)
    await interaction.followup.send(embed=e, ephemeral=True)


# ── /templates ────────────────────────────────────────────────────
@bot.tree.command(name="templates", description="List available OS templates")
async def cmd_templates(interaction: Interaction):
    e = embed_base("Available OS Templates", color=config.COLOR_PRIMARY)
    for key, tpl in config.OS_TEMPLATES.items():
        e.add_field(name=tpl["display"], value=f"`{key}`", inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


# ── /help ─────────────────────────────────────────────────────────
@bot.tree.command(name="help", description="Show all available commands")
async def cmd_help(interaction: Interaction):
    e = embed_base("ZenVPS — Command List", color=config.COLOR_PRIMARY)
    e.description = (
        "**User Commands**\n"
        "• `/deploy` — Deploy a new VPS server\n"
        "• `/panel` — Open your VPS control panel\n"
        "• `/vps list` — List all your VPS\n"
        "• `/vps info <name>` — VPS details\n"
        "• `/vps start <name>` — Start a VPS\n"
        "• `/vps stop <name>` — Stop a VPS\n"
        "• `/vps restart <name>` — Restart a VPS\n"
        "• `/vps delete <name>` — Delete a VPS\n"
        "• `/vps rebuild <name>` — Rebuild a VPS\n"
        "• `/vps extend <name> <hours>` — Extend expiry\n"
        "• `/vps console <name>` — SSH connection info\n"
        "• `/stats` — System resource usage\n"
        "• `/templates` — List OS templates\n\n"
        "**Admin Commands**\n"
        "• `/admin list` — List ALL VPS\n"
        "• `/admin user <id> ban|unban` — Ban/unban user\n"
        "• `/admin limit <id> <number>` — Set VPS limit\n"
        "• `/admin cleanup` — Delete expired VPS\n"
        "• `/admin broadcast <msg>` — DM all users\n"
    )
    await interaction.response.send_message(embed=e, ephemeral=True)


# ══════════════════════════════════════════════════════════════════
#  ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════════

admin_group = app_commands.Group(name="admin", description="Admin-only commands")


def admin_only(interaction: Interaction) -> bool:
    if not is_admin(interaction.user):
        return False
    return True


@admin_group.command(name="list", description="List ALL VPS on the system (admin only)")
async def cmd_admin_list(interaction: Interaction):
    if not admin_only(interaction):
        return await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    all_vps = await db.get_all_vps()
    if not all_vps:
        return await interaction.followup.send("No VPS found.", ephemeral=True)
    e = embed_base(f"All VPS ({len(all_vps)})", color=config.COLOR_PRIMARY)
    for v in all_vps[:25]:
        e.add_field(
            name=f"{status_badge(v['status'])} `{v['name']}` — <@{v['owner_id']}>",
            value=f"{v['os_template']} · {v['cpu']}vCPU · {v['ram']}MB · IP: `{v['ip'] or 'N/A'}` · Expires: {fmt_expiry(v['expires_at'])}",
            inline=False,
        )
    if len(all_vps) > 25:
        e.set_footer(text=f"Showing 25 of {len(all_vps)} · zendevelopment.in", icon_url=config.BOT_LOGO)
    await interaction.followup.send(embed=e, ephemeral=True)


@admin_group.command(name="user", description="Manage a user (admin only)")
@app_commands.describe(discord_id="User Discord ID", action="ban or unban")
async def cmd_admin_user(interaction: Interaction, discord_id: str, action: str):
    if not admin_only(interaction):
        return await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    action = action.lower().strip()
    if action == "ban":
        await db.set_ban(discord_id, True)
        await db.add_log(str(interaction.user.id), "admin_ban", discord_id)
        await interaction.followup.send(f"✅ Banned user {discord_id}", ephemeral=True)
    elif action == "unban":
        await db.set_ban(discord_id, False)
        await db.add_log(str(interaction.user.id), "admin_unban", discord_id)
        await interaction.followup.send(f"✅ Unbanned user {discord_id}", ephemeral=True)
    else:
        await interaction.followup.send("❌ Action must be `ban` or `unban`.", ephemeral=True)


@admin_group.command(name="limit", description="Set a user's VPS limit (admin only)")
@app_commands.describe(discord_id="User Discord ID", limit="Max VPS count")
async def cmd_admin_limit(interaction: Interaction, discord_id: str, limit: int):
    if not admin_only(interaction):
        return await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    limit = max(0, min(limit, 50))
    await db.set_max_vps(discord_id, limit)
    await db.add_log(str(interaction.user.id), "admin_limit", discord_id, f"limit={limit}")
    await interaction.followup.send(f"✅ Set {discord_id} VPS limit to {limit}", ephemeral=True)


@admin_group.command(name="cleanup", description="Delete all expired VPS (admin only)")
async def cmd_admin_cleanup(interaction: Interaction):
    if not admin_only(interaction):
        return await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    count = await deployer.cleanup_expired()
    await db.add_log(str(interaction.user.id), "admin_cleanup", "", f"deleted={count}")
    await interaction.followup.send(f"✅ Cleaned up {count} expired VPS.", ephemeral=True)


@admin_group.command(name="broadcast", description="Send a DM to all users (admin only)")
@app_commands.describe(message="Message to send")
async def cmd_admin_broadcast(interaction: Interaction, message: str):
    if not admin_only(interaction):
        return await interaction.response.send_message(config.MSG_NO_PERMISSION, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    users = await db.get_all_users()
    sent, failed = 0, 0
    for u in users:
        try:
            user = await bot.fetch_user(int(u["discord_id"]))
            e = embed_base(f"📢 Message from {config.BOT_NAME}", color=config.COLOR_PRIMARY)
            e.description = message
            await user.send(embed=e)
            sent += 1
        except Exception:
            failed += 1
    await db.add_log(str(interaction.user.id), "admin_broadcast", "", f"sent={sent} failed={failed}")
    await interaction.followup.send(f"✅ Broadcast sent to {sent} users ({failed} failed).", ephemeral=True)


bot.tree.add_command(admin_group)


# ══════════════════════════════════════════════════════════════════
#  AUTO-CLEANUP TASK
# ══════════════════════════════════════════════════════════════════

async def auto_cleanup():
    """Background task: clean expired VPS every 30 minutes."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            count = await deployer.cleanup_expired()
            if count:
                log.info("Auto-cleanup: removed %d expired VPS", count)
        except Exception as e:
            log.error("Auto-cleanup error: %s", e)
        await asyncio.sleep(1800)  # 30 min


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

async def main():
    # Init database
    await db.connect()

    # Init deployer
    from deployer import Deployer
    global deployer
    deployer = Deployer(db)

    # Start dashboard in background thread
    if config.DASHBOARD_ENABLED:
        from dashboard import run_dashboard_thread
        dash_thread = threading.Thread(
            target=run_dashboard_thread,
            args=(db, deployer),
            daemon=True,
        )
        dash_thread.start()
        log.info("Dashboard thread started")

    # Start bot
    async with bot:
        bot.loop.create_task(auto_cleanup())
        await bot.start(config.BOT_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down…")
    finally:
        asyncio.run(db.close())

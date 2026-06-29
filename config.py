# ╔══════════════════════════════════════════════════════════════════╗
# ║              ZENDEVELOPMENT — ZenVPS Bot Config                 ║
# ║         Modify all settings here. Do NOT edit other files.       ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── Bot ────────────────────────────────────────────────────────────
BOT_TOKEN            = "YOUR_BOT_TOKEN_HERE"
BOT_NAME             = "ZenVPS"
BOT_LOGO             = "https://www.zendevelopment.in/logo.png"
BOT_ACTIVITY_TEXT    = "Managing VPS Servers"
BOT_STATUS           = "online"          # online | idle | dnd | invisible

# ── Admins ─────────────────────────────────────────────────────────
ADMIN_DISCORD_IDS    = [123456789012345678]   # ← YOUR DISCORD ID
ADMIN_ROLE_ID        = None                     # Optional role-based admin

# ── Web Dashboard ──────────────────────────────────────────────────
DASHBOARD_ENABLED    = True
DASHBOARD_HOST       = "0.0.0.0"
DASHBOARD_PORT       = 8080
DASHBOARD_USERNAME   = "admin"
DASHBOARD_PASSWORD   = "CHANGE_ME_SECURE_PASSWORD"
DASHBOARD_SECRET_KEY = "CHANGE_THIS_TO_A_RANDOM_64_CHAR_STRING"

# ── VPS Engine ─────────────────────────────────────────────────────
# "lxc"  – real LXC containers (requires lxc installed on host)
# "mock" – simulated VPS for testing without LXC
DEPLOY_BACKEND       = "mock"

# Resource defaults & limits
VPS_DEFAULT_CPU      = 1
VPS_DEFAULT_RAM      = 512        # MB
VPS_DEFAULT_DISK     = 5          # GB
VPS_MAX_CPU          = 4
VPS_MAX_RAM          = 4096       # MB
VPS_MAX_DISK         = 50         # GB
VPS_DEFAULT_EXPIRY_HOURS = 72
VPS_MAX_PER_USER     = 3
VPS_NAME_PREFIX      = "zen"
VPS_HOST_IP          = "YOUR_HOST_PUBLIC_IP"   # For SSH port-forward display

# ── LXC-Specific (only used when DEPLOY_BACKEND = "lxc") ──────────
LXC_BRIDGE           = "lxcbr0"
LXC_IP_RANGE_START   = "10.0.3.100"
LXC_IP_RANGE_END     = "10.0.3.200"
LXC_GATEWAY          = "10.0.3.1"
LXC_DNS              = "8.8.8.8"
SSH_PORT_BASE        = 2200
SSH_DEFAULT_PASSWORD = "zen12345"

# ── OS Templates ───────────────────────────────────────────────────
OS_TEMPLATES = {
    "ubuntu-22.04": {"display": "Ubuntu 22.04 LTS",  "distro": "ubuntu",    "release": "22.04",      "arch": "amd64"},
    "ubuntu-20.04": {"display": "Ubuntu 20.04 LTS",  "distro": "ubuntu",    "release": "20.04",      "arch": "amd64"},
    "debian-12":    {"display": "Debian 12",         "distro": "debian",    "release": "bookworm",   "arch": "amd64"},
    "debian-11":    {"display": "Debian 11",         "distro": "debian",    "release": "bullseye",   "arch": "amd64"},
    "alpine-3.19":  {"display": "Alpine 3.19",      "distro": "alpine",    "release": "3.19",       "arch": "amd64"},
    "centos-9":     {"display": "CentOS 9 Stream",   "distro": "centos",    "release": "9-Stream",   "arch": "amd64"},
    "fedora-39":    {"display": "Fedora 39",         "distro": "fedora",    "release": "39",         "arch": "amd64"},
    "archlinux":    {"display": "Arch Linux",        "distro": "archlinux", "release": "current",    "arch": "amd64"},
}

# ── Database ───────────────────────────────────────────────────────
DATABASE_PATH        = "zenvps.db"

# ── Logging ────────────────────────────────────────────────────────
LOG_LEVEL            = "INFO"
LOG_FILE             = "zenvps.log"

# ── Embed Colours ──────────────────────────────────────────────────
COLOR_PRIMARY        = 0x5865F2
COLOR_SUCCESS        = 0x57F287
COLOR_WARNING        = 0xFEE75C
COLOR_ERROR          = 0xED4245
COLOR_INFO           = 0x5865F2

# ── Messages ───────────────────────────────────────────────────────
MSG_NO_PERMISSION    = "❌ You do not have permission to use this command."
MSG_VPS_LIMIT        = "❌ You have reached your VPS limit ({max})."
MSG_VPS_NOT_FOUND    = "❌ VPS not found."
MSG_INTERNAL_ERROR   = "❌ An internal error occurred. Contact an admin."
MSG_DEPLOYING        = "🔄 Deploying your VPS… This may take a few minutes."
MSG_DEPLOYED         = "✅ VPS deployed successfully!"

🖥️ ZenVPS — Discord VPS Deploy Bot
ZenDevelopment

Production-level Discord bot that deploys & manages VPS servers directly from chat.
Includes a full admin web dashboard.

Built with ❤️ by ZenDevelopment

✨ Features
Feature	Description
VPS Deployment	Deploy LXC containers or mock VPS via Discord slash commands
Full Control Panel	Start, stop, restart, delete, rebuild VPS from Discord UI
Web Dashboard	Admin-only panel at http://your-ip:8080 with live stats
Multi-OS Support	Ubuntu, Debian, Alpine, CentOS, Fedora, Arch Linux
Resource Limits	Configurable CPU, RAM, disk per VPS with hard caps
Auto-Expiry	VPS auto-expire and get cleaned up
User Management	Per-user VPS limits, ban/unban, broadcast DMs
SSH Access	Auto port-forwarding with connection details in embeds
Activity Logging	Full audit trail visible in dashboard
Background Cleanup	Auto-removes expired VPS every 30 minutes
📁 File Structure
├── config.py ← ALL settings (edit this first!)
├── bot.py ← Main Discord bot + commands
├── database.py ← SQLite database layer
├── deployer.py ← VPS deployment engine (LXC / Mock)
├── dashboard.py ← Flask web dashboard
├── requirements.txt ← Python dependencies
├── start.sh ← Start the bot
├── stop.sh ← Stop the bot
├── README.md ← This file
├── zenvps.db ← Database (created automatically)
├── zenvps.log ── Runtime log (created automatically)
└── venv/ ← Python virtual environment

text


---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.10+** installed
- A **Discord Bot Token** (from [Discord Developer Portal](https://discord.com/developers/applications))
- For real LXC deployment: **LXC** installed (`apt install lxc lxc-templates`)

### 2. Clone / Upload

Upload all files (except `venv/`, `zenvps.db`, `zenvps.log`) to your VPS.

### 3. Configure

Edit `config.py` and set **at minimum**:

```python
BOT_TOKEN         = "your_actual_bot_token"
ADMIN_DISCORD_IDS = [your_discord_id]        # YOUR numeric Discord user ID
VPS_HOST_IP       = "your.server.public.ip"  # For SSH display
DASHBOARD_PASSWORD = "a_strong_password"     # Dashboard login
DASHBOARD_SECRET_KEY = "random_string_here"  # Flask session secret
4. Run
bash

chmod +x start.sh stop.sh
./start.sh
5. Stop
bash

./stop.sh
⚙️ Configuration Guide
Deploy Backend
Value
Description
"mock"	Simulated VPS — no LXC required. Great for testing.
"lxc"	Real LXC containers. Requires LXC installed on host.

LXC Setup (for real deployments)
bash

# Install LXC
apt update && apt install -y lxc lxc-templates debootstrap

# Verify
lxc-ls

# The bot uses the default lxcbr0 bridge.
# Ensure it's running:
ip addr show lxcbr0
Key Config Variables
Variable
Default
Description
VPS_MAX_PER_USER	3	Max VPS per user
VPS_DEFAULT_CPU	1	Default CPU cores
VPS_DEFAULT_RAM	512	Default RAM in MB
VPS_DEFAULT_DISK	5	Default disk in GB
VPS_MAX_CPU	4	Maximum allowed CPU
VPS_MAX_RAM	4096	Maximum allowed RAM
VPS_MAX_DISK	50	Maximum allowed disk
VPS_DEFAULT_EXPIRY_HOURS	72	Hours before VPS expires
DASHBOARD_PORT	8080	Web dashboard port
SSH_DEFAULT_PASSWORD	zen12345	Root password for new VPS

🎮 Discord Commands
User Commands
Command
Description
/deploy	Open deployment form (modal)
/panel	Interactive VPS control panel
/vps list	List all your VPS
/vps info <name>	Detailed VPS information
/vps start <name>	Start a VPS
/vps stop <name>	Stop a VPS
/vps restart <name>	Restart a VPS
/vps delete <name>	Permanently delete VPS
/vps rebuild <name>	Destroy and redeploy VPS
/vps extend <name> <hours>	Add hours to expiry
/vps console <name>	Get SSH connection info
/stats	System resource usage
/templates	List available OS templates
/help	Full command reference

Admin Commands
Command
Description
/admin list	List ALL VPS on the system
/admin user <id> ban|unban	Ban or unban a user
/admin limit <id> <number>	Set user's VPS limit
/admin cleanup	Manually delete expired VPS
/admin broadcast <message>	DM all registered users

🌐 Web Dashboard
Access at http://YOUR_SERVER_IP:8080

Login with credentials from config.py
View real-time stats (CPU, RAM, Disk)
Create, start, stop, restart, delete VPS
View activity logs
Auto-refreshes every 15 seconds
🔒 Security Notes
Change DASHBOARD_PASSWORD and DASHBOARD_SECRET_KEY before deploying
Change SSH_DEFAULT_PASSWORD in production
The dashboard is not encrypted — use a reverse proxy (nginx + Let's Encrypt) for HTTPS
Restrict DASHBOARD_PORT with firewall rules if needed
Only admin Discord IDs can use /admin commands and access the dashboard
🛠️ Troubleshooting
Issue
Solution
Bot won't start	Check zenvps.log — usually a bad token or missing dependency
Commands don't appear	Bot needs "applications.commands" scope in invite URL
LXC creation fails	Ensure LXC is installed and lxcbr0 bridge exists
Dashboard not loading	Check if port 8080 is open and not in use
"No IP addresses available"	Expand LXC_IP_RANGE_START to LXC_IP_RANGE_END in config

Discord Invite URL
Generate your bot invite with these scopes:

text

https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=274877975552&scope=bot%20applications.commands
📜 License
This project is provided as-is. Use responsibly.

<p align="center">
<strong>Built by ZenDevelopment</strong><br/>
<a href="https://www.zendevelopment.in">www.zendevelopment.in</a>
</p>
```

How to Deploy — Step by Step
bash

# 1. Upload all files to your VPS (except venv/, *.db, *.log, *.pid)

# 2. Make scripts executable
chmod +x start.sh stop.sh

# 3. Edit config.py with your real values
nano config.py
#    - Set BOT_TOKEN
#    - Set ADMIN_DISCORD_IDS (your Discord ID)
#    - Set VPS_HOST_IP (your server's public IP)
#    - Set DASHBOARD_PASSWORD to something strong
#    - Set DASHBOARD_SECRET_KEY to a random string
#    - Set DEPLOY_BACKEND to "mock" for testing, "lxc" for real

# 4. Start the bot
./start.sh

# 5. Check it's running
tail -f zenvps.log

# 6. Invite your bot to your Discord server using the invite URL from README

# 7. Open dashboard in browser
#    http://YOUR_SERVER_IP:8080
Key points about the architecture:

No Docker, no systemctl — runs directly via nohup in a Python venv
Single process — Flask dashboard runs in a background thread inside the same Python process as the Discord bot
SQLite database — zero external database dependencies, file-based
Mock mode — works immediately without LXC installed, perfect for testing the full Discord UI and dashboard
LXC mode — switch DEPLOY_BACKEND = "lxc" in config when you're ready for real container deployment
Auto-cleanup — background task runs every 30 minutes to remove expired VPS
Thread-safe deployer — uses a threading lock so only one LXC operation runs at a time
All responses are ephemeral — VPS details stay private to the user who requested them



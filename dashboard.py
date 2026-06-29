import logging
import threading
from flask import Flask, request, jsonify, redirect, session, send_string
import hashlib, hmac, json, psutil, time
from datetime import datetime
import config

log = logging.getLogger("zenvps.dashboard")

app = Flask(__name__)
app.secret_key = config.DASHBOARD_SECRET_KEY

# ── auth helpers ──────────────────────────────────────────────────
def _check_auth():
    return session.get("logged_in") is True

def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _check_auth():
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper

# ── reference to bot modules (set from bot.py) ────────────────────
_db = None
_deployer = None

def init_dashboard(db_ref, deployer_ref):
    global _db, _deployer
    _db = db_ref
    _deployer = deployer_ref


# ══════════════════════════════════════════════════════════════════
#  HTML TEMPLATES
# ══════════════════════════════════════════════════════════════════

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZenVPS — Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1e1f22;color:#dbdee1;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#2b2d31;border:1px solid #3f4147;border-radius:12px;padding:40px;width:100%;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,.4)}
.card h1{font-size:22px;margin-bottom:6px;display:flex;align-items:center;gap:10px}
.card h1 img{width:28px;height:28px;border-radius:50%}
.card p.sub{color:#949ba4;font-size:13px;margin-bottom:24px}
label{display:block;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:#b5bac1;margin-bottom:6px}
input[type=text],input[type=password]{width:100%;padding:10px 12px;background:#1e1f22;border:1px solid #3f4147;border-radius:6px;color:#dbdee1;font-size:14px;outline:none;transition:.2s}
input:focus{border-color:#5865f2}
.btn{width:100%;padding:11px;background:#5865f2;color:#fff;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;margin-top:18px;transition:.2s}
.btn:hover{background:#4752c4}
.error{color:#ed4245;font-size:13px;margin-top:10px;display:none}
.footer{text-align:center;margin-top:20px;font-size:11px;color:#6d6f78}
.footer a{color:#5865f2;text-decoration:none}
</style></head><body>
<div class="card">
  <h1><img src="CONFIG_LOGO" alt=""> ZenVPS</h1>
  <p class="sub">Admin Dashboard Login</p>
  <form method="POST" action="/login">
    <label>Username</label>
    <input type="text" name="username" required autofocus>
    <label style="margin-top:14px">Password</label>
    <input type="password" name="password" required>
    <button class="btn" type="submit">Log In</button>
    <div class="error" id="err">Invalid credentials</div>
  </form>
  <div class="footer">Built by <a href="https://www.zendevelopment.in" target="_blank">ZenDevelopment</a></div>
</div>
<script>if(new URLSearchParams(location.search).has('err'))document.getElementById('err').style.display='block';</script>
</body></html>""".replace("CONFIG_LOGO", config.BOT_LOGO)

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZenVPS — Dashboard</title>
<style>
:root{--bg:#1e1f22;--card:#2b2d31;--border:#3f4147;--text:#dbdee1;--dim:#949ba4;--accent:#5865f2;--green:#57f287;--red:#ed4245;--yellow:#fee75c;--radius:8px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.topbar{background:var(--card);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.topbar .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px}
.topbar .brand img{width:26px;height:26px;border-radius:50%}
.topbar .right{display:flex;align-items:center;gap:16px;font-size:13px;color:var(--dim)}
.topbar .right a{color:var(--red);text-decoration:none;font-weight:600}
.main{padding:28px;max-width:1400px;margin:0 auto}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:28px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.stat-card .label{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);margin-bottom:8px}
.stat-card .value{font-size:28px;font-weight:700}
.stat-card .value.green{color:var(--green)}.stat-card .value.blue{color:var(--accent)}.stat-card .value.yellow{color:var(--yellow)}.stat-card .value.red{color:var(--red)}
.section{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:20px}
.section h2{font-size:15px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between}
.section h2 .btns{display:flex;gap:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
td{padding:8px 10px;border-bottom:1px solid var(--border)}
tr:hover td{background:rgba(88,101,242,.06)}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge.running{background:rgba(87,242,135,.15);color:var(--green)}
.badge.stopped{background:rgba(237,66,69,.15);color:var(--red)}
.badge.creating{background:rgba(254,231,92,.15);color:var(--yellow)}
.badge.failed{background:rgba(237,66,69,.15);color:var(--red)}
.badge.deleted{background:rgba(148,155,164,.15);color:var(--dim)}
.btn-sm{padding:4px 10px;border:1px solid var(--border);background:transparent;color:var(--text);border-radius:4px;font-size:11px;cursor:pointer;transition:.15s}
.btn-sm:hover{background:var(--accent);border-color:var(--accent);color:#fff}
.btn-sm.danger:hover{background:var(--red);border-color:var(--red)}
.btn-accent{padding:7px 16px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;transition:.15s}
.btn-accent:hover{background:#4752c4}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;align-items:center;justify-content:center}
.modal-bg.show{display:flex}
.modal{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:28px;width:100%;max-width:440px}
.modal h3{margin-bottom:18px;font-size:17px}
.modal label{display:block;font-size:12px;font-weight:600;text-transform:uppercase;color:var(--dim);margin-bottom:5px;margin-top:12px}
.modal input,.modal select{width:100%;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;outline:none}
.modal input:focus,.modal select:focus{border-color:var(--accent)}
.modal .btns{display:flex;gap:10px;margin-top:20px;justify-content:flex-end}
.modal .btns button{padding:8px 20px;border-radius:6px;border:none;font-size:13px;font-weight:600;cursor:pointer}
.modal .btn-cancel{background:transparent;border:1px solid var(--border);color:var(--text)}
.modal .btn-submit{background:var(--accent);color:#fff}
.toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:600;z-index:999;transform:translateY(100px);opacity:0;transition:.3s}
.toast.show{transform:translateY(0);opacity:1}
.toast.success{background:var(--green);color:#000}
.toast.error{background:var(--red);color:#fff}
.logs{max-height:260px;overflow-y:auto}
.logs p{font-size:12px;padding:5px 0;border-bottom:1px solid var(--border);color:var(--dim)}
.logs p span.time{color:var(--dim);margin-right:10px;font-family:monospace}
.logs p span.action{color:var(--accent)}
.footer{text-align:center;padding:20px;font-size:11px;color:#4e5058}
.footer a{color:var(--accent);text-decoration:none}
@media(max-width:768px){.main{padding:16px}.stats{grid-template-columns:1fr 1fr}table{font-size:11px}td,th{padding:5px 6px}}
</style></head><body>
<div class="topbar">
  <div class="brand"><img src="CONFIG_LOGO" alt=""> ZenVPS Dashboard</div>
  <div class="right"><span id="clock"></span><a href="/logout">Logout</a></div>
</div>
<div class="main">
  <div class="stats" id="stats"></div>
  <div class="section">
    <h2>VPS Servers <div class="btns"><button class="btn-accent" onclick="openModal()">+ New VPS</button><button class="btn-sm" onclick="loadData()">↻ Refresh</button></div></h2>
    <div style="overflow-x:auto"><table><thead><tr>
      <th>ID</th><th>Name</th><th>Owner</th><th>OS</th><th>CPU</th><th>RAM</th><th>Disk</th><th>IP</th><th>Port</th><th>Status</th><th>Expires</th><th>Actions</th>
    </tr></thead><tbody id="vps-table"></tbody></table></div>
  </div>
  <div class="section">
    <h2>Activity Logs</h2>
    <div class="logs" id="logs"></div>
  </div>
</div>
<div class="footer">Built by <a href="https://www.zendevelopment.in" target="_blank">ZenDevelopment</a> — www.zendevelopment.in</div>

<div class="modal-bg" id="modal">
  <div class="modal">
    <h3>Deploy New VPS</h3>
    <label>Owner Discord ID</label>
    <input type="text" id="m-owner" placeholder="123456789012345678">
    <label>OS Template</label>
    <select id="m-os">OS_OPTIONS</select>
    <label>CPU Cores</label>
    <input type="number" id="m-cpu" value="1" min="1" max="4">
    <label>RAM (MB)</label>
    <input type="number" id="m-ram" value="512" min="128" max="4096" step="128">
    <label>Disk (GB)</label>
    <input type="number" id="m-disk" value="5" min="1" max="50">
    <label>Expiry (hours)</label>
    <input type="number" id="m-hours" value="72" min="1" max="720">
    <div class="btns"><button class="btn-cancel" onclick="closeModal()">Cancel</button><button class="btn-submit" onclick="createVPS()">Deploy</button></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const API='';
function toast(msg,ok){const t=document.getElementById('toast');t.textContent=msg;t.className='toast '+(ok?'success':'error')+' show';setTimeout(()=>t.classList.remove('show'),3000)}
function fmtTime(s){if(!s)return'-';const d=new Date(s+'Z');return d.toLocaleString()}
async function loadData(){
  const [stats,vps,logs]=await Promise.all([fetch(API+'/api/stats').then(r=>r.json()),fetch(API+'/api/vps').then(r=>r.json()),fetch(API+'/api/logs').then(r=>r.json())]);
  document.getElementById('stats').innerHTML=`
    <div class="stat-card"><div class="label">Total VPS</div><div class="value blue">${stats.total_vps}</div></div>
    <div class="stat-card"><div class="label">Active</div><div class="value green">${stats.active_vps}</div></div>
    <div class="stat-card"><div class="label">Users</div><div class="value yellow">${stats.total_users}</div></div>
    <div class="stat-card"><div class="label">CPU Usage</div><div class="value blue">${stats.cpu_pct.toFixed(1)}%</div></div>
    <div class="stat-card"><div class="label">RAM Usage</div><div class="value yellow">${stats.ram_pct.toFixed(1)}%</div></div>
    <div class="stat-card"><div class="label">Disk Usage</div><div class="value red">${stats.disk_pct.toFixed(1)}%</div></div>`;
  const tb=document.getElementById('vps-table');
  if(!vps.length){tb.innerHTML='<tr><td colspan="12" style="text-align:center;color:var(--dim);padding:30px">No VPS deployed yet</td></tr>';return}
  tb.innerHTML=vps.map(v=>`<tr>
    <td>${v.id}</td><td><code>${v.name}</code></td><td>${v.owner_id}</td><td>${v.os_template}</td>
    <td>${v.cpu}</td><td>${v.ram}MB</td><td>${v.disk}GB</td><td>${v.ip||'-'}</td><td>${v.ssh_port||'-'}</td>
    <td><span class="badge ${v.status}">${v.status}</span></td><td>${fmtTime(v.expires_at)}</td>
    <td>${v.status==='running'?`<button class="btn-sm" onclick="act('${v.name}','stop')">Stop</button> `:''}
    ${v.status==='stopped'?`<button class="btn-sm" onclick="act('${v.name}','start')">Start</button> `:''}
    <button class="btn-sm" onclick="act('${v.name}','restart')">Restart</button>
    <button class="btn-sm danger" onclick="act('${v.name}','delete')">Delete</button></td>
  </tr>`).join('');
  document.getElementById('logs').innerHTML=logs.map(l=>`<p><span class="time">${l.timestamp||''}</span><span class="action">[${l.action}]</span> ${l.target} ${l.details?'— '+l.details:''}</p>`).join('');
}
async function act(name,action){
  if(action==='delete'&&!confirm('Permanently delete '+name+'?'))return;
  const r=await fetch(API+'/api/vps/act',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,action})});
  const d=await r.json();toast(d.message||d.error,!!d.ok);loadData();
}
function openModal(){document.getElementById('modal').classList.add('show')}
function closeModal(){document.getElementById('modal').classList.remove('show')}
async function createVPS(){
  const body={owner_id:document.getElementById('m-owner').value,os:document.getElementById('m-os').value,
    cpu:+document.getElementById('m-cpu').value,ram:+document.getElementById('m-ram').value,
    disk:+document.getElementById('m-disk').value,hours:+document.getElementById('m-hours').value};
  const r=await fetch(API+'/api/vps/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();toast(d.message||d.error,!!d.ok);if(d.ok)closeModal();loadData();
}
function clock(){document.getElementById('clock').textContent=new Date().toLocaleTimeString()}
setInterval(clock,1000);clock();loadData();setInterval(loadData,15000);
</script>
</body></html>""".replace("CONFIG_LOGO", config.BOT_LOGO).replace(
    "OS_OPTIONS",
    "\n".join(f'<option value="{k}">{v["display"]}</option>' for k, v in config.OS_TEMPLATES.items())
)


# ══════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == config.DASHBOARD_USERNAME and p == config.DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        return redirect("/login?err=1")
    return send_string(LOGIN_HTML)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
@_login_required
def index():
    return send_string(DASHBOARD_HTML)


# ── API ───────────────────────────────────────────────────────────
@app.route("/api/stats")
@_login_required
async def api_stats():
    import asyncio
    s = await _db.stats()
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    s["cpu_pct"] = cpu
    s["ram_pct"] = mem.percent
    s["disk_pct"] = disk.percent
    return jsonify(s)


@app.route("/api/vps")
@_login_required
async def api_vps_list():
    vps_list = await _db.get_all_vps()
    return jsonify(vps_list)


@app.route("/api/vps/create", methods=["POST"])
@_login_required
async def api_vps_create():
    j = request.json
    r = await _deployer.deploy(
        owner_id=j.get("owner_id", ""),
        os_key=j.get("os", "ubuntu-22.04"),
        cpu=j.get("cpu", 1),
        ram=j.get("ram", 512),
        disk=j.get("disk", 5),
        hours=j.get("hours", 72),
    )
    if r["ok"]:
        return jsonify({"ok": True, "message": f"VPS {r['vps']['name']} deployed"})
    return jsonify({"ok": False, "error": r.get("error", "unknown")}), 400


@app.route("/api/vps/act", methods=["POST"])
@_login_required
async def api_vps_act():
    j = request.json
    name, action = j.get("name", ""), j.get("action", "")
    actions = {"start": _deployer.start, "stop": _deployer.stop,
               "restart": _deployer.restart, "delete": _deployer.destroy}
    fn = actions.get(action)
    if not fn:
        return jsonify({"ok": False, "error": "Invalid action"}), 400
    r = await fn(name)
    if r["ok"]:
        return jsonify({"ok": True, "message": f"{action} on {name} done"})
    return jsonify({"ok": False, "error": r.get("error", "unknown")}), 400


@app.route("/api/logs")
@_login_required
async def api_logs():
    logs_list = await _db.get_logs(100)
    return jsonify(logs_list)


# ── run in thread ─────────────────────────────────────────────────
def run_dashboard_thread(db_ref, deployer_ref):
    init_dashboard(db_ref, deployer_ref)
    log.info("Dashboard starting on %s:%d", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )

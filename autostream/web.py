"""Phone/browser control dashboard.

Serves a small page on the local network so you can see status and stop the
stream from your phone — which works regardless of the game's display mode
(nothing can float above exclusive fullscreen).

Stdlib only. Runs on a daemon thread. Like the desktop panel it never touches
YouTube or OBS directly: it posts to engine.submit() and reads engine.state.

SECURITY: plain HTTP on your LAN, guarded by a token in the URL. That is
appropriate for a home network and nothing more. Do not port-forward it.
"""
from __future__ import annotations

import hmac
import json
import logging
import socket
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("autostream.web")

PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<title>AutoStream</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0d1117;color:#e6edf3;
 font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 padding:max(20px,env(safe-area-inset-top)) 20px 40px;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:440px;margin:0 auto}
.card{background:#161b22;border:1px solid #2a3441;border-radius:16px;padding:22px;margin-bottom:14px}
.row{display:flex;align-items:center;gap:11px}
.dot{width:14px;height:14px;border-radius:50%;flex:0 0 auto;background:#6e7d8f;
 transition:background .3s}
.dot.pulse{animation:p 1.6s ease-in-out infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.35}}
h1{font-size:24px;margin:0;letter-spacing:-.02em;font-weight:700}
.game{color:#9aa8b8;margin:10px 0 0;font-size:17px;min-height:25px}
.time{font:600 40px/1 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
 margin:16px 0 6px;letter-spacing:-.02em}
.meta{color:#6e7d8f;font-size:13px}
button{width:100%;padding:19px;border:0;border-radius:14px;font-size:17px;
 font-weight:650;color:#fff;background:#232c38;margin-bottom:11px;cursor:pointer;
 font-family:inherit;transition:transform .08s,opacity .2s}
button:active{transform:scale(.985)}
button:disabled{opacity:.32;cursor:default}
.stop{background:#c2352f}
.pause{background:#8a6410}
a.open{display:block;text-align:center;padding:19px;border-radius:14px;
 background:#232c38;color:#e6edf3;text-decoration:none;font-weight:650;font-size:17px}
.err{background:#3d1418;border-color:#5c1d23;color:#ffb3b3}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}
.stat{background:#0d1117;border:1px solid #222b36;border-radius:11px;padding:11px 8px;text-align:center}
.stat b{display:block;font:700 20px/1 ui-monospace,Menlo,monospace;margin-bottom:5px}
.stat span{font-size:10.5px;color:#6e7d8f;text-transform:uppercase;letter-spacing:.07em}
.hd{font-size:11px;color:#6e7d8f;text-transform:uppercase;letter-spacing:.09em;
 margin:0 0 12px;font-weight:700}
#chat{max-height:44vh;overflow-y:auto;-webkit-overflow-scrolling:touch}
.msg{padding:7px 0;border-bottom:1px solid #1c232d;font-size:14.5px;line-height:1.45}
.msg:last-child{border-bottom:0}
.msg .a{color:#4d9fff;font-weight:650}
.msg.own .a{color:#ff4d4d}
.msg.mod .a{color:#3fb950}
.empty{color:#5c6875;font-size:14px;padding:10px 0}
.send{display:flex;gap:9px;margin-top:12px}
.send input{flex:1;min-width:0;background:#0d1117;border:1px solid #2a3441;border-radius:11px;
 padding:14px;color:#e6edf3;font-size:16px;font-family:inherit}
.send input:focus{outline:0;border-color:#4d9fff}
.send button{width:auto;padding:14px 20px;margin:0;background:#1f6feb;font-size:15px}
.health{font-size:12px;color:#6e7d8f;margin-top:12px}
.health.bad{color:#d29922}
</style></head><body><div class="wrap">

<div class="card">
  <div class="row"><span class="dot" id="dot"></span><h1 id="phase">…</h1></div>
  <p class="game" id="game"></p>
  <div class="time" id="time">--:--:--</div>
  <div class="meta" id="meta"></div>
  <div class="stats">
    <div class="stat"><b id="s_view">–</b><span>watching</span></div>
    <div class="stat"><b id="s_like">–</b><span>likes</span></div>
    <div class="stat"><b id="s_tot">–</b><span>views</span></div>
  </div>
  <div class="health" id="health"></div>
</div>

<div class="card">
  <div class="hd">Live chat</div>
  <div id="chat"><div class="empty">No messages yet.</div></div>
  <div class="send">
    <input id="msg" placeholder="Say something…" maxlength="200"
           autocomplete="off" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">Send</button>
  </div>
</div>

<div class="card" id="controls">
  <button class="stop" id="bstop" onclick="cmd('stop')">End stream</button>
  <button class="pause" id="bpause" onclick="cmd('toggle_pause')">Pause</button>
  <a class="open" id="bopen" href="#" target="_blank" rel="noopener">Open on YouTube</a>
</div>

</div><script>
const K = new URLSearchParams(location.search).get('k') || '';
const C = {IDLE:'#6e7d8f',ARMING:'#d29922',STARTING:'#d29922',TESTING:'#a371f7',
           LIVE:'#ff4d4d',COOLDOWN:'#4d9fff',STOPPING:'#8b98a8'};
const L = {IDLE:'Idle',ARMING:'Arming',STARTING:'Starting',TESTING:'Going live',
           LIVE:'LIVE',COOLDOWN:'Cooldown',STOPPING:'Stopping'};
let busy = false;

function hms(s){if(s==null)return '--:--:--';s=Math.max(0,s|0);
  const p=n=>String(n).padStart(2,'0');
  return p(s/3600|0)+':'+p((s%3600)/60|0)+':'+p(s%60);}

async function tick(){
  try{
    const r = await fetch('/api/status?k='+encodeURIComponent(K),{cache:'no-store'});
    if(r.status===403){document.body.innerHTML=
      '<div class="wrap"><div class="card err"><b>Wrong or missing key</b><br>'+
      'Open the exact URL from the AutoStream log.</div></div>';return;}
    const d = await r.json();
    const paused = d.paused;
    const col = paused ? '#d29922' : (C[d.phase]||'#6e7d8f');
    const dot = document.getElementById('dot');
    dot.style.background = col;
    dot.className = 'dot' + (d.phase==='LIVE' && !paused ? ' pulse':'');
    document.getElementById('phase').textContent = paused ? 'Paused' : (L[d.phase]||d.phase);
    document.getElementById('phase').style.color = (d.phase==='LIVE'&&!paused)?col:'#e6edf3';
    const g = document.getElementById('game');
    if(d.phase==='IDLE' && d.blocked){g.textContent='blocked: '+d.blocked;g.style.color='#d29922';}
    else {g.textContent = d.game || 'no game'; g.style.color='#9aa8b8';}
    document.getElementById('time').textContent = hms(d.elapsed);
    document.getElementById('meta').textContent =
      'session #'+d.session+'  ·  quota '+d.quota_spent+'/10000';
    const n = v => v==null ? '–' : (v>=1000 ? (v/1000).toFixed(1)+'k' : v);
    document.getElementById('s_view').textContent = n(d.viewers);
    document.getElementById('s_like').textContent = n(d.likes);
    document.getElementById('s_tot').textContent  = n(d.views);

    const h = document.getElementById('health'), oh = d.obs || {};
    if(oh.active){
      const drop = oh.total ? (oh.skipped/oh.total*100) : 0;
      h.textContent = 'OBS  ·  '+(oh.congestion>0.3?'congested':'healthy')
        +'  ·  '+drop.toFixed(1)+'% frames dropped';
      h.className = 'health' + ((oh.congestion>0.3||drop>2) ? ' bad' : '');
    } else { h.textContent=''; h.className='health'; }

    renderChat(d.chat||[]);
    const liveish = ['STARTING','TESTING','LIVE','COOLDOWN'].includes(d.phase);
    document.getElementById('bstop').disabled = !liveish || busy;
    document.getElementById('bpause').textContent = paused ? 'Resume' : 'Pause';
    const o = document.getElementById('bopen');
    if(d.url){o.href=d.url;o.style.display='block';}else{o.style.display='none';}
  }catch(e){
    document.getElementById('phase').textContent = 'Disconnected';
    document.getElementById('dot').style.background = '#6e7d8f';
  }
}
let lastChatKey = '';
function renderChat(msgs){
  const box = document.getElementById('chat');
  const key = msgs.length ? msgs[msgs.length-1].id + ':' + msgs.length : 'e';
  if(key === lastChatKey) return;
  lastChatKey = key;
  if(!msgs.length){box.innerHTML='<div class="empty">No messages yet.</div>';return;}
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  box.innerHTML = msgs.map(m =>
    '<div class="msg'+(m.owner?' own':(m.mod?' mod':''))+'">'+
    '<span class="a">'+esc(m.author)+'</span> '+esc(m.text)+'</div>').join('');
  if(atBottom) box.scrollTop = box.scrollHeight;
}
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML;}

async function send(){
  const i = document.getElementById('msg');
  const t = i.value.trim();
  if(!t) return;
  i.value = '';
  try{
    await fetch('/api/chat?k='+encodeURIComponent(K),{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})});
  }catch(e){ i.value = t; }
  setTimeout(tick, 900);
}

async function cmd(c){
  if(busy) return; busy = true;
  try{
    await fetch('/api/cmd?k='+encodeURIComponent(K),{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})});
  }catch(e){}
  setTimeout(()=>{busy=false;tick();},600);
  tick();
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


def lan_ip() -> str:
    """Best-effort LAN address. Opens a UDP socket but sends nothing."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "AutoStream"
    protocol_version = "HTTP/1.1"

    def __init__(self, engine, token, *args, **kwargs):
        self.engine = engine
        self.token = token
        super().__init__(*args, **kwargs)

    # silence per-request stderr spam
    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ---------------- helpers ----------------

    def _authed(self, query) -> bool:
        given = (parse_qs(query).get("k") or [""])[0]
        return hmac.compare_digest(given, self.token)

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _snapshot(self) -> dict:
        s = self.engine.state
        return {
            "phase": s.phase,
            "game": s.current_game,
            "paused": s.paused,
            "session": s.session_number,
            "quota_spent": s.quota_spent,
            "viewers": getattr(self.engine, "viewers", None),
            "blocked": getattr(self.engine, "blocked_reason", None),
            "likes": getattr(self.engine, "likes", None),
            "views": getattr(self.engine, "views", None),
            "obs": getattr(self.engine, "obs_health", {}) or {},
            "chat": list(getattr(self.engine, "chat", []))[-60:],
            "elapsed": (int(time.time() - s.session_start) if s.session_start else None),
            "url": (f"https://www.youtube.com/watch?v={s.broadcast_id}"
                    if s.broadcast_id else None),
        }

    # ---------------- routes ----------------

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            if not self._authed(u.query):
                self._send(403, b"Add ?k=<token> to the URL. See the AutoStream log.",
                           "text/plain; charset=utf-8")
                return
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif u.path == "/api/status":
            if not self._authed(u.query):
                self._send(403, b'{"error":"forbidden"}')
                return
            # tells the engine a dashboard is open, so it starts polling chat
            self.engine.client_seen = time.monotonic()
            self._send(200, json.dumps(self._snapshot()).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/chat":
            if not self._authed(u.query):
                self._send(403, b'{"error":"forbidden"}')
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                text = str(json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                           .get("text", "")).strip()
            except (ValueError, TypeError):
                self._send(400, b'{"error":"bad request"}')
                return
            if not text:
                self._send(400, b'{"error":"empty"}')
                return
            self.engine.submit(("chat", text[:200]))
            self._send(200, b'{"ok":true}')
            return
        if u.path != "/api/cmd":
            self._send(404, b'{"error":"not found"}')
            return
        if not self._authed(u.query):
            self._send(403, b'{"error":"forbidden"}')
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
            command = str(payload.get("command", ""))
        except (ValueError, TypeError):
            self._send(400, b'{"error":"bad request"}')
            return

        if command not in ("stop", "pause", "resume", "toggle_pause"):
            self._send(400, b'{"error":"unknown command"}')
            return
        log.info("web command: %s from %s", command, self.address_string())
        self.engine.submit(command)
        self._send(200, b'{"ok":true}')


class Dashboard:
    def __init__(self, engine, token: str, port: int = 8787):
        self.engine = engine
        self.token = token
        self.port = port
        self.httpd = None
        self._thread = None

    def start(self) -> str | None:
        try:
            handler = partial(_Handler, self.engine, self.token)
            self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        except OSError as e:
            log.error("dashboard could not bind port %d: %s", self.port, e)
            return None
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        name="autostream-web", daemon=True)
        self._thread.start()
        url = f"http://{lan_ip()}:{self.port}/?k={self.token}"
        log.info("=" * 60)
        log.info("phone dashboard: %s", url)
        log.info("=" * 60)
        return url

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
            self.httpd = None

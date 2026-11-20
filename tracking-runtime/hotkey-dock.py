"""Serve the OBS controls dock on loopback while its Lua script is loaded."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import sys
import platform
import threading

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1:46642"
TOKEN = secrets.token_hex(24)

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OBS Controls</title>
<style>
:root { color-scheme: dark; font: 13px system-ui; background: #191c22; color: #eef2f8 }
body { margin: 0; padding: 12px }
main { max-width: 320px; margin: auto }
header { display: flex; align-items: center; justify-content: space-between; gap: 8px }
h1 { font-size: 15px; margin: 0 }
output { color: #b7c5d6 }
output.on { color: #8be3aa } output.off { color: #ffcb86 }
button { width: 100%; margin: 10px 0 7px; padding: 8px; border: 1px solid #536888;
border-radius: 7px; color: #fff; background: #30476a; font: inherit; cursor: pointer }
button:disabled { opacity: .55; cursor: default }
small { color: #b7c5d6 } kbd { color: #fff }
</style>
<main><header><h1>OBS Controls</h1><output aria-live="polite">Connecting</output></header>
<button disabled>Pause shortcuts</button><small><kbd>__SHORTCUT__</kbd> toggles shortcuts in OBS</small></main>
<script>
const button = document.querySelector("button");
const status = document.querySelector("output");
let busy = false;
function display(state) {
    status.className = state;
    status.textContent = { on: "On", off: "Paused" }[state] || "Unavailable";
    button.textContent = state === "off" ? "Resume shortcuts" : "Pause shortcuts";
    button.disabled = busy || !["on", "off"].includes(state);
}
async function refresh() {
    try {
        const response = await fetch("/state", {cache: "no-store"});
        display(await response.text());
    } catch { display("unavailable"); }
}
button.onclick = async () => {
    busy = true;
    button.disabled = true;
    try {
        await fetch("/toggle", {method: "POST", headers: {"X-OBS-Dock": "__TOKEN__"}});
    } finally {
        busy = false;
        await refresh();
    }
};
refresh();
setInterval(refresh, 500);
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data="", mime="text/plain"):
        payload = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def valid_host(self):
        return self.headers.get("Host") == HOST

    def do_GET(self):
        if not self.valid_host():
            self.reply(403)
        elif self.path == "/":
            self.reply(200, PAGE.replace("__TOKEN__", TOKEN).replace("__SHORTCUT__", "⌘ `" if platform.system() == "Darwin" else "Ctrl + `"), "text/html")
        elif self.path == "/state":
            try:
                state = (ROOT / "hotkey-dock.state").read_text()
            except OSError:
                state = "unavailable"
            self.reply(200, state)
        else:
            self.reply(404)

    def do_POST(self):
        valid = (self.valid_host() and self.headers.get("Origin") == "http://" + HOST
                 and hmac.compare_digest(self.headers.get("X-OBS-Dock", ""), TOKEN))
        if self.path != "/toggle" or not valid:
            self.reply(403)
            return
        pending = ROOT / "hotkey-dock.toggle"
        try:
            pending.touch(exist_ok=False)
        except FileExistsError:
            pass
        self.reply(202)

    def log_message(self, *_args):
        pass


with ThreadingHTTPServer(("127.0.0.1", 46642), Handler) as server:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sys.stdin.read()
    server.shutdown()

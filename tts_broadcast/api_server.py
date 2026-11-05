"""내부망 HTTP API + 웹 조작 페이지 (외부 CDN/인터넷 리소스 사용 안 함).

  POST /api/announce   {"text": "...", "priority": "긴급|높음|보통|0~9", "repeat": 1, "chime": true}
  GET  /api/announce?text=...&priority=...     (간단한 장비 연동용)
  GET  /api/status
  POST /api/stop       현재 방송 중지
  POST /api/clear      대기열 비우기
  GET  /               브라우저 조작 페이지
token 설정 시 헤더 X-Token 또는 ?token= 필요.
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .broadcaster import Announcement, Broadcaster, parse_bool, parse_priority

log = logging.getLogger(__name__)

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TTS 방송</title><style>
body{font-family:'Malgun Gothic',sans-serif;max-width:720px;margin:20px auto;padding:0 16px;background:#f4f5f7;color:#222}
textarea{width:100%;height:120px;font-size:16px;box-sizing:border-box}
button{font-size:16px;padding:8px 16px;margin:4px 4px 4px 0;cursor:pointer}
.emg{background:#c62828;color:#fff;border:0}.box{background:#fff;padding:12px;border-radius:8px;margin:10px 0}
pre{white-space:pre-wrap;font-size:13px}</style></head><body>
<h2>TTS 방송 송출</h2>
<div class="box"><textarea id="t" placeholder="방송할 문구를 입력하세요"></textarea><br>
우선순위 <select id="p"><option>보통</option><option>높음</option><option>긴급</option></select>
반복 <input id="r" type="number" min="1" max="10" value="1" style="width:50px">
<label><input id="c" type="checkbox" checked> 차임</label>
토큰 <input id="k" type="password" style="width:100px"><br>
<button onclick="send()">방송 송출</button><button class="emg" onclick="send('긴급')">긴급 방송</button>
<button onclick="post('/api/stop')">현재 방송 중지</button><button onclick="post('/api/clear')">대기열 비우기</button>
<div id="m"></div></div>
<div class="box"><b>상태</b><pre id="s"></pre></div>
<script>
const k=document.getElementById('k');try{k.value=localStorage.getItem('tok')||''}catch(e){}
function hdr(){try{localStorage.setItem('tok',k.value)}catch(e){}return{'Content-Type':'application/json','X-Token':k.value}}
async function post(u,b){const r=await fetch(u,{method:'POST',headers:hdr(),body:JSON.stringify(b||{})});
const j=await r.json();document.getElementById('m').textContent=j.ok?'완료':('오류: '+j.error);refresh();return j}
async function send(p){const j=await post('/api/announce',{text:document.getElementById('t').value,
priority:p||document.getElementById('p').value,repeat:+document.getElementById('r').value,chime:document.getElementById('c').checked});
if(j.ok)document.getElementById('t').value=''}
async function refresh(){try{const r=await fetch('/api/status',{headers:hdr()});const j=await r.json();
if(!j.ok){document.getElementById('s').textContent=j.error;return}
let s='엔진: '+j.engine+'\\n현재 송출: '+(j.current?j.current.text:'(없음)')+'\\n대기: '+j.pending.length+'건\\n';
j.pending.forEach(a=>s+='  ['+a.priority_name+'] '+a.text+'\\n');document.getElementById('s').textContent=s}catch(e){}}
setInterval(refresh,2000);refresh();
</script></body></html>"""


class ApiServer:
    def __init__(self, broadcaster: Broadcaster, host: str, port: int, token: str = ""):
        self.broadcaster = broadcaster
        self.token = token
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                log.debug("%s - %s", self.address_string(), fmt % args)

            def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
                data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self, query: dict) -> bool:
                if not server.token:
                    return True
                given = self.headers.get("X-Token") or (query.get("token") or [""])[0]
                return hmac.compare_digest(given.encode(), server.token.encode())

            def _handle(self, method: str):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path == "/" and method == "GET":
                    return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                if not self._authorized(query):
                    return self._send(401, {"ok": False, "error": "토큰이 올바르지 않습니다"})
                body = {}
                if method == "POST":
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length else b""
                    if raw:
                        ctype = self.headers.get("Content-Type", "")
                        if "json" in ctype:
                            body = json.loads(raw.decode("utf-8"))
                        else:
                            body = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
                params = {k: v[0] for k, v in query.items()}
                params.update(body)
                b = server.broadcaster
                if url.path == "/api/announce":
                    ann = b.submit(Announcement(
                        text=str(params.get("text", "")),
                        priority=parse_priority(params.get("priority")),
                        repeat=int(params.get("repeat") or 1),
                        chime=parse_bool(params.get("chime")),
                        source=f"API:{self.client_address[0]}"))
                    return self._send(200, {"ok": True, "id": ann.id})
                if url.path == "/api/status":
                    cur = b.current
                    return self._send(200, {"ok": True, "engine": b.engine_key,
                                            "current": cur.to_dict() if cur else None,
                                            "pending": [a.to_dict() for a in b.pending()]})
                if url.path == "/api/stop" and method == "POST":
                    b.stop_current()
                    return self._send(200, {"ok": True})
                if url.path == "/api/clear" and method == "POST":
                    return self._send(200, {"ok": True, "cleared": b.clear_queue()})
                return self._send(404, {"ok": False, "error": "not found"})

            def _safe(self, method: str):
                try:
                    self._handle(method)
                except (ValueError, TypeError) as e:
                    self._send(400, {"ok": False, "error": str(e)})
                except Exception as e:
                    log.exception("API 오류")
                    self._send(500, {"ok": False, "error": str(e)})

            def do_GET(self):
                self._safe("GET")

            def do_POST(self):
                self._safe("POST")

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self._started = False

    def start(self) -> None:
        self._started = True
        threading.Thread(target=self.httpd.serve_forever, name="api", daemon=True).start()
        host, port = self.httpd.server_address[:2]
        log.info("HTTP API: http://%s:%s/", host, port)

    def stop(self) -> None:
        if self._started:
            self.httpd.shutdown()
        self.httpd.server_close()

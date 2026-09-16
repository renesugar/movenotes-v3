"""Loopback-only 7b subpath mount; run the generated Bluge server on port 18773."""
import http.server, urllib.request, urllib.error, threading, sys
from pathlib import Path
ROOT=Path(sys.argv[1])
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,backend,**kwargs):
        self.backend=backend
        super().__init__(*args,directory=str(ROOT/backend/'public'),**kwargs)
    def do_GET(self):
        if not self.path.startswith('/archive/'):
            self.send_error(404); return
        self.path=self.path[len('/archive'):]
        if self.path.startswith('/api/') and self.backend=='bluge':
            try:
                with urllib.request.urlopen('http://127.0.0.1:18773'+self.path) as r:
                    self.send_response(r.status)
                    self.send_header('Content-Type',r.headers.get('Content-Type','application/json'))
                    self.end_headers(); self.wfile.write(r.read())
            except urllib.error.HTTPError as e: self.send_error(e.code)
        else: super().do_GET()
servers=[]
for backend,port in [('bluge',18771),('pagefind',18772)]:
    def factory(*a,backend=backend,**k): return Handler(*a,backend=backend,**k)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),factory)
    servers.append(server); threading.Thread(target=server.serve_forever,daemon=True).start()
threading.Event().wait()

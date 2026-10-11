"""Controlled egress endpoint inside the isolated test namespace."""

import json
from pathlib import Path
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.client_address[0].encode()
        if self.path == "/dynamic-ip":
            control = Path("work/native-rootfs/tmp/egress-mode.json")
            mode = json.loads(control.read_text()) if control.exists() else {}
            tail = int(self.client_address[0].split(".")[-1]) + mode.get("generation", 0) * 20
            if mode.get("mismatch") and self.headers.get("Host") == "beta.test":
                tail += 100
            value = f"93.184.216.{tail}"
            if mode.get("private"):
                value = "10.0.0.1"
            if mode.get("malformed"):
                value = "not-an-ip"
            body = value.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("203.0.113.10", 443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("work/native-tls/server.pem", "work/native-tls/server.key")
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()

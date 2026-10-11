"""Controlled egress endpoint inside the isolated test namespace."""

import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.client_address[0].encode()
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

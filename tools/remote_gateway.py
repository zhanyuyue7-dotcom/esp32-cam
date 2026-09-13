"""Private camera gateway. Bind only to loopback; publish with Tailscale Serve."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import io
import json
from pathlib import Path
import socket
import struct
import threading
import time
from urllib.parse import urlsplit, parse_qs
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class CameraConnection(http.client.HTTPConnection):
    def __init__(self, host, port, interface_index=0, timeout=6):
        super().__init__(host, port, timeout=timeout)
        self.interface_index = interface_index

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            if self.interface_index:
                # Windows IP_UNICAST_IF chooses WLAN without changing system routes.
                self.sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack('!I', self.interface_index))
            self.sock.connect((self.host, self.port))
        except Exception:
            self.sock.close()
            self.sock = None
            raise


def load_page():
    source = (ROOT / 'src/main.cpp').read_text(encoding='utf-8')
    page = source.split('R"HTML(', 1)[1].split(')HTML";', 1)[0]
    page = page.replace('连接与摄像头相同的 Wi-Fi，即可实时查看。画面由摄像头直接传到浏览器。',
                        '手机保持 Tailscale 已连接。低延迟模式按需读取最新画面，连接中断后自动重试。')
    viewer = (ROOT/'tools/remote_viewer.js').read_text(encoding='utf-8')
    return (page.split('<script>', 1)[0] + '<script>' + viewer + '</script></html>').encode('utf-8')


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, config, page=None):
        self.camera_config = config
        self.page = page if page is not None else load_page()
        self.stream_lock = threading.Lock()
        self.began = time.monotonic()
        super().__init__(address, Handler)

    def current_config(self):
        config = json.loads(self.camera_config.read_text(encoding='utf-8-sig'))
        ipaddress.IPv4Address(config['camera_ip'])
        return config


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/':
            return self.reply(200, self.server.page, 'text/html; charset=utf-8')
        if path == '/favicon.ico':
            return self.reply(204, b'')
        if path == '/health':
            return self.reply(200, json.dumps({'gateway_ok': True,
                'uptime_s': int(time.monotonic()-self.server.began)}).encode())
        if path not in ('/status', '/capture', '/stream'):
            return self.reply(404, b'{"error":"Not found"}')

        streaming = path == '/stream'
        locked = False
        connection = None
        headers_sent = False
        try:
            if streaming:
                locked = self.server.stream_lock.acquire(blocking=False)
                if not locked:
                    return self.reply(503, b'{"error":"A video viewer is already connected"}')
            config = self.server.current_config()
            port = config.get('stream_port', 81) if streaming else config.get('web_port', 80)
            connection = CameraConnection(config['camera_ip'], port, config.get('interface_index', 0))
            connection.request('GET', path, headers={'Connection': 'close'})
            response = connection.getresponse()
            if not streaming or response.status != 200:
                data = response.read(2 * 1024 * 1024)
                if path == '/capture' and response.status == 200 and parse_qs(urlsplit(self.path).query).get('profile') == ['mobile']:
                    # Reduce transmission cost only when the viewer detects a slow link.
                    with Image.open(io.BytesIO(data)) as frame:
                        frame.thumbnail((480, 360), Image.Resampling.LANCZOS)
                        output = io.BytesIO()
                        frame.convert('RGB').save(output, format='JPEG', quality=55, optimize=True)
                        data = output.getvalue()
                self.reply(response.status, data, response.getheader('Content-Type', 'application/octet-stream'))
                return
            self.connection.settimeout(10)
            self.send_response(200)
            self.send_header('Content-Type', response.getheader('Content-Type'))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            headers_sent = True
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
            self.log_error('Camera request failed: %s', type(exc).__name__)
            if not headers_sent:
                try:
                    self.reply(502, json.dumps({'camera_ok': False, 'gateway_ok': True,
                        'error': 'Camera unavailable', 'reason': type(exc).__name__}).encode())
                except OSError:
                    pass
        finally:
            if connection:
                connection.close()
            if locked:
                self.server.stream_lock.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18732)
    parser.add_argument('--config', type=Path, default=ROOT/'gateway.json')
    args = parser.parse_args()
    server = Gateway(('127.0.0.1', args.port), args.config)
    print(f'Camera gateway listening on http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
from PIL import Image
from pathlib import Path
import tempfile
import threading
import unittest
from remote_gateway import Gateway

PAYLOAD = b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 8\r\n\r\n\xff\xd8test\xff\xd9\r\n'

class Upstream(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace;boundary=frame')
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            for chunk in (PAYLOAD[:19], PAYLOAD[19:]):
                self.wfile.write(f'{len(chunk):x}\r\n'.encode()+chunk+b'\r\n')
            self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
        else:
            if self.path == '/capture':
                output = io.BytesIO()
                Image.new('RGB', (640,480), (120,80,40)).save(output, format='JPEG')
                body = output.getvalue(); content_type = 'image/jpeg'
            else:
                body = b'{"camera_ok":true}'; content_type = 'application/json'
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Type', content_type); self.end_headers(); self.wfile.write(body)

class GatewayTest(unittest.TestCase):
    def test_proxy_and_failure_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
            config = Path(tmp)/'gateway.json'
            config.write_text(json.dumps({'camera_ip':'127.0.0.1','web_port':upstream.server_port,
                'stream_port':upstream.server_port}), encoding='utf-8')
            gateway = Gateway(('127.0.0.1', 0), config)
            for server in (upstream, gateway):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            def get(path):
                c = http.client.HTTPConnection('127.0.0.1', gateway.server_port, timeout=3)
                c.request('GET', path); r = c.getresponse(); result = r.status, r.read(); c.close(); return result
            try:
                code, page = get('/')
                self.assertEqual(code, 200)
                self.assertIn(b"fetch('/capture?t='", page)
                self.assertNotIn(b"location.hostname+':81", page)
                self.assertEqual(get('/status'), (200,b'{"camera_ok":true}'))
                code, original = get('/capture')
                code, mobile = get('/capture?profile=mobile')
                self.assertEqual(code,200)
                with Image.open(io.BytesIO(original)) as im: self.assertEqual(im.size,(640,480))
                with Image.open(io.BytesIO(mobile)) as im: self.assertEqual(im.size,(480,360))
                self.assertLess(len(mobile),len(original))
                self.assertEqual(get('/stream'), (200,PAYLOAD))
                self.assertTrue(gateway.stream_lock.acquire(timeout=1)); gateway.stream_lock.release()
                self.assertEqual(get('/not-a-proxy')[0],404)
                upstream.shutdown(); upstream.server_close()
                code, error = get('/status')
                self.assertEqual(code,502)
                self.assertFalse(json.loads(error)['camera_ok'])
                self.assertTrue(json.loads(get('/health')[1])['gateway_ok'])
                print('PASS: page stream URL, status proxy, chunked MJPEG passthrough, stream cleanup, route whitelist, camera offline response, gateway health')
            finally:
                gateway.shutdown(); gateway.server_close()
                upstream.shutdown(); upstream.server_close()

if __name__ == '__main__': unittest.main()

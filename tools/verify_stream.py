"""Exercise the board's live HTTP endpoints and decode every sampled MJPEG frame."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument('host')
p.add_argument('--seconds', type=int, default=20)
p.add_argument('--out', default='artifacts')
a = p.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
base = 'http://' + a.host
def get(path):
    with http.open(base+path, timeout=10) as r: return r.read()
html = get('/').decode()
assert '/stream' in html and '实时' in html
before = json.loads(get('/status'))
assert before['camera_ok'], before
photo = get('/capture')
with Image.open(io.BytesIO(photo)) as im:
    im.load(); assert im.size == (640,480), im.size
(out/'camera-capture.jpg').write_bytes(photo)
count = 0; hashes = set(); sizes = []; started = time.monotonic()
with http.open(base+':81/stream', timeout=10) as response:
    assert response.headers.get_content_type() == 'multipart/x-mixed-replace'
    while time.monotonic()-started < a.seconds:
        line = response.readline()
        if not line: raise RuntimeError('Stream ended unexpectedly')
        if not line.startswith(b'--frame'): continue
        headers = {}
        while True:
            line = response.readline()
            if line in (b'\r\n', b'\n'): break
            if not line: raise RuntimeError('Truncated frame headers')
            key,value = line.decode().split(':',1); headers[key.lower()] = value.strip()
        n = int(headers['content-length'])
        frame = response.read(n)
        assert len(frame) == n and frame.startswith(b'\xff\xd8') and frame.endswith(b'\xff\xd9')
        with Image.open(io.BytesIO(frame)) as im:
            im.load(); assert im.size == (640,480), im.size
        hashes.add(hashlib.sha256(frame).hexdigest()); sizes.append(n); count += 1
        if count == 1: (out/'stream-first-frame.jpg').write_bytes(frame)
elapsed = time.monotonic()-started
after = json.loads(get('/status'))
report = {'host': a.host,'elapsed_s': round(elapsed,2),'decoded_frames':count,'fps':round(count/elapsed,2),
          'unique_frames':len(hashes),'min_bytes':min(sizes),'max_bytes':max(sizes),'before':before,'after':after}
assert count >= 10 and len(hashes) > 1, report
(out/'stream-verification.json').write_text(json.dumps(report,indent=2), encoding='utf-8')
print(json.dumps(report,indent=2),flush=True)

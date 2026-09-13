"""Download the exact PlatformIO registry archive using verified range requests."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import requests
import time

URL = 'https://sin1.contabostorage.com/fd833e6c4db04192b0ad7e561907b935:pioregmirrorsg/tools/27/0f/b2b64783933fe486b269488257a1b717ec091ce3a30e63e0823f87fa1c67/toolchain-xtensa-esp32-windows_amd64-8.4.0+2021r2-patch5.tar.gz'
SIZE = 120571066
SHA = 'abc98e1765139746154dc2927e3438eb7a65478909463210f4b5fb984cee0491'
OUT = Path(__file__).resolve().parents[1] / 'artifacts/toolchain.tar.gz'
OUT.parent.mkdir(parents=True, exist_ok=True)
STEP = 4*1024*1024

def fetch(start):
    end = min(start+STEP, SIZE)-1
    s = requests.Session()
    s.trust_env = False
    for attempt in range(3):
        try:
            r = s.get(URL, headers={'Range': f'bytes={start}-{end}'}, timeout=(10, 30))
            r.raise_for_status()
            assert r.status_code == 206 and r.headers['Content-Range'].startswith(f'bytes {start}-{end}/')
            assert len(r.content) == end-start+1
            return start, r.content
        except Exception:
            if attempt == 2: raise

began = time.monotonic()
with OUT.open('wb') as f:
    f.truncate(SIZE)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch, start) for start in range(0, SIZE, STEP)]
        for i, future in enumerate(as_completed(futures), 1):
            start, data = future.result()
            f.seek(start); f.write(data)
            print(f'{i}/{len(futures)} chunks in {time.monotonic()-began:.1f}s', flush=True)
actual = hashlib.sha256(OUT.read_bytes()).hexdigest()
assert actual == SHA, actual
print('VERIFIED', OUT, actual, flush=True)

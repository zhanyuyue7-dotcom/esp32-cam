import argparse
from pathlib import Path
import time
import serial

p = argparse.ArgumentParser()
p.add_argument('--port', default='COM37')
p.add_argument('--seconds', type=int, default=45)
p.add_argument('--reset', action='store_true')
p.add_argument('--out', default='artifacts/serial.log')
a = p.parse_args()
out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
s = serial.Serial(); s.port = a.port; s.baudrate = 115200
s.timeout = .2; s.dtr = False; s.rts = False; s.open()
if a.reset:
    s.rts = True; time.sleep(.15); s.rts = False
end = time.monotonic()+a.seconds
with out.open('w', encoding='utf-8') as f:
    while time.monotonic() < end:
        data = s.read(s.in_waiting or 1)
        if data:
            text = data.decode('utf-8', errors='replace')
            f.write(text); f.flush(); print(text, end='', flush=True)
s.close()

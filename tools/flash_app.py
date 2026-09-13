"""Flash this camera's factory app only. Never writes NVS, PHY or the partition table."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--port', default='COM37')
a = p.parse_args()
fw = ROOT/'.pio/build/esp32cam/firmware.bin'
backup = ROOT/'backups/20260909-original/flash-4mb.bin'
assert backup.stat().st_size == 0x400000, 'Full original backup required'
assert hashlib.sha256(backup.read_bytes()).hexdigest() == '66661b5531ac90a917cdd0e6c7c9d4eb10b5e298312c2207382d0fb8884b3d40'
data = fw.read_bytes()
assert len(data) <= 0x180000 and data[0] == 0xe9, 'App must fit original factory partition'
base = [sys.executable, '-m', 'esptool', '--chip', 'esp32', '--port', a.port, '--baud', '460800']
probe = subprocess.run(base+['chip_id'], capture_output=True, text=True, check=True).stdout
assert 'ec:e3:34:d9:ed:e0' in probe.lower(), 'Wrong board; refusing to flash'
print(probe, flush=True)
result = subprocess.run(base+['write_flash', '0x10000', str(fw)], capture_output=True, text=True)
print(result.stdout, flush=True)
artifacts = ROOT/'artifacts'; artifacts.mkdir(exist_ok=True)
(artifacts/'flash.log').write_text(result.stdout+'\n'+result.stderr, encoding='utf-8')
result.check_returncode()
assert 'Hash of data verified.' in result.stdout
manifest = {'port': a.port,'mac':'ec:e3:34:d9:ed:e0','address':'0x10000','bytes':len(data),
            'sha256':hashlib.sha256(data).hexdigest(),'write_scope':'factory app only',
            'untouched_by_flash':['bootloader','partition table','NVS','PHY data']}
(artifacts/'firmware.bin').write_bytes(data)
(artifacts/'firmware-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest,indent=2),flush=True)

#!/usr/bin/env python3
"""Flash an image over the ESP32 SWS flasher in one session, then verify by on-chip CRC.
Usage: flash.py file [addr] [--late]
  --late: power-cycle, let the current firmware run 4 s (for images that grab the SWS
          pad at boot but release it later), re-sync without reset, stop the CPU."""
import sys, time, zlib, serial
args = [a for a in sys.argv[1:] if not a.startswith('--')]
fn = args[0]; base = int(args[1], 0) if len(args) > 1 else 0
img = open(fn, 'rb').read(); pad = img.ljust((len(img) + 0xfff) & ~0xfff, b'\xff')
s = serial.Serial('/dev/ttyUSB0', 460800, timeout=8); time.sleep(4.5); s.reset_input_buffer()
def cmd(c):
    s.write((c + '\n').encode())
    while True:
        l = s.readline().decode(errors='replace').strip()
        if not l: return 'ERR timeout'
        if l.startswith(('OK', 'ERR')): return l
for c in ('MODE uart', 'BAUD 400000', 'BURST 1'): cmd(c)
if '--late' in sys.argv:
    cmd('RST'); time.sleep(4); r = cmd('A 0'); print(r); print('stop', cmd('S 0x602 05'))
else:
    r = cmd('A 1000'); print(r)
if not r.startswith('OK'): sys.exit('no SWS link')
print('id', cmd('G 0x7e 2'), 'flash', cmd('FJ'))
if base <= 0x76000 < base + len(pad): sys.exit('refusing: range covers MAC sector 0x76000')
for a in range(0, len(pad), 0x1000):
    r = cmd(f'FE {base+a:#x}')
    if not r.startswith('OK'): sys.exit(f'erase {base+a:#x}: {r}')
    for p in range(a, min(a + 0x1000, len(img)), 256):
        r = cmd(f'FW {base+p:#x} {img[p:p+256].hex()}')
        if not r.startswith('OK'): sys.exit(f'write {base+p:#x}: {r}')
    print(f'\r{base+a:#07x}', end='', flush=True)
print(); bad = 0
for a in range(0, len(pad), 0x1000):
    got = cmd(f'FC {base+a:#x} 4096'); exp = '%08x' % zlib.crc32(pad[a:a+0x1000])
    if not got.endswith(exp): bad += 1; print(f'{base+a:#07x} MISMATCH {exp} {got}')
print('VERIFY OK' if not bad else f'{bad} bad sectors')
if '--boot' in sys.argv and not bad: print('boot', cmd('RST'))

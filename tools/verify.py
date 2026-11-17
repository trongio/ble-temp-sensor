#!/usr/bin/env python3
"""Verify a flashed image per 4K sector via on-chip CRC (FC). Usage: verify.py file [addr]"""
import sys, time, zlib, serial
fn = sys.argv[1]; base = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
b = open(fn, 'rb').read(); b = b.ljust((len(b) + 0xfff) & ~0xfff, b'\xff')
s = serial.Serial('/dev/ttyUSB0', 460800, timeout=8); time.sleep(4.5); s.reset_input_buffer()
def cmd(c):
    s.write((c + '\n').encode())
    while True:
        l = s.readline().decode().strip()
        if l.startswith(('OK', 'ERR')) or not l: return l
for c in ('MODE uart', 'BAUD 400000'): cmd(c)
print(cmd('A 500')); bad = 0
for a in range(0, len(b), 0x1000):
    got = cmd(f'FC {base+a:#x} 4096'); exp = '%08x' % zlib.crc32(b[a:a+0x1000])
    if not got.endswith(exp): bad += 1; print(f'{base+a:#07x} MISMATCH exp {exp} got {got}')
print('ALL OK' if not bad else f'{bad} bad sectors')

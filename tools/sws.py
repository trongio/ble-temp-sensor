#!/usr/bin/env python3
"""Send raw commands to the ESP32 tlsr-c3-flasher in ONE serial session.
Usage: sws.py "CMD1" "CMD2" ...   ("sleep 2" pauses). Opening the port resets the ESP,
which re-activates (halts) the target; we wait for that before sending."""
import sys, time, serial
s = serial.Serial('/dev/ttyUSB0', 460800, timeout=3)
time.sleep(4.5); s.reset_input_buffer()
def cmd(c):
    s.write((c + '\n').encode()); out = []
    t = time.time()
    while time.time() - t < 8:
        l = s.readline().decode(errors='replace').strip()
        if not l: continue
        out.append(l)
        if l.startswith(('OK', 'ERR', 'E ')): break
    return out
for c in sys.argv[1:]:
    if c.startswith('sleep'): time.sleep(float(c.split()[1])); continue
    print(f'> {c}'); [print('  ' + l) for l in cmd(c)]

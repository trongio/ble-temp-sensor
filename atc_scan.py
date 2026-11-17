"""Scan for a Telink sensor running open firmware (pvvx ATC_MiThermometer / BTHome)
and print decoded temperature / humidity. No pairing, no bindkey — these firmwares
broadcast in the clear.

Decodes the three advert formats such firmware emits:
  * pvvx "custom"  - service data UUID 0x181A, 15-byte little-endian payload
  * ATC1441        - service data UUID 0x181A, 13-byte big-endian payload
  * BTHome v2      - service data UUID 0xFCD2, typed objects
"""
from __future__ import annotations

import argparse
import asyncio
import struct
import sys
from datetime import datetime

from bleak import BleakScanner

UUID_181A = "0000181a-0000-1000-8000-00805f9b34fb"
UUID_BTHOME = "0000fcd2-0000-1000-8000-00805f9b34fb"


def decode_pvvx(d: bytes) -> dict | None:
    # size(1) MAC(6,LE) temp(int16,0.01C) humi(uint16,0.01%) batt_mv(uint16) batt%(1) cnt(1) flags(1)
    if len(d) != 15:
        return None
    mac = ":".join("%02X" % b for b in d[6:0:-1])
    t, h, mv = struct.unpack_from("<hHH", d, 7)
    return {"fmt": "pvvx", "mac": mac, "temperature": t / 100, "humidity": h / 100,
            "battery": d[13], "batt_mv": mv}


def decode_atc1441(d: bytes) -> dict | None:
    # MAC(6,BE) temp(int16,0.1C,BE) humi(uint8) batt%(1) batt_mv(uint16,BE) cnt(1)
    if len(d) != 13:
        return None
    mac = ":".join("%02X" % b for b in d[0:6])
    t = struct.unpack_from(">h", d, 6)[0]
    return {"fmt": "atc1441", "mac": mac, "temperature": t / 10, "humidity": d[8],
            "battery": d[9]}


def decode_bthome(d: bytes) -> dict | None:
    if len(d) < 1:
        return None
    out: dict = {"fmt": "bthome"}
    i = 1  # skip device-info byte
    while i < len(d):
        oid = d[i]; i += 1
        if oid == 0x02 and i + 2 <= len(d):      # temperature int16 0.01
            out["temperature"] = struct.unpack_from("<h", d, i)[0] / 100; i += 2
        elif oid == 0x03 and i + 2 <= len(d):    # humidity uint16 0.01
            out["humidity"] = struct.unpack_from("<H", d, i)[0] / 100; i += 2
        elif oid == 0x2E and i + 1 <= len(d):    # humidity uint8
            out["humidity"] = d[i]; i += 1
        elif oid == 0x01 and i + 1 <= len(d):    # battery %
            out["battery"] = d[i]; i += 1
        elif oid == 0x0C and i + 2 <= len(d):    # voltage uint16 0.001
            out["batt_v"] = struct.unpack_from("<H", d, i)[0] / 1000; i += 2
        else:
            break
    return out if "temperature" in out or "humidity" in out else None


def decode(adv) -> dict | None:
    sd = adv.service_data
    if UUID_181A in sd:
        raw = sd[UUID_181A]
        return decode_pvvx(raw) or decode_atc1441(raw) or {"fmt": "181A?", "raw": raw.hex()}
    if UUID_BTHOME in sd:
        return decode_bthome(sd[UUID_BTHOME])
    return None


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mac", help="only show this address (e.g. A4:C1:38:CB:81:A7)")
    p.add_argument("--once", action="store_true", help="exit after the first decoded reading")
    p.add_argument("--timeout", type=float, default=60)
    args = p.parse_args()
    want = args.mac.upper() if args.mac else None
    done = asyncio.Event()

    def cb(dev, adv):
        if want and dev.address.upper() != want:
            return
        r = decode(adv)
        if not r:
            return
        ts = datetime.now().isoformat(timespec="seconds")
        extra = "  ".join(f"{k}={v}" for k, v in r.items() if k not in ("fmt", "mac"))
        print(f"{ts}  {dev.address}  [{r.get('fmt')}]  {extra}", flush=True)
        if args.once and ("temperature" in r or "humidity" in r):
            done.set()

    async with BleakScanner(cb):
        print(f"Scanning{' for ' + want if want else ''} (Ctrl+C to stop)...", file=sys.stderr)
        try:
            if args.once:
                await asyncio.wait_for(done.wait(), args.timeout)
            else:
                await asyncio.Event().wait()
        except asyncio.TimeoutError:
            print("No open-firmware broadcast seen.", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

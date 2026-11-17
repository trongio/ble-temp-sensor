#!/usr/bin/env python3
# Verify pvvx ATC_MiThermometer broadcasts. Run with: python3 -I verify_adv.py
# Needs: pip install bleak
# Decodes the three formats pvvx can emit:
#   - BTHome v2  (service data UUID 0xFCD2)  <-- pvvx DEFAULT out of the box
#   - pvvx "custom" (service data UUID 0x181A, 15-byte payload)
#   - ATC1441   (service data UUID 0x181A, 13-byte payload, big-endian temp)
import asyncio, struct
from bleak import BleakScanner

TARGET_MAC = "A4:C1:38:CB:81:A7"   # set to None to show all T/H beacons

def parse_bthome(d: bytes):
    # d = service data bytes for UUID 0xFCD2
    out = {}
    if not d or d[0] & 0x01:  # bit0 set => encrypted; we flash unencummbered default
        return out
    i = 1
    while i < len(d):
        oid = d[i]; i += 1
        if oid == 0x00 and i < len(d):            # packet id
            out["pid"] = d[i]; i += 1
        elif oid == 0x01 and i < len(d):          # battery %
            out["batt_%"] = d[i]; i += 1
        elif oid == 0x02 and i+1 < len(d):        # temperature int16 x0.01 C
            out["temp_C"] = struct.unpack_from("<h", d, i)[0] / 100; i += 2
        elif oid == 0x03 and i+1 < len(d):        # humidity uint16 x0.01 %
            out["humi_%"] = struct.unpack_from("<H", d, i)[0] / 100; i += 2
        elif oid == 0x0C and i+1 < len(d):        # voltage uint16 x0.001 V
            out["volt_V"] = struct.unpack_from("<H", d, i)[0] / 1000; i += 2
        else:
            break
    return out

def parse_181a(d: bytes):
    # d = service data for UUID 0x181A (after the 2-byte UUID)
    if len(d) >= 15:  # pvvx custom: MAC(6)+temp(2)+humi(2)+mv(2)+bat(1)+cnt(1)+flg(1)
        temp = struct.unpack_from("<h", d, 6)[0] / 100
        humi = struct.unpack_from("<H", d, 8)[0] / 100
        mv   = struct.unpack_from("<H", d, 10)[0]
        return {"fmt": "pvvx-custom", "temp_C": temp, "humi_%": humi, "batt_mV": mv,
                "batt_%": d[12], "cnt": d[13]}
    if len(d) >= 13:  # ATC1441: MAC(6)+temp_be(2 x0.1)+humi(1)+bat%(1)+mv_be(2)+cnt(1)
        temp = struct.unpack_from(">h", d, 6)[0] / 10
        return {"fmt": "atc1441", "temp_C": temp, "humi_%": d[8], "batt_%": d[9],
                "batt_mV": struct.unpack_from(">H", d, 10)[0], "cnt": d[12]}
    return {}

def cb(dev, adv):
    if TARGET_MAC and dev.address.upper() != TARGET_MAC:
        return
    for uuid, data in (adv.service_data or {}).items():
        u = uuid.lower()
        if u.startswith("0000fcd2"):
            r = parse_bthome(bytes(data))
            if r: print(dev.address, "BTHome", r)
        elif u.startswith("0000181a"):
            r = parse_181a(bytes(data))
            if r: print(dev.address, r)

async def main():
    print("Scanning (Ctrl-C to stop). Looking for", TARGET_MAC or "any T/H beacon")
    scanner = BleakScanner(detection_callback=cb)
    await scanner.start(); await asyncio.sleep(60); await scanner.stop()

if __name__ == "__main__":
    asyncio.run(main())

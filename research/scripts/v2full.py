import asyncio, sys, time
sys.path.insert(0, "/home/azael/Documents/Github/ble-temp-sensor")
from mi_sensor import *

ADDR = "A4:C1:38:CB:81:A7"

async def drain_listen(s, secs):
    """Collect every AVDTP/UPNP notification for `secs`, reassembling parcels."""
    end = time.time() + secs
    while time.time() < end:
        try:
            hdr = await s._get(s.avdtp, max(0.2, end - time.time()))
        except asyncio.TimeoutError:
            break
        if hdr[:2] == b"\0\0" and len(hdr) >= 6 and hdr[2] in (0, 2):
            if hdr[2] == 2:
                print(f"  LISTEN single parcel type={hdr[3]:#04x}: {hdr[4:].hex()}")
                continue
            kind, frames = hdr[3], hdr[4] | hdr[5] << 8
            await s._w(AVDTP, RCV_RDY)
            buf = b""
            for _ in range(frames):
                try: buf += (await s._get(s.avdtp, 3))[2:]
                except asyncio.TimeoutError: break
            await s._w(AVDTP, RCV_OK)
            print(f"  LISTEN parcel type={kind:#04x} len={len(buf)}: {buf.hex()}")
        else:
            print(f"  LISTEN raw: {hdr.hex()}")
    while not s.upnp.empty():
        print("  LISTEN UPNP:", s.upnp.get_nowait().hex())

async def main():
    for _ in range(4):
        try: c = await connect(ADDR); break
        except Exception as e: print("connect failed:", type(e).__name__); await asyncio.sleep(2)
    else: return
    s = MiSession(c, debug=False); await s.start()
    await s._w(UPNP, CMD_GET_INFO)
    print("info:", (await s.recv_parcel()).hex())
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)[1:]
    await s._w(UPNP, bytes.fromhex("15020000"))
    await s.send_parcel(0x03, pub)
    dev_pub = await s.recv_parcel()
    print(f"device pubkey ({len(dev_pub)}B): {dev_pub.hex()}")

    print("--- listening 12s for unprompted device parcels (cert chain?) ---")
    await drain_listen(s, 12)

    if not c.is_connected:
        print("device disconnected during listen"); return

    print("--- sweeping every parcel header type for an ACK ---")
    for kind in range(0x00, 0x0f):
        if not c.is_connected: print("disconnected at type", hex(kind)); return
        await s._w(AVDTP, bytes([0, 0, 0, kind, 1, 0]))
        try:
            r = await s._get(s.avdtp, 2.0)
            print(f"  type {kind:#04x}: ACK {r.hex()}")
        except asyncio.TimeoutError:
            print(f"  type {kind:#04x}: silent")
    print("connected:", c.is_connected)
    await c.disconnect()

asyncio.run(main())

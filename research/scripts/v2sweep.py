import asyncio, sys
sys.path.insert(0, "/home/azael/Documents/Github/ble-temp-sensor")
from mi_sensor import *

async def main():
    for attempt in range(3):
        try:
            c = await connect("A4:C1:38:CB:81:A7"); break
        except Exception as e:
            print("connect failed:", type(e).__name__); await asyncio.sleep(2)
    else:
        return
    s = MiSession(c, debug=False); await s.start()
    await s._w(UPNP, CMD_GET_INFO); await s.recv_parcel()
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)[1:]
    await s._w(UPNP, bytes.fromhex(sys.argv[1] if len(sys.argv) > 1 else "15020000"))
    await s.send_parcel(0x03, pub); await s.recv_parcel()
    print("pubkeys exchanged; sweeping parcel header types")
    for kind in [0x00, 0x0b, 0x0a, 0x07, 0x05, 0x06]:
        for frames in range(1, 6):
            if not c.is_connected:
                print("disconnected"); return
            await s._w(AVDTP, bytes([0, 0, 0, kind, frames, 0]))
            try:
                r = await s._get(s.avdtp, 1.5)
                print(f"kind {kind:#04x} frames {frames}: ANSWER {r.hex()}")
                await c.disconnect(); return
            except asyncio.TimeoutError:
                pass
        print(f"kind {kind:#04x}: silent for 1..5 frames")
    await c.disconnect()

asyncio.run(main())

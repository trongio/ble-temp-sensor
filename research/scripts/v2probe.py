import asyncio, sys
sys.path.insert(0, "/home/azael/Documents/Github/ble-temp-sensor")
from mi_sensor import *
async def recv_any(s, t=8):
    try: hdr = await s._get(s.avdtp, t)
    except asyncio.TimeoutError: return None
    if hdr[:2]!=b"\0\0" or len(hdr)<6:
        print("  non-header:", hdr.hex()); return ("raw", hdr)
    if hdr[2]==2:
        print(f"  single-frame parcel kind={hdr[3]:#04x}: {hdr[4:].hex()}"); return (hdr[3], hdr[4:])
    kind, frames = hdr[3], hdr[4]|hdr[5]<<8
    await s._w(AVDTP, RCV_RDY); buf=b""
    for _ in range(frames): buf += (await s._get(s.avdtp))[2:]
    await s._w(AVDTP, RCV_OK)
    print(f"  parcel kind={kind:#04x} len={len(buf)}: {buf.hex()}"); return (kind, buf)
async def main():
    for attempt in range(3):
        try:
            c = await connect("A4:C1:38:CB:81:A7"); break
        except Exception as e:
            print("connect attempt failed:", type(e).__name__); await asyncio.sleep(2)
    else: return
    s = MiSession(c, debug=True); await s.start()
    await s._w(UPNP, CMD_GET_INFO); print("info", (await s.recv_parcel()).hex())
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)[1:]
    await s._w(UPNP, bytes.fromhex("15020000"))
    await s.send_parcel(0x03, pub)
    got = []
    while (p := await recv_any(s)) is not None: got.append(p)
    while not s.upnp.empty(): print("  UPNP:", s.upnp.get_nowait().hex())
    print("received parcels:", [(k if isinstance(k,str) else hex(k), len(d)) for k,d in got])
    await c.disconnect()
asyncio.run(main())

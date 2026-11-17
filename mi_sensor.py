"""Direct BLE access to a Xiaomi (MiBeacon v5 / "standard auth") temp/humidity sensor.

No Xiaomi cloud or app needed:
  * `register` performs the Mi standard-auth ECDH pairing with an *unbound* sensor
    and stores the resulting token + bindkey locally (keys.json, git-ignored).
  * `login` proves a direct authenticated GATT session using the token.
  * `read` listens to the sensor's encrypted advertisements and decrypts
    temperature / humidity / battery with the bindkey.

Protocol details adapted from miauth (AGPL-3.0, Daljeet Nandha) and the work of
Aaron Christophel (atc1441) and Daniel Kucera (mi-standardauth).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import struct
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MI_SERVICE = "0000fe95-0000-1000-8000-00805f9b34fb"
UPNP = "00000010-0000-1000-8000-00805f9b34fb"
AVDTP = "00000019-0000-1000-8000-00805f9b34fb"

CMD_GET_INFO = bytes.fromhex("a2000000")
CMD_SET_KEY = bytes.fromhex("15000000")
CMD_AUTH = bytes.fromhex("13000000")
CMD_LOGIN = bytes.fromhex("24000000")

RCV_RDY = bytes.fromhex("00000101")
RCV_OK = bytes.fromhex("00000100")

KEYS_FILE = Path(__file__).with_name("keys.json")


# --------------------------------------------------------------------------- crypto
def hkdf(secret: bytes, info: bytes, salt: bytes | None = None) -> bytes:
    return HKDF(hashes.SHA256(), 64, salt, info).derive(secret)


def hmac256(key: bytes, data: bytes) -> bytes:
    h = HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


# --------------------------------------------------------------------------- GATT session
class MiSession:
    """Implements the Mi 'parcel' transfer on top of the UPNP/AVDTP characteristics."""

    def __init__(self, client: BleakClient, debug: bool = False):
        self.c = client
        self.debug = debug
        self.avdtp: asyncio.Queue[bytes] = asyncio.Queue()
        self.upnp: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self):
        await self.c.start_notify(UPNP, lambda _, d: self._put(self.upnp, "UPNP", d))
        await self.c.start_notify(AVDTP, lambda _, d: self._put(self.avdtp, "AVDTP", d))

    def _put(self, q, name, data):
        if self.debug:
            print(f"  {name} <- {bytes(data).hex()}")
        q.put_nowait(bytes(data))

    async def _w(self, uuid, data: bytes):
        if self.debug:
            print(f"  {'UPNP' if uuid == UPNP else 'AVDTP'} -> {data.hex()}")
        await self.c.write_gatt_char(uuid, data, response=False)

    async def _get(self, q, timeout=10.0) -> bytes:
        return await asyncio.wait_for(q.get(), timeout)

    async def recv_parcel(self) -> bytes:
        hdr = await self._get(self.avdtp)
        if hdr[:3] != b"\0\0\0" or len(hdr) < 6:
            raise RuntimeError(f"unexpected parcel header {hdr.hex()}")
        frames = hdr[4] | hdr[5] << 8
        await self._w(AVDTP, RCV_RDY)
        buf = b""
        for _ in range(frames):
            f = await self._get(self.avdtp)
            buf += f[2:]
        await self._w(AVDTP, RCV_OK)
        return buf

    async def send_parcel(self, kind: int, data: bytes, retries: int = 1):
        frames = (len(data) + 17) // 18
        hdr = bytes([0, 0, 0, kind, frames & 0xFF, frames >> 8])
        for attempt in range(retries):
            await self._w(AVDTP, hdr)
            try:
                r = await self._get(self.avdtp, timeout=4.0)
                break
            except asyncio.TimeoutError:
                if self.debug:
                    print(f"  (no answer to header, retry {attempt + 1})")
        else:
            raise RuntimeError("device never acknowledged parcel header")
        if r != RCV_RDY:
            raise RuntimeError(f"device not ready to receive: {r.hex()}")
        for i in range(frames):
            await self._w(AVDTP, bytes([i + 1, 0]) + data[i * 18:(i + 1) * 18])
        r = await self._get(self.avdtp)
        if r != RCV_OK:
            raise RuntimeError(f"device rejected parcel: {r.hex()}")

    # ---- standard-auth registration (device must be unbound)
    async def register(self, did: bytes) -> dict:
        await self._w(UPNP, CMD_GET_INFO)
        info = await self.recv_parcel()
        remote_did = info[4:]
        if remote_did:
            did = remote_did
        if len(did) != 20:
            raise RuntimeError(f"DID must be 20 bytes, got {len(did)}")

        priv = ec.generate_private_key(ec.SECP256R1())
        pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)[1:]

        await self._w(UPNP, CMD_SET_KEY)
        await self.send_parcel(0x03, pub)
        remote_pub = await self.recv_parcel()

        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + remote_pub)
        shared = priv.exchange(ec.ECDH(), peer)
        dk = hkdf(shared, b"mible-setup-info")
        token, bind_key, a = dk[0:12], dk[12:28], dk[28:44]

        did_ct = AESCCM(a, tag_length=4).encrypt(bytes(range(16, 28)), did, b"devID")
        await asyncio.sleep(2)  # let the MCU finish its ECDH computation
        await self.send_parcel(0x00, did_ct, retries=6)

        while not self.upnp.empty():  # drop stale status notifications
            self.upnp.get_nowait()
        await self._w(UPNP, CMD_AUTH)
        r = await self._get(self.upnp)
        if r[0] != 0x11:
            raise RuntimeError(f"registration failed (code {r.hex()})")
        return {"token": token.hex(), "bindkey": bind_key.hex(), "did": did.strip(b"\0").decode(errors="replace")}

    # ---- login with a stored token
    async def login(self, token: bytes) -> dict:
        rand = secrets.token_bytes(16)
        await self._w(UPNP, CMD_LOGIN)
        await self.send_parcel(0x0B, rand)
        remote_key = await self.recv_parcel()
        remote_info = await self.recv_parcel()

        dk = hkdf(token, b"mible-login-info", salt=rand + remote_key)
        keys = {"dev_key": dk[:16], "app_key": dk[16:32], "dev_iv": dk[32:36], "app_iv": dk[36:40]}
        if remote_info != hmac256(keys["dev_key"], remote_key + rand):
            raise RuntimeError("device proof mismatch – wrong token?")
        await self.send_parcel(0x0A, hmac256(keys["app_key"], rand + remote_key))
        r = await self._get(self.upnp)
        if r[0] != 0x21:
            raise RuntimeError(f"login failed (code {r.hex()})")
        return keys


async def wait_for_bind_confirm(addr: str, timeout: float = 90) -> object:
    """'Front binding' sensors (capability BondAbility=1) only accept registration
    after the user presses the button; they then advertise frame-control bit 9."""
    addr = addr.upper()
    found: asyncio.Future = asyncio.get_running_loop().create_future()

    def cb(dev, adv):
        sd = adv.service_data.get(MI_SERVICE)
        if dev.address.upper() == addr and sd and len(sd) >= 2:
            fc = struct.unpack_from("<H", sd)[0]
            if fc & 0x200 and not found.done():
                found.set_result(dev)

    print(">> Hold the sensor's button ~2 s until it starts blinking...", flush=True)
    async with BleakScanner(cb):
        dev = await asyncio.wait_for(found, timeout)
    print(">> Binding confirmation seen, connecting.", flush=True)
    return dev


async def connect(addr: str, dev=None) -> BleakClient:
    dev = dev or await BleakScanner.find_device_by_address(addr, timeout=20)
    if dev is None:
        sys.exit(f"Sensor {addr} not found – is it nearby and awake?")
    client = BleakClient(dev, timeout=20)
    await client.connect()
    return client


# --------------------------------------------------------------------------- MiBeacon decoding
def parse_objects(payload: bytes) -> dict:
    out, i = {}, 0
    while i + 3 <= len(payload):
        oid, ln = struct.unpack_from("<HB", payload, i)
        v = payload[i + 3:i + 3 + ln]
        i += 3 + ln
        if oid == 0x1004 and ln == 2:
            out["temperature"] = struct.unpack("<h", v)[0] / 10
        elif oid == 0x1006 and ln == 2:
            out["humidity"] = struct.unpack("<H", v)[0] / 10
        elif oid == 0x100D and ln == 4:
            t, h = struct.unpack("<hH", v)
            out["temperature"], out["humidity"] = t / 10, h / 10
        elif oid == 0x100A and ln >= 1:
            out["battery"] = v[0]
        elif oid == 0x4C01 and ln == 4:
            out["temperature"] = round(struct.unpack("<f", v)[0], 2)
        elif oid in (0x4C02, 0x4C08) and ln >= 1:
            out["humidity"] = struct.unpack("<f", v)[0] if ln == 4 else v[0]
        elif oid == 0x4803 and ln >= 1:
            out["battery"] = v[0]
        else:
            out[f"obj_{oid:04x}"] = v.hex()
    return out


def decode_mibeacon(data: bytes, mac: str, bindkey: bytes | None) -> dict | None:
    if len(data) < 5:
        return None
    fc, pid, cnt = struct.unpack_from("<HHB", data)
    i = 5
    if fc & 0x10:  # MAC included
        i += 6
    if fc & 0x20:  # capability byte
        cap = data[i]
        i += 1
        if cap & 0x20:
            i += 2
    if not fc & 0x40:  # no object payload
        return None
    if fc & 0x08:  # encrypted
        if bindkey is None or (fc >> 12) < 4:
            return None
        mac_le = bytes.fromhex(mac.replace(":", ""))[::-1]
        ct, ext, mic = data[i:-7], data[-7:-4], data[-4:]
        nonce = mac_le + data[2:5] + ext
        try:
            payload = AESCCM(bindkey, tag_length=4).decrypt(nonce, ct + mic, b"\x11")
        except Exception:
            return {"error": "decrypt failed (wrong bindkey?)"}
    else:
        payload = data[i:]
    return parse_objects(payload)


# --------------------------------------------------------------------------- CLI
def load_keys() -> dict:
    if not KEYS_FILE.exists():
        sys.exit(f"{KEYS_FILE.name} not found – run `register` first.")
    return json.loads(KEYS_FILE.read_text())


async def cmd_scan(_):
    print("Scanning 10 s for Xiaomi (FE95) devices...")
    found = await BleakScanner.discover(timeout=10, return_adv=True)
    for addr, (d, adv) in found.items():
        if MI_SERVICE in adv.service_data:
            sd = adv.service_data[MI_SERVICE]
            fc = struct.unpack_from("<H", sd)[0]
            bound = "bound" if fc & 0x100 else "unbound"
            print(f"{addr}  rssi={adv.rssi}  name={adv.local_name!r}  v{fc >> 12} {bound}")


async def cmd_register(args):
    if KEYS_FILE.exists() and not args.force:
        sys.exit(f"{KEYS_FILE.name} already exists; use --force to re-register.")
    # same layout TelinkMiFlasher uses: 0x00 + "blt.3.129v" + 6 random + "g00"
    did_b = (b"\0" + args.did.encode()).ljust(20, b"\0")[:20] if args.did else \
        b"\0" + b"blt.3.129v" + secrets.token_hex(3).encode() + b"g00"
    dev = None if args.no_wait else await wait_for_bind_confirm(args.addr)
    client = await connect(args.addr, dev)
    try:
        s = MiSession(client, args.debug)
        await s.start()
        keys = await s.register(did_b)
    finally:
        await client.disconnect()
    keys["address"] = args.addr
    KEYS_FILE.write_text(json.dumps(keys, indent=2))
    KEYS_FILE.chmod(0o600)
    print(f"Registered! token/bindkey saved to {KEYS_FILE}")


async def cmd_login(args):
    keys = load_keys()
    client = await connect(args.addr or keys["address"])
    try:
        s = MiSession(client, args.debug)
        await s.start()
        await s.login(bytes.fromhex(keys["token"]))
        print("Login successful – authenticated direct GATT session established.")
    finally:
        await client.disconnect()


async def cmd_read(args):
    keys = load_keys()
    addr = (args.addr or keys["address"]).upper()
    bindkey = bytes.fromhex(keys["bindkey"])
    seen: set = set()
    done = asyncio.Event()

    def cb(dev, adv):
        if dev.address.upper() != addr or MI_SERVICE not in adv.service_data:
            return
        raw = adv.service_data[MI_SERVICE]
        if raw in seen:
            return
        seen.add(raw)
        r = decode_mibeacon(raw, addr, bindkey)
        if args.debug:
            print("  adv", raw.hex(), "->", r)
        if r:
            ts = datetime.now().isoformat(timespec="seconds")
            if args.json:
                print(json.dumps({"time": ts, **r}), flush=True)
            else:
                print(ts, "  ".join(f"{k}={v}" for k, v in r.items()), flush=True)
            if args.once and "temperature" in r:
                done.set()

    async with BleakScanner(cb):
        print(f"Listening for {addr} (Ctrl+C to stop)...", file=sys.stderr)
        if args.once:
            await asyncio.wait_for(done.wait(), args.timeout)
        else:
            await asyncio.Event().wait()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--debug", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="find nearby Xiaomi BLE devices")
    r = sub.add_parser("register", help="pair an unbound sensor, save token+bindkey")
    r.add_argument("addr")
    r.add_argument("--did", help="device ID to assign (default: random blt.3.*)")
    r.add_argument("--force", action="store_true")
    r.add_argument("--no-wait", action="store_true", help="don't wait for button-press confirmation")
    lg = sub.add_parser("login", help="authenticate over GATT with the saved token")
    lg.add_argument("addr", nargs="?")
    rd = sub.add_parser("read", help="decode live temperature/humidity")
    rd.add_argument("addr", nargs="?")
    rd.add_argument("--once", action="store_true", help="exit after first reading")
    rd.add_argument("--timeout", type=float, default=120)
    rd.add_argument("--json", action="store_true")
    args = p.parse_args()
    try:
        asyncio.run({"scan": cmd_scan, "register": cmd_register, "login": cmd_login, "read": cmd_read}[args.cmd](args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

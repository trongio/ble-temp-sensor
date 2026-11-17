# ble-temp-sensor

Freeing a Yanmi ESM787 (`ym001.sensor_ht.ymwsdj`, TLSR8253) Mijia temperature/humidity
sensor from the Xiaomi cloud by flashing open firmware (pvvx ATC_MiThermometer / BTHome)
over Telink SWS with an ESP32.

**Status: work in progress — see [HANDOFF.md](HANDOFF.md) for full state and next steps.**

## Layout
| Path | What |
|---|---|
| `HANDOFF.md` | Full findings, rig wiring, addresses, hypotheses |
| `mi_sensor.py` | Mijia BLE scan / register attempt (documents std-auth v2 dead end) |
| `atc_scan.py` | Decodes pvvx-custom / ATC1441 / BTHome adverts |
| `tools/sws.py` | Raw command session to the ESP32 SWS flasher |
| `tools/verify.py` | Per-4K-sector on-chip CRC verify of a flashed image (reliable, avoids big reads) |
| `esp-flasher/` | ESP32 port of [tlsr-c3-flasher](https://github.com/gyimesibalazs/tlsr-c3-flasher) (diff in `patches/`) |
| `fw/` | pvvx v5.9 builds for different boards/pin pairs |
| `backup/` | Stock firmware 0x0–0x20000 and MAC/cal sector 0x76000 of the target sensor |
| `patches/` | Local changes to upstream repos + their commit hashes |
| `research/` | Probe scripts, protocol refs, upstream reference code |
| `photos/` | Board and wiring photos |

## Status (2026-11-17): WORKING
`fw/YANMI_v59.bin` (pvvx v5.9, `DEVICE_ZBEACON2TH01_SHTC3` config retargeted, see
`patches/pvvx-ATC_MiThermometer-app_config.patch`) advertises BTHome v2 (UUID 0xFCD2)
as `ATC_CB81A7` with temperature, humidity and battery.

Board facts (Yanmi VCH6043-V03, TLSR8253):
- Sensor: **SHTC3 at I2C 0x70, SCL = PA7 (the SWS pad), SDA = PC5** (found with
  `test-fw/i2cscan.c`). No stock pvvx build uses these pins, which is why all of them failed.
- pvvx's software I2C (no `I2C_GROUP`) supports arbitrary pins.
- LCD controller: not on that I2C bus; display not yet supported (display disabled).
- Firmware that uses PA7 kills SWS right after boot; the activation (reset + stall) still
  catches it. Flash with `tools/flash.py` (`--late` for images that grab PA7 instantly).
- Resuming the CPU from an SWS stall (0x602=0x88) does NOT really run it; PC reads 0x0d0
  regardless. Test run-state only with a real cold boot (`RST`) then `A 0`.

Test firmware: `test-fw/counter.S` (SRAM counter) and `test-fw/i2cscan.c` (I2C pin/address scan),
built with the TC32 toolchain from the pvvx SDK.

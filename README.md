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

## Latest findings (2026-11-17)
- pvvx `BTH_allsensors_v59.bin` was verified byte-correct on chip (per-sector CRC), but the CPU parks at PC 0x0d0 after a SWS-stall resume, and is silent after cold boot.
- Stock firmware was re-flashed (verified) — and it **also** does not advertise, on ESP power or on coin cell. So the problem is not the pvvx image; suspect the MAC/RF-cal sector 0x76000 (whole-sector CRC differs from backup; first 8 bytes match) or board/battery.

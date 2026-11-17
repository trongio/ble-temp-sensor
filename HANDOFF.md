# Handoff — Yanmi TLSR8253 T/H sensor → open BLE firmware

**Goal:** make a Xiaomi/Mijia-ecosystem **Yanmi ESM787** temperature/humidity sensor
(`ym001.sensor_ht.ymwsdj`, product id 0x78DB) report its readings to a Linux PC with
**no Xiaomi cloud / no pairing**, then publish a public GitHub repo. A second, identical
sensor (still sealed) exists; whatever works here will be repeated on it.

## TL;DR current status
- Direct BLE pairing is **impossible** (Mijia std-auth v2 needs a Xiaomi-cloud-signed cert; Mi Home China-region login is blocked for this user — their account works only in the Georgia/EU region, which can't even find the device).
- We therefore went the **custom-firmware** route. Built an ESP32 Telink SWS flasher, and have **full, verified read/write/erase access** to the sensor's TLSR8253.
- Flashed pvvx ATC firmware (`BTH_allsensors_v59.bin`) at 0x0. **Flash content verified byte-correct** at many offsets; **MAC/calibration at 0x76000 preserved**.
- **BLOCKER:** after flashing, the sensor **does not advertise anything** — not on battery, not powered by the ESP. Not even battery-only BTHome packets. So the new firmware boots-and-hangs or doesn't run. This is the open problem.

## Hardware rig (currently connected)
- **Flasher:** ESP32-WROOM-32 DevKit on **`/dev/ttyUSB0`** (CH340; port perms reset to root on every USB replug — run `sudo chmod a+rw /dev/ttyUSB0`, user not in dialout).
  Runs ported `tlsr-c3-flasher` firmware. Pins: **D18→1kΩ→SWS, D19→SWS (same node), D25+D26→VDD, GND→GND, D23 unused.** Sensor is powered ONLY by the ESP GPIOs (coin cell out) when the rig is attached.
- **Target:** Yanmi board silk `VCH6043-V03`, TLSR8253 (chip id **0x5562**), 512KB flash, ~24MHz. Sensor's SWS pad is **shared with I²C SCL** (silk "SCL/SWS"). I²C sensor model/pins unconfirmed; pvvx MJWSD05MMC family uses SDA=PC0/SCL=PC1.
- **Second sensor (sealed):** MAC `A4:C1:38:1A:0A:A2`, still broadcasting stock FE95. Our target MAC is **`A4:C1:38:CB:81:A7`**.

## Key facts / addresses
- Flash: firmware at 0x0 (stock was ~117KB; everything 0x20000+ is 0xFF except the MAC sector).
- **MAC + RF cal at 0x076000**: `a7 81 cb 38 c1 a4 9d 59 ...` (MAC little-endian + the `9d59` looks like freq-offset cal). **MUST preserve.** 0x77000 is 0xFF (no separate freq-cap trim; stock worked fine without it).
- pvvx config sector 0x7C000–0x7FFFF (blank now; firmware self-inits).

## Tooling (all under the scratchpad)
Scratchpad root: `/tmp/claude-1000/-home-azael-Documents-Github/65a81801-2d4a-4e67-8c57-4d3ed355c446/scratchpad/`
- ESP flasher host tool: `esp/tlsr-c3-flasher/tlsr_c3.py`, run with venv `esp/.pio-venv/bin/python`.
  Firmware source + built bin: `esp/tlsr-c3-flasher/.pio/build/esp32/firmware.bin` (flash to the ESP via `esp/.pio-venv/bin/pio run -e esp32 -t upload --upload-port /dev/ttyUSB0`).
- **Reliable comms settings:** `-m uart -b 400000 --burst 128 -t 500`. UART mode works; **RMT mode flash-reads mis-time on this classic-ESP32 port** (symbol-count errors) — prefer UART. For verification reads use small ranges / burst 1 (big burst-128 reads over tens of KB corrupt — that caused a false "write failed" alarm).
- Raw firmware protocol (send `cmd\n`, read line) is more reliable than the host CLI for one-offs. Commands: `V`, `MODE uart|rmt`, `BAUD n`, `RATE n`, `BURST n`, `A <ms>` (reset+stall+match-speed; prints `OK mode=uart div=...` on success), `G <addr> <len>` (read reg/RAM, hex), `S <addr> <hex>` (write reg), `FJ` (flash id → `OK 5e3213`), `FR <addr> <len>` (flash read), `FE <addr>` (erase 4K sector), `FW <addr> <hex>` (write ≤1 page), `RST` (power-cycle target), `RUN` (restart target CPU via `sws_write1(0x006f,0x22)`). NOTE: the ESP's `setup()` runs `activate(AUTO_ACTIVATE_MS=3000)` on every boot, and **opening the serial port auto-resets the ESP (CH340 DTR/RTS)** — so every connection re-halts the target. To let the target RUN you must boot it last (`RST` or `RUN`) and not reopen the port.

## Firmware candidates (`scratchpad/fw/`, flash at 0x0, best first)
1. `BTH_allsensors_v59.bin` (86836B) — **flashed, verified on-chip, but target won't advertise.** MJWSD05MMC build, I²C PC0/PC1, all sensor drivers, e-ink. Default advert = **BTHome v2 (UUID 0xFCD2)** ~every 10s.
2. `BTH_v59.bin` (official, SHT4x only, PC0/PC1).
3. `CGDK2_v59.bin` (SHTC3+SHT4x+SHT30, PC0/PC1, different display).
4. `TH03Z_v59.bin` (79124B) — **all-sensor on the OTHER pin pair PC2/PC3** — try this if the sensor is simply on different pins.
5. `TS0201_v59.bin`, 6. `MJ6_v59.bin` (PC2/PC3).
- Backups: `scratchpad/backup/stock_fw_0x0_0x20000.bin` (128KB) + `stock_mac_0x76000.bin` (restore to recover the original device).

## What's verified working
- SWS activation, register read (`G 0x7e 2` → `OK 6255` = TLSR8253), RAM read, **flash erase/write/read** (test pattern round-tripped on a blank sector; firmware bytes match file at 7 offsets incl. 0x15000). MAC sector intact post-flash.

## The blocker + hypotheses (for the next session)
Flash is correct but the device is silent. Likely causes, roughly ranked:
1. **Firmware boots but hangs before advertising** — e.g. the MJWSD05MMC **e-ink display init** blocks on this board's (possibly different) panel, or an **I²C read hangs** because the sensor isn't on PC0/PC1 (SCL=PC1 is the SWS pad; with the ESP wires attached the 1kΩ+GPIO load that line — but it was ALSO silent on battery with wires removed).
2. **Wrong I²C pin pair / display** → try `TH03Z_v59.bin` (PC2/PC3) and/or `CGDK2_v59.bin`.
3. **Not actually running the new image** — verify by booting (`RST`/`RUN`) without re-halting and reading the **program counter** / a known pvvx RAM counter to confirm the CPU executes in 0x0–0x16000; check the Telink multi-boot flag isn't pointing at 0x40000.
4. **RF** — unlikely (stock RF worked with same cal), but could confirm by checking whether ANY adv (even a raw beacon) leaves the chip.

## Recommended next steps
1. **Confirm run-state over SWS:** power-cycle to run (don't re-activate), read PC a few times — is it executing in firmware range and changing? If halted/looping at 0, it's a boot issue (check boot flag / try a different build).
2. **Try the alternate builds** on-chip in order: `TH03Z_v59.bin` (PC2/PC3, all-sensor) → `CGDK2_v59.bin`. After each: `FW`/`wf` at 0x0 (erase only 0x0–0x16000, NEVER 0x76000), `RST`, then scan.
3. **Scan with** `ble-temp-sensor/atc_scan.py` (decodes pvvx-custom/ATC1441/BTHome) or a broad bleak scan for UUID 0xFCD2 / names `ATC_*`. Target MAC `A4:C1:38:CB:81:A7`.
4. If a build advertises battery-only (T/H = 0), it's a **sensor pin/type** problem → switch pin-pair build. If nothing ever advertises on any build, it's **boot/display** → consider building a minimal pvvx config with the display disabled.
5. Once broadcasting: put the coin cell back, confirm standalone, then repeat the whole flash on the sealed second sensor. Finally, build the public GitHub repo (reader tool `mi_sensor.py`, `atc_scan.py`, this writeup).

## Project files (durable, in the repo dir `/home/azael/Documents/Github/ble-temp-sensor/`)
- `mi_sensor.py` — Mijia BLE scan / (attempted) register / read tool, documents the std-auth v2 findings.
- `atc_scan.py` — decodes open-firmware adverts (pvvx-custom / ATC1441 / BTHome).
- `.venv/` — python env with bleak. `keys.json` is git-ignored.

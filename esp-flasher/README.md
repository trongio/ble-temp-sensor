# ESP32-C3 as a Telink TLSR825x flasher

Reads, erases and writes the flash of a Telink TLSR825x chip (TLSR8251 / 8253 / 8258, Tuya "Z2") over its
single-wire debug pin (SWS), with an ESP32-C3 board instead of a USB-UART adapter.

**Status (2026-11-15):** used on three kinds of TLSR8258 boards:

| Board | Flash | Reset pad | Done with it |
|---|---|---|---|
| ZY-ZTH03Pro thermometer (Tuya) | 512 k GigaDevice | yes | backup, write, verify |
| Zbeacon TS0001 relay module | 512 k ZBIT | no (power pins) | backup, write, verify, sector erase |
| TS004F rotary knob (ZG-101ZD) | 1 M GigaDevice | no (power pins) | backup, write, pin and LED search |

At the default 1 Mbit/s (RMT mode) a 512 k read takes 9.3 s, a full backup with `--twice` 19.8 s, a 182 k
firmware write with verify 15.3 s. Read works up to 1.6 Mbit/s (`--rate 1500000`); the default leaves more
margin. UART mode works at 921600 baud; above that the first bit of each byte is read wrong (the activation
check refuses such a speed). Read first, write only after a backup.

The SWS line can be driven in two ways, selectable at run time on the same wiring:

| Mode | How | Speed setting | State |
|---|---|---|---|
| `rmt` (default) | The RMT peripheral generates and measures the pulses (12.5 ns steps) | `--rate` SWire bit rate, default 1 Mbit/s | tested up to 1.6 Mbit/s |
| `uart` | One UART byte per SWire bit, a port of pvvx's `TLSR825xComFlasher.py` | `-b` UART baud, SWire bit rate = baud / 10 | tested at 921600 baud (92 kbit/s); the fallback |

## Wiring

| ESP32-C3 | Target | Note |
|---|---|---|
| GPIO 5 (`PIN_SWS_RX`) | SWS | direct |
| GPIO 4 (`PIN_SWS_TX`) | SWS | through a 1 k … 1.8 k resistor |
| GPIO 6 (`PIN_RST`) | RST | open drain, active low; leave open if the board has no reset pad |
| 3V3 **or** GPIO 7 (+ 10, 3, 1) | 3.3 V / VBAT+ | see below; remove the batteries first |
| GND | GND | |

Pins and the power-up defaults are set in `src/config.h`. Never put 5 V on the target. Keep the SWS wire
short (10 cm or less) for the faster settings.

**Boards with a reset pad:** power from the 3V3 pin, reset from GPIO 6.

**Boards without a reset pad** (and boards whose firmware switches SWS off right after start, for example
Tuya relay modules): connect the target's 3.3 V pad to GPIO 7 instead of the 3V3 pin. Every activation
then switches the target off for 300 ms and catches it while it starts. One pin gives about 40 mA at its
limit; GPIO 7, 10, 3 and 1 (`PWR_PINS`) switch with one register write, so join two or more of them on the
target's 3.3 V pad to share the current. Do not connect these pins to the 3V3 pin. Enough for a bare
Telink board, not for relays or other loads.

The firmware also tries an activation by itself for 3 seconds when the flasher is plugged in
(`AUTO_ACTIVATE_MS`), for a target that gets its power from the 3V3 pin together with the flasher. Whether
this is early enough depends on the target's firmware; the power pins are the reliable way.

**Mains powered modules:** their supply is usually not isolated (logic ground = neutral). Disconnect both
mains wires before connecting the flasher, and power the board from the flasher only.

## Build and upload

    pio run -e c3-usb -t upload      # USB connector wired straight to the C3 (Super Mini, XIAO)
    pio run -e c3-uart -t upload     # board with a CH340 / CP2102 USB-UART chip

Needs the Arduino core 3.x (ESP-IDF 5) for the RMT driver.

## Use

    pip install pyserial
    python3 tlsr_c3.py -p /dev/ttyACM0 selftest
    python3 tlsr_c3.py -p /dev/ttyACM0 info
    python3 tlsr_c3.py -p /dev/ttyACM0 rf 0 0x80000 stock.bin --twice
    python3 tlsr_c3.py -p /dev/ttyACM0 wf 0 new_firmware.bin
    python3 tlsr_c3.py -p /dev/ttyACM0 es 0x2D000 0x49000
    python3 tlsr_c3.py -p /dev/ttyACM0 ea
    python3 tlsr_c3.py -p /dev/ttyACM0 --run info

    python3 tlsr_c3.py -p /dev/ttyACM0 --mode uart info

On Windows use `py tlsr_c3.py -p COM12 ...`.

Options:

- `-m rmt|uart` how the line is driven (default `rmt`).
- `--rate bps` RMT mode speed, 30000 … 2000000, default 1000000. The firmware picks the nearest divider
  the chip can do and prints the real bit rate (941 kbit/s for the default, 1.6 Mbit/s for 1500000).
- `-b baud` UART mode speed, 340000 … 5000000, default 921600 (92 kbit/s on the wire). Do not go higher.
- `-t ms` activation time after the reset pulse (default 100; try 300–1000 if the chip does not answer).
- `--burst n` bytes requested in one go; `--burst 1` is the slow, safest read (default 64, up to 256).
- `--run` restart the target's CPU at the end. Without it the chip stays stopped after every command.

`selftest` sends one END byte and checks what the RX pin sees; it works without a target and tells whether
the TX – resistor – RX path is right. `info` prints the chip id (0x5562 for TLSR825x), the program counter
and the flash JEDEC id; the flash size tells how much to read (0x80000 for 512 k, 0x100000 for 1 M).

## Finding the pins of an unknown board

With the chip stopped, its GPIO registers can be read and written over SWS. Two commands use this to map
a board without reading its firmware:

    python3 tlsr_c3.py -p /dev/ttyACM0 pins --seconds 30            # 10 k pull-ups on every pin
    python3 tlsr_c3.py -p /dev/ttyACM0 pins --seconds 3 --pull down
    python3 tlsr_c3.py -p /dev/ttyACM0 led
    python3 tlsr_c3.py -p /dev/ttyACM0 led --only C4

- `pins` makes every pin (except PA7 = SWS) an input and prints each change with its time, about 250
  polls per second: press the button, turn the encoder, close the switch input and read off the pins and
  their order. A pin that reads 1 with pull-ups and 0 with pull-downs is not connected to anything (free
  for a battery measurement, for example); one that stays 1 with pull-downs is tied to the supply, often
  through an LED.
- `led` drives the pins one by one low and then high for a second and prints which one it is at: note the
  line on the screen when the LED lights. `--skip` lists pins that must stay inputs (default `A1,D4,D7`),
  `--only` tests just the given pins three times.

The chip is stopped right after reset, with the clocks of its blocks off; `pins` and `led` switch them on
first (registers `0x60`–`0x65`), otherwise the pull resistors and the input enable of ports B and C, which
live in the analog registers, are not accepted.

## First use

1. `selftest` with only the resistor fitted, no target: checks the TX – resistor – RX path.
2. `info` — proves wiring, activation and the speed. Every activation also writes a test pattern into the
   chip's RAM and reads it back at the speed and burst in use; if that fails, nothing else is done.
   If the chip does not answer: check the resistor and GND, raise `-t`, lower `--rate 500000`, or try
   `--mode uart`.
3. `rf 0 <flash size> stock.bin --twice` — full backup; the second pass compares checksums.
4. Keep the backup safe, then `wf`. It erases the touched sectors, writes and verifies.

## The protocol, and how the two modes map onto it

From Telink's SWire description (in pvvx's TLSRPGM repository) and the working tools:

- A bit is 5 time units: 0 = 1 low + 4 high, 1 = 4 low + 1 high. The line idles high.
- A byte is a command bit, 8 data bits MSB first, and one unit of low.
- A message is START (`0x5a`, command bit set), the address (3 bytes on TLSR825x, 2 on TLSR826x), RW_ID
  (bit 7 = read), the data, and END (`0xff`, command bit set).
- Read: the master sends one unit of low per byte. When the line has then been high for longer than that
  pulse, the slave sends 8 bits and one unit of low, timed by its own clock.
- Slave speed: bit rate = system clock / 5 / `reg 0xb2`. With the divider 5 the chip does about 960 kbit/s.
- `reg 0xb3` bit 7 is the FIFO mode: the address is not incremented, used to stream bytes through the SPI
  data register (`0x0c`; control `0x0d`) to the flash.
- Activation: reset pulse, then "stall CPU" (`0x0602 = 0x05`) repeated so that it lands before the firmware
  can disable SWS or go to sleep.

| | UART mode | RMT mode |
|---|---|---|
| Bit shape | `0x80` = low for 8 of 10 UART bit times, `0xfe` = low for 2 of 10 | exact 1 : 4 and 4 : 1 pulses |
| Speed match | the chip's divider is scanned until the read-back fits the UART frame | the current divider is read at a slow speed, the chip's bit period is measured, the clock is computed and the divider nearest to the requested rate is set |
| Read decode | the UART samples each slave bit at a fixed point, so the slave must run at baud / 10 | each bit is 1 when its low part is longer than its high part, any slave speed |
| Bulk read | start pulses sent one by one with a timed gap, up to 256 bytes per burst | up to 256 bytes per burst, 10 pulses per byte; the driver empties the channel memory in halves while receiving, a lost symbol fails the burst |
| Long writes | one UART stream | pieces of 9 bytes queued back to back, cut on byte boundaries |
| Echo check | yes, every write is read back | only in `selftest` |

## Flash access, checked against the chip's own flash code

Compared with `flash.c` / `spi_i.h` of pvvx's loader (Telink's reference routines) and `TlsrPgm.py`:

| Step | Reference | Here |
|---|---|---|
| Commands | 0x06 write enable, 0x02 page program, 0x03 read, 0x05 status, 0x20 sector erase (4 k), 0x60 chip erase, 0x01 write status | same |
| Page program | at most 256 bytes, inside one page | same; the host cuts on page boundaries |
| Read | command, address, a dummy byte, control `0x0a` (auto read), then the data register | same |
| Status | command, then a **dummy byte** to clock the answer in, then the data register | same. pvvx's SWire script reads without the dummy byte, so its "ready" check may be a constant |
| Unlock | write enable, write status 0, wait, status must read 0 | same, plus a check that the write-enable latch follows 0x06 / 0x04; without it nothing is erased or written |
| After a page program | poll the busy bit | 2 ms fixed wait, then poll |

Cautions that come from the layout of Telink / Tuya firmware (from memory of the Telink SDK, not confirmed
by the sources read: check them in your own dump):

- The top sectors hold per-device data: the MAC address and the factory RF calibration (512 k flash:
  0x76000 / 0x77000, 1 M flash: 0xFF000 / 0xFE000). `ea` wipes them. `wf` only erases the sectors the
  file covers, so a firmware written at address 0 leaves them alone.
- To find them, search the backup for the device's IEEE address in reversed byte order.
- pvvx's advice for these thermometers: write the BLE firmware by wire first (smaller, address 0), then
  switch to Zigbee from his web flasher over BLE.

## Host protocol

One text line per command, answer `OK [payload]` or `ERR reason`; numbers decimal or `0x` hex, data hex.

`V`, `MODE uart|rmt`, `BAUD n`, `RATE n`, `BURST n`, `SELFTEST`, `RST` (reset pulse and power cycle),
`A ms` (activate), `G addr len` (read registers / RAM), `S addr hex` (write registers / RAM),
`FJ`, `FS`, `FR addr len` (hex), `FB addr len` (base64, `*` = all 0xff), `FC addr len` (CRC-32 of the range),
`FU`, `FE addr`, `FA`, `FW addr hex`, `RUN`.

The USB link is the slow part of a read (about 45 kbytes/s), so the host reads with `FB`, and the second
pass of `rf --twice` and the verify after `wf` only compare CRCs (`FC`).

## Not done

- pvvx's RAM loader (`TlsrComProg825x`) is not used: it talks over the chip's UART pins (PA0 / PB1), not
  over SWS, so it needs two more wires.
- Chips other than TLSR825x (the TLSR826x family uses 2-byte addresses).

## Files

- `src/main.cpp`, `src/config.h`, `platformio.ini`: the ESP32-C3 firmware.
- `tlsr_c3.py`: the command line tool on the computer (Python 3, `pyserial`).

## Credits

SWire emulation over a UART, the register sequences and the activation: pvvx
(<https://github.com/pvvx/TlsrComSwireWriter>, public domain; <https://github.com/pvvx/TLSRPGM>).

## License

MIT, see `LICENSE`.

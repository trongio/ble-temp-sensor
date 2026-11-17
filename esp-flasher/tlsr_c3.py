#!/usr/bin/env python3
"""Host side of the ESP32-C3 Telink TLSR825x flasher.

Examples:
    python3 tlsr_c3.py -p /dev/ttyACM0 info
    python3 tlsr_c3.py -p /dev/ttyACM0 rf 0 0x100000 stock.bin --twice
    python3 tlsr_c3.py -p /dev/ttyACM0 wf 0 firmware.bin
    python3 tlsr_c3.py -p /dev/ttyACM0 --rate 1500000 rf 0 0x80000 stock.bin --twice
    python3 tlsr_c3.py -p /dev/ttyACM0 --mode uart info
"""
import argparse
import base64
import sys
import time
import zlib

import serial

SECTOR = 4096
PAGE = 256
READ_CHUNK = 1024
CRC_CHUNK = 4096


class FlasherError(RuntimeError):
    pass


class Flasher:
    def __init__(self, port, baud=460800):
        self.rxbuf = b''
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baud
        # fixed and short: changing it per command reconfigures the port, which costs about 25 ms on Windows
        self.ser.timeout = 0.1
        # keep the control lines quiet, they reset some C3 boards
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        time.sleep(1.5)
        self.ser.reset_input_buffer()
        last = None
        for _ in range(5):
            try:
                self.version = self.cmd('V', timeout=1)
                return
            except FlasherError as e:
                last = e
                self.ser.reset_input_buffer()
                self.rxbuf = b''
        raise FlasherError('the flasher does not answer on %s (%s)' % (port, last))

    def readline(self, timeout=5):
        """Like serial.readline(), but takes everything that has arrived in one call: reading a long
        answer one byte at a time is slow on Windows."""
        deadline = time.time() + timeout
        while b'\n' not in self.rxbuf:
            chunk = self.ser.read(max(1, self.ser.in_waiting))
            if chunk:
                self.rxbuf += chunk
            elif time.time() >= deadline:
                break
        line, sep, rest = self.rxbuf.partition(b'\n')
        self.rxbuf = rest if sep else b''
        return line

    def cmd(self, text, timeout=5):
        self.ser.write(text.encode() + b'\n')
        answer = self.readline(timeout).decode(errors='replace').strip()
        if answer == 'OK':
            return ''
        if answer.startswith('OK '):
            return answer[3:]
        if answer.startswith('ERR'):
            raise FlasherError('%s -> %s' % (text.split()[0], answer))
        raise FlasherError('%s -> no or bad answer: %r' % (text.split()[0], answer))

    def activate(self, tact_ms):
        return self.cmd('A %d' % tact_ms, timeout=tact_ms / 1000 + 10)

    def read_flash(self, addr, size, progress=True):
        out = bytearray()
        while len(out) < size:
            n = min(READ_CHUNK, size - len(out))
            if progress:
                print('\rRead 0x%06x' % (addr + len(out)), end='', flush=True)
            for attempt in range(3):
                try:
                    answer = self.cmd('FB %d %d' % (addr + len(out), n))
                    data = b'\xff' * n if answer == '*' else base64.b64decode(answer, validate=True)
                    if len(data) != n:
                        raise FlasherError('short answer')
                    break
                except (FlasherError, ValueError):
                    if attempt == 2:
                        if progress:
                            print()
                        raise
            out += data
        if progress:
            print('\r' + ' ' * 20 + '\r', end='')
        return bytes(out)

    def compare_flash(self, addr, data, label='Compare'):
        """Check the flash against data by CRC, block by block; returns the address of the first bad block."""
        pos = 0
        while pos < len(data):
            n = min(CRC_CHUNK, len(data) - pos)
            print('\r%s 0x%06x' % (label, addr + pos), end='', flush=True)
            crc = int(self.cmd('FC %d %d' % (addr + pos, n), timeout=20), 16)
            if crc != zlib.crc32(data[pos:pos + n]):
                print()
                return addr + pos
            pos += n
        print('\r' + ' ' * 24 + '\r', end='')
        return None

    def write_flash(self, addr, data, erase=True):
        self.cmd('FU')
        erased = None
        if erase and addr % SECTOR:
            erased = addr - addr % SECTOR   # as in pvvx's tool: a partly covered first sector is kept
        pos = 0
        while pos < len(data):
            a = addr + pos
            n = min(PAGE - a % PAGE, len(data) - pos)
            page = data[pos:pos + n]
            sector = a - a % SECTOR
            if erase and sector != erased:
                print('\rErase 0x%06x' % sector, end='', flush=True)
                self.cmd('FE %d' % sector)
                erased = sector
            if page.count(0xff) != len(page):
                print('\rWrite 0x%06x' % a, end='', flush=True)
                self.cmd('FW %d %s' % (a, page.hex()))
            pos += n
        print('\r' + ' ' * 20 + '\r', end='')


def auto_int(x):
    return int(x, 0)


def watch_pins(f, seconds, pull):
    """TLSR825x: every pin (except PA7 = SWS) becomes a GPIO input, then the input registers are polled."""
    def ana_write(addr, value):
        f.cmd('S 0xb8 %02x%02x60' % (addr, value))   # analog register: address, data, start + write
        time.sleep(0.002)
        f.cmd('S 0xba 00')

    def ana_read(addr):
        f.cmd('S 0xb8 %02x0040' % addr)              # start, read
        time.sleep(0.002)
        value = bytes.fromhex(f.cmd('G 0xb9 1'))[0]
        f.cmd('S 0xba 00')
        return value

    # The chip was stopped right after reset: release the resets and switch the clocks of its
    # blocks on, as the SDK's start-up code does. Without it the analog registers (pull resistors,
    # input enable of ports B and C) cannot be written.
    f.cmd('S 0x60 000000ffffff')
    time.sleep(0.01)
    f.cmd('S 0x586 7f')                               # port A: GPIO function, PA7 stays SWS
    for reg in (0x58e, 0x596, 0x59e):                 # ports B, C, D: GPIO function
        f.cmd('S 0x%x ff' % reg)
    for reg in (0x582, 0x58a, 0x592, 0x59a):          # outputs off
        f.cmd('S 0x%x ff' % reg)
    pa_ie = bytes.fromhex(f.cmd('G 0x581 1'))[0]
    f.cmd('S 0x581 %02x' % (pa_ie | 0x7f))            # input enable, ports A and D
    f.cmd('S 0x599 ff')
    ana_write(0xbd, 0xff)                             # input enable, ports B and C
    ana_write(0xc0, 0xff)
    code = {'up': 0xff, 'down': 0xaa, 'none': 0x00}[pull]
    for reg in range(0x0e, 0x16):                     # two bits per pin: 3 = 10 k up, 2 = 100 k down
        if reg == 0x0f:
            ana_write(reg, (ana_read(reg) & 0xc0) | (code & 0x3f))   # PA7 untouched
        else:
            ana_write(reg, code)

    check = ana_read(0x0e)
    if check != code:
        print('Warning: the pull resistors were not accepted (register 0x0e reads %02x, wanted %02x).' % (check, code))

    def read_ports():
        return [bytes.fromhex(f.cmd('G 0x%x 1' % reg))[0] for reg in (0x580, 0x588, 0x590, 0x598)]

    def names(ports):
        return ' '.join('%s=%s' % (n, format(v, '08b')) for n, v in zip('ABCD', ports))

    last = read_ports()
    print('Pull: %s. Bits are pins 7..0 of each port (PA7 is the SWS line itself).' % pull)
    print('Start:  %s' % names(last))
    print('Watching for %.0f s: turn, press, switch...' % seconds)
    t0 = time.time()
    polls = 0
    while time.time() - t0 < seconds:
        now = read_ports()
        polls += 1
        if now != last:
            changed = []
            for port, a, b in zip('ABCD', last, now):
                for bit in range(8):
                    if (a ^ b) >> bit & 1 and not (port == 'A' and bit == 7):
                        changed.append('P%s%d %d->%d' % (port, bit, a >> bit & 1, b >> bit & 1))
            if changed:
                print('%6.2f s  %s' % (time.time() - t0, ', '.join(changed)))
            last = now
    print('End:    %s   (%d polls, %.0f per second)' % (names(last), polls, polls / seconds))


def find_led(f, skip, hold, only=''):
    """TLSR825x: every pin in turn becomes an output, low and then high, the others stay inputs."""
    f.cmd('S 0x60 000000ffffff')                      # clocks on, see watch_pins
    time.sleep(0.01)
    f.cmd('S 0x586 7f')                               # GPIO function everywhere, PA7 stays SWS
    for reg in (0x58e, 0x596, 0x59e):
        f.cmd('S 0x%x ff' % reg)
    for reg in (0x582, 0x58a, 0x592, 0x59a):          # all outputs off
        f.cmd('S 0x%x ff' % reg)
    skipped = {x.strip().upper() for x in skip.split(',') if x.strip()}
    skipped.add('A7')
    order = [(port, bit) for port in 'BCDA' for bit in range(8) if '%s%d' % (port, bit) not in skipped]
    wanted = [x.strip().upper() for x in only.split(',') if x.strip()]
    if wanted:
        order = [(x[0], int(x[1])) for x in wanted if x not in skipped] * 3
    print('Watch the LED. %d pins, %.0f s low and %.0f s high each (about %.0f s in all).' %
          (len(order), hold, hold, len(order) * 2 * hold))
    print('Note the line that is on the screen when the LED lights up.')
    for port, bit in order:
        base = 0x580 + 8 * 'ABCD'.index(port)
        out_reg, oen_reg = base + 3, base + 2
        for level in (0, 1):
            f.cmd('S 0x%x %02x' % (out_reg, (1 << bit) if level else 0))
            f.cmd('S 0x%x %02x' % (oen_reg, 0xff & ~(1 << bit)))   # 0 = output enabled
            print('  P%s%d %s' % (port, bit, 'HIGH' if level else 'low'), flush=True)
            time.sleep(hold)
        f.cmd('S 0x%x ff' % oen_reg)                  # back to input
        f.cmd('S 0x%x 00' % out_reg)
    print('Done, all pins are inputs again.')


def main():
    ap = argparse.ArgumentParser(description='ESP32-C3 Telink TLSR825x SWire flasher')
    ap.add_argument('-p', '--port', default='/dev/ttyACM0')
    ap.add_argument('--host-baud', type=auto_int, default=460800, help='only for boards with a USB-UART chip')
    ap.add_argument('-t', '--tact', type=auto_int, default=100,
                    help='activation time in ms after the reset pulse (0 = no reset, default 100)')
    ap.add_argument('-m', '--mode', choices=['uart', 'rmt'], default='rmt',
                    help='how the SWS line is driven: rmt = pulse timing (default), uart = UART emulation')
    ap.add_argument('-b', '--baud', type=auto_int, default=0,
                    help='uart mode: UART baud, the SWire bit rate is a tenth of it (default 921600)')
    ap.add_argument('--rate', type=auto_int, default=0,
                    help='rmt mode: SWire bit rate in bit/s (default 1000000)')
    ap.add_argument('--burst', type=auto_int, default=0,
                    help='bytes read per burst, 1 = slow and safe (default 64)')
    ap.add_argument('-r', '--run', action='store_true', help='restart the target CPU at the end')
    sub = ap.add_subparsers(dest='op', required=True)
    sub.add_parser('info', help='chip id, program counter, flash id')
    sub.add_parser('selftest', help='line test without talking to the target (TX - resistor - RX)')
    p = sub.add_parser('rf', help='read flash to a file')
    p.add_argument('address', type=auto_int)
    p.add_argument('size', type=auto_int)
    p.add_argument('filename')
    p.add_argument('--twice', action='store_true', help='read twice and compare')
    p = sub.add_parser('wf', help='write a file to flash, erasing the sectors, then verify')
    p.add_argument('address', type=auto_int)
    p.add_argument('filename')
    p.add_argument('--no-erase', action='store_true')
    p.add_argument('--no-verify', action='store_true')
    p = sub.add_parser('es', help='erase flash sectors')
    p.add_argument('address', type=auto_int)
    p.add_argument('size', type=auto_int)
    sub.add_parser('ea', help='erase the whole flash')
    p = sub.add_parser('led', help='drive every free pin low and then high for a moment, one after the other, '
                                   'to find the pin of an LED on an unknown board')
    p.add_argument('--skip', default='A1,D4,D7',
                   help='pins that must stay inputs, e.g. buttons and encoder lines (default: A1,D4,D7)')
    p.add_argument('--hold', type=float, default=1.0, help='seconds per level (default 1)')
    p.add_argument('--only', default='', help='test just these pins, e.g. C4 (repeats 3 times)')
    p = sub.add_parser('pins', help='watch the GPIO inputs of the stopped chip and print every change '
                                    '(to find buttons, encoders and switch inputs on an unknown board)')
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--pull', choices=['up', 'down', 'none'], default='up',
                   help='pull resistor on every pin while watching (default: 10 k pull-up)')
    args = ap.parse_args()

    t0 = time.time()
    try:
        f = Flasher(args.port, args.host_baud)
        print('Flasher:', f.version)
        try:
            fw = tuple(int(x) for x in f.version.split()[1].split('.'))
        except (IndexError, ValueError):
            fw = (0, 0)
        if fw < (0, 11):
            raise FlasherError('this script needs flasher firmware 0.11 or newer on the C3')
        # always set the speeds: the flasher keeps the last values until it is powered off
        f.cmd('BAUD %d' % (args.baud or 921600))
        f.cmd('RATE %d' % (args.rate or 1000000))
        f.cmd('MODE ' + args.mode)
        # always set it: the flasher keeps the last value until it is powered off
        f.cmd('BURST %d' % (args.burst or 64))
        if args.op == 'selftest':
            print('Line:   ', f.cmd('SELFTEST'))
            print('Done in %.1f s' % (time.time() - t0))
            return
        print('Target: ', f.activate(args.tact))

        if args.op == 'info':
            # 0x7e: chip id (0x5562 = TLSR825x), 0x6bc: program counter
            cid = bytes.fromhex(f.cmd('G 0x7e 2'))
            pc = bytes.fromhex(f.cmd('G 0x6bc 4'))
            print('Chip id: 0x%04x' % int.from_bytes(cid, 'little'))
            print('PC:      0x%06x' % int.from_bytes(pc, 'little'))
            jedec = bytes.fromhex(f.cmd('FJ'))
            size = (1 << jedec[2]) >> 10 if 10 <= jedec[2] <= 24 else 0
            print('Flash:   JEDEC %s, %d kbytes, status 0x%s' % (jedec.hex(), size, f.cmd('FS')))
        elif args.op == 'rf':
            f.cmd('STAT')
            t1 = time.time()
            data = f.read_flash(args.address, args.size)
            print('Read in %.1f s (flasher: %s)' % (time.time() - t1, f.cmd('STAT')))
            t1 = time.time()
            if args.twice:
                print('Second pass...')
                # the flasher reads everything again and only sends checksums: no data over the slow USB link
                bad = f.compare_flash(args.address, data, 'Check')
                if bad is not None:
                    with open(args.filename + '.pass1', 'wb') as fh:
                        fh.write(data)
                    raise FlasherError('the second read differs in the block at 0x%06x; the first read was kept '
                                       'as %s.pass1, do not trust it' % (bad, args.filename))
                print('Both reads are identical. Check took %.1f s (flasher: %s)' % (time.time() - t1, f.cmd('STAT')))
            with open(args.filename, 'wb') as fh:
                fh.write(data)
            print('Saved %d bytes to %s' % (len(data), args.filename))
        elif args.op == 'wf':
            with open(args.filename, 'rb') as fh:
                data = fh.read()
            if not data:
                raise FlasherError('empty file')
            print('Write 0x%06x..0x%06x' % (args.address, args.address + len(data)))
            f.write_flash(args.address, data, erase=not args.no_erase)
            if not args.no_verify:
                print('Verify...')
                bad = f.compare_flash(args.address, data, 'Verify')
                if bad is not None:
                    raise FlasherError('verify failed in the block at 0x%06x' % bad)
                print('Verified.')
        elif args.op == 'es':
            f.cmd('FU')
            first = args.address - args.address % SECTOR
            last = args.address + max(args.size, 1) - 1
            for a in range(first, last + 1, SECTOR):
                print('\rErase 0x%06x' % a, end='', flush=True)
                f.cmd('FE %d' % a)
            print()
        elif args.op == 'led':
            find_led(f, args.skip, args.hold, args.only)
        elif args.op == 'pins':
            watch_pins(f, args.seconds, args.pull)
        elif args.op == 'ea':
            f.cmd('FU')
            print('Erase all...')
            f.cmd('FA', timeout=60)
        if args.run:
            f.cmd('RUN')
            print('Target restarted.')
    except (FlasherError, serial.SerialException) as e:
        print('\nError:', e)
        sys.exit(1)
    print('Done in %.1f s' % (time.time() - t0))


if __name__ == '__main__':
    main()

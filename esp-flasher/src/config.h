// Wiring of the flasher. Avoid the strapping pins (2, 8, 9), USB (18, 19) and UART0 (20, 21).
#pragma once

// SWS line: PIN_SWS_RX goes straight to the target's SWS pad,
// PIN_SWS_TX goes to the same pad through a 1 k ... 1.8 k resistor.
#define PIN_SWS_TX 18
#define PIN_SWS_RX 19

// Target reset (active low, open drain). Connect to the target's RST pad.
#define PIN_RST 23

// Optional target power (push-pull, strongest drive): connect the target's 3.3 V pad here instead of
// the 3V3 pin when the target has no reset pad, or when its firmware switches SWS off right after start.
// Every activation then switches the target off and on, and catches it while it starts.
// One pin gives about 40 mA at its limit; the pins of the list switch at the same instant, so several
// of them can be joined on the target's 3.3 V pad to share the current. Unused ones stay unconnected.
#define PWR_PINS {25, 26, 27, 16, 17}
#define PWR_OFF_MS 300

// At power-up of the flasher: try to stop a target that got its power together with the flasher
// (3.3 V pad on the 3V3 pin, no reset wire). 0 = off.
#define AUTO_ACTIVATE_MS 3000

// Speed of the link to the computer (only matters on boards with a USB-UART chip).
#define HOST_BAUD 460800

// Mode at power-up: 0 = UART emulation (pvvx's method), 1 = RMT (real pulse timing, faster).
#define SWS_MODE_DEFAULT 1

// UART mode: one SWire bit = 10 UART bits, so the SWire bit rate is baud / 10. Range 340000 ... 5000000.
#define SWS_BAUD_DEFAULT 921600

// RMT mode: SWire bit rate in bit/s. Range 30000 ... 2000000 (the chip's own default is about 960000).
#define SWS_RATE_DEFAULT 1000000

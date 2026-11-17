/* I2C bus scan with SCL bit-banged on PA7 (the SWS pad) and SDA tried on every
 * other GPIO. Results land in SRAM, then PA7 is handed back to SWS for readout.
 *   0x848100 u32 magic (0x5CA11000 running, 0x5CA1D0E0 done)
 *   0x848104 u32 idle-high bitmap of the 32 pins (PA0..PD7) when released
 *   0x848108 u32 PA7 idle level after release (1 = SCL pulled up)
 *   0x848110 + 16*pin : 128-bit bitmap of 7-bit addresses that ACKed */
typedef unsigned char u8; typedef unsigned int u32;
#define R8(a) (*(volatile u8 *)(0x800000 + (a)))
#define R32(a) (*(volatile u32 *)(a))
#define IN(p)   R8(0x580 + 8*(p))
#define IE(p)   R8(0x581 + 8*(p))
#define OEN(p)  R8(0x582 + 8*(p))
#define OUT(p)  R8(0x583 + 8*(p))
#define FUNC(p) R8(0x586 + 8*(p))
#define RES 0x848100

static void dly(void) { for (volatile int i = 0; i < 40; i++); }
static void rel(int p, int b) { OEN(p) |= 1 << b; }         /* input -> pulled high */
static void low(int p, int b) { OUT(p) &= ~(1 << b); OEN(p) &= ~(1 << b); }
static int  rd(int p, int b) { return (IN(p) >> b) & 1; }
#define SCL_H() rel(0, 7)
#define SCL_L() low(0, 7)

#define sp (*(volatile int *)0x848000)   /* SDA port/bit kept in SRAM: no .bss */
#define sb (*(volatile int *)0x848004)
static void start(void) { rel(sp, sb); SCL_H(); dly(); low(sp, sb); dly(); SCL_L(); dly(); }
static void stop(void)  { low(sp, sb); dly(); SCL_H(); dly(); rel(sp, sb); dly(); }
static int wbyte(u8 v) {
  for (int i = 7; i >= 0; i--) {
    if (v >> i & 1) rel(sp, sb); else low(sp, sb);
    dly(); SCL_H(); dly(); SCL_L();
  }
  rel(sp, sb); dly(); SCL_H(); dly();
  int ack = !rd(sp, sb);
  SCL_L(); dly();
  return ack;
}

int main(void) {
  R32(RES) = 0x5CA11000;
  for (int p = 0; p < 4; p++) {               /* PA..PD: all GPIO, inputs, out latch 0 */
    FUNC(p) = 0xff; IE(p) = 0xff; OUT(p) = 0; OEN(p) = 0xff;
  }
  for (volatile int i = 0; i < 200000; i++);  /* let devices power up */
  u32 idle = 0;
  for (int p = 0; p < 4; p++) idle |= (u32)IN(p) << (8 * p);
  R32(RES + 4) = idle;
  for (int pin = 0; pin < 32; pin++) {
    for (int k = 0; k < 4; k++) R32(RES + 0x10 + 16 * pin + 4 * k) = 0;
    if (pin == 7) continue;                   /* PA7 is SCL */
    sp = pin >> 3; sb = pin & 7;
    if (!rd(sp, sb)) continue;                /* SDA must idle high */
    for (int a = 0x03; a < 0x78; a++) {
      start();
      int ack = wbyte(a << 1);
      stop();
      if (ack) R32(RES + 0x10 + 16 * pin + 4 * (a >> 5)) |= 1u << (a & 31);
    }
  }
  SCL_H(); dly();
  R32(RES + 8) = rd(0, 7);
  FUNC(0) &= ~0x80;                           /* PA7 back to SWS */
  R32(RES) = 0x5CA1D0E0;
  for (;;);
}

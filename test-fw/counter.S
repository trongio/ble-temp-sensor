@ Minimal TLSR825x test image: runs entirely from SRAM (boot ROM copies the
@ first 256 bytes), never reads flash. Writes magic 0xC0DEC0DE to 0x848000 and
@ increments a counter at 0x848004 forever. Read both over SWS to see if it runs.
	.code 16
	.section .text
	.org 0x0
	tj	reset
	.word	0
	.org 0x8
	.word	0x544c4e4b          @ "KNLT"
	.word	(0x00880000 + 16)   @ copy 16*16 = 256 bytes to SRAM
	.org 0x10
	tj	reset
	.org 0x18
	.word	256
	.org 0x20
	.align 4
reset:
	tloadr	r1, ADDR
	tloadr	r0, MAGIC
	tstorer	r0, [r1, #0]
	tmov	r0, #0
loop:
	tadd	r0, #1
	tstorer	r0, [r1, #4]
	tj	loop
	.align 4
ADDR:	.word	0x00848000
MAGIC:	.word	0xc0dec0de
	.org 0xfc
	.word	0

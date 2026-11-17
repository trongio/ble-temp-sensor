	.code 16
	.section .vectors,"ax"
	.org 0x0
	tj	reset
	.word	0
	.org 0x8
	.word	0x544c4e4b
	.word	(0x00880000 + 64)
	.org 0x10
	tj	reset
	.org 0x18
	.word	_bin_size_
	.org 0x20
	.align 4
reset:
	tmov	r0, #0x13
	tmcsr	r0
	tloadr	r0, STK
	tmov	r13, r0
	tjl	main
hang:	tj	hang
	.align 4
STK:	.word	0x0084c000

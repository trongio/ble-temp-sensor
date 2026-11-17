SECTIONS {
  . = 0;
  .vectors : { *(.vectors) }
  .text : { *(.text*) *(.rodata*) }
  _bin_size_ = .;
  /DISCARD/ : { *(.data*) *(.bss*) *(COMMON) }
}

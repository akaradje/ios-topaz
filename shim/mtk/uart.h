#pragma once
#include <stdint.h>

/*
 * MediaTek UART0 on merlin (MT6768): a 16550 with 32-bit register spacing
 * (lk: platform/common/uart/uart.c). lk has already configured UART0 for
 * its own console, so we only push characters out and never touch the
 * baud/divisor registers.
 */
#define MT_UART0_BASE	0x11002000UL

#define UART_RBR	0x00
#define UART_THR	0x00
#define UART_IER	0x04
#define UART_IIR_FCR	0x08
#define UART_LCR	0x0c
#define UART_MCR	0x10
#define UART_LSR	0x14
#define UART_MSR	0x18
#define UART_DLL	0x00
#define UART_DLH	0x04

#define UART_LSR_THRE	0x20	/* transmit holding register empty */
#define UART_LSR_DR	0x01	/* data ready */

void uart_putc(char c);
void uart_puts(const char *s);
void uart_hex(uint64_t v);

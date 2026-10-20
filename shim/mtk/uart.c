/*
 * MT6768 UART0 console.
 *
 * lk has already enabled the UART0 clock and programmed the line, so this
 * only waits for THR to be free and writes the byte out. If lk never
 * touched UART0 the LSR reads as 0 and we keep quiet instead of hanging.
 */
#include "uart.h"

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

void uart_putc(char c)
{
	uint32_t lsr = rd32(MT_UART0_BASE + UART_LSR);

	if (!(lsr & UART_LSR_THRE))
		return;			/* no clock, no console: stay silent */
	for (int i = 0; i < 10000; i++) {
		if (rd32(MT_UART0_BASE + UART_LSR) & UART_LSR_THRE)
			break;
	}
	wr32(MT_UART0_BASE + UART_THR, (uint32_t)c);
}

void uart_puts(const char *s)
{
	while (*s) {
		if (*s == '\n')
			uart_putc('\r');
		uart_putc(*s++);
	}
}

void uart_hex(uint64_t v)
{
	static const char hex[] = "0123456789ABCDEF";
	char buf[17];

	for (int i = 0; i < 16; i++)
		buf[i] = hex[(v >> (4 * (15 - i))) & 0xf];
	buf[16] = 0;
	uart_puts(buf);
}

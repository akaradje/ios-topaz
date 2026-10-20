/*
 * merlin (Redmi Note 9, MediaTek MT6768) boot shim - stage 1.
 *
 * MediaTek's lk hands over to a 64-bit kernel like this (lk:
 * app/mt_boot/mt_boot.c, boot_linux() -> lk_jump64()):
 *
 *   x0 = entry address
 *   x1 = the device tree lk built (tags_target_addr)   <- not x0 like ABL
 *   x2 = 0
 *   x3 = 1 (KERNEL_64BITS)
 *
 * The tree lk passes is its own, and it carries lk's boot properties in the
 * root node: "atag,videolfb" (the framebuffer lk configured), "atag,mem"
 * (the memory it gave us) and "bootargs" (the kernel command line).
 *
 * Stage 1 only proves that our own code runs on the phone: banner on the
 * framebuffer lk set up, the geometry it handed over, the CPU we landed on.
 * XNU comes later, on an A75 core (the A53s have no 16K granule).
 */
#include <stdint.h>
#include "console.h"
#include "uart.h"

#define FDT_MAGIC	0xd00dfeed
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4

#define ATAG_MEM	0x54410002
#define ATAG_VIDEOLFB	0x54410008

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline uint32_t le32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline uint16_t le16(uintptr_t a) { return *(volatile uint16_t *)a; }
static inline uint32_t be32(uintptr_t a) { return __builtin_bswap32(rd32(a)); }

static int str_eq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

/* Find a property of the root node; returns its value pointer. */
static uintptr_t fdt_root_prop(uintptr_t fdt, const char *name, uint32_t *out_len)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			depth++;
			while (*(volatile char *)p)	/* skip the node name */
				p++;
			p = (p + 4) & ~3UL;
			break;
		}
		case FDT_END_NODE:
			depth--;
			if (depth <= 0)
				return 0;	/* past the root node */
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (depth == 1 && str_eq((const char *)(strings + nameoff), name)) {
				*out_len = len;
				return val;
			}
			p = (val + len + 3) & ~3UL;
			break;
		}
		case FDT_NOP:
			break;
		default:
			return 0;
		}
	}
}

/* lk stores whole ATAGs in the tree: [u32 size][u32 tag][payload]. */
static uintptr_t atag_body(uintptr_t prop, uint32_t len, uint32_t tag)
{
	if (!prop || len < 12)
		return 0;
	if (le32(prop + 4) == tag)
		return prop + 8;
	return 0;
}

static void banner(const char *s)
{
	uart_puts(s);
	con_str("", s);
}

static void line2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb)
{
	con_hex2(label, a, va, b, vb);
	uart_puts(label);
	uart_puts(a);
	uart_hex(va);
	uart_puts(" ");
	uart_puts(b);
	uart_hex(vb);
	uart_puts("\n");
}

void shim_main(uint64_t dtb)
{
	uint64_t mmfr0 = rsr("id_aa64mmfr0_el1");
	uint32_t midr = (uint32_t)rsr("midr_el1");
	uint32_t mpidr = (uint32_t)rsr("mpidr_el1");

	uart_puts("\n=== ios-topaz merlin shim stage 1 ===\n");

	/* The framebuffer lk configured: from "atag,videolfb" in the root node. */
	uint32_t len = 0;
	uintptr_t fb = atag_body(fdt_root_prop((uintptr_t)dtb, "atag,videolfb", &len),
				  len, ATAG_VIDEOLFB);
	uint32_t fb_base = 0, fb_w = 0, fb_h = 0, fb_stride = 0, fb_size = 0;
	if (fb) {
		fb_w = le16(fb + 0);
		fb_h = le16(fb + 2);
		fb_stride = le16(fb + 6);
		fb_base = le32(fb + 8);
		fb_size = le32(fb + 12);
		con_setup(fb_base, fb_w, fb_h, fb_stride);
	}

	con_clear(BLUE);
	banner("MERLIN SHIM STAGE 1");
	con_skip();
	line2("CPU", "midr=", midr, "mpidr=", mpidr);
	line2("MMFR0", "tg16=", (uint32_t)((mmfr0 >> 20) & 0xf), "pa=", (uint32_t)(mmfr0 & 0xf));
	line2("DTB", "at=", (uint32_t)dtb, "magic=", dtb ? be32((uintptr_t)dtb) : 0);
	line2("FB", "base=", fb_base, "size=", fb_size);
	line2("FB", "w=", fb_w, "h=", fb_h);
	line2("FB", "stride=", fb_stride, "bpp=", (uint32_t)(fb ? le16(fb + 4) : 0));

	/* Memory lk gave us: "atag,mem" = [size][start_addr]. */
	uintptr_t mem = atag_body(fdt_root_prop((uintptr_t)dtb, "atag,mem", &len), len, ATAG_MEM);
	if (mem) {
		line2("MEM", "size=", le32(mem + 0), "start=", le32(mem + 4));
	} else {
		con_str("MEM", "no atag,mem");
		uart_puts("MEM none\n");
	}

	/* lk's command line for the kernel. */
	uintptr_t args = fdt_root_prop((uintptr_t)dtb, "bootargs", &len);
	if (args) {
		char buf[160];
		uint32_t n = len < sizeof(buf) - 1 ? len : sizeof(buf) - 1;
		for (uint32_t i = 0; i < n; i++)
			buf[i] = ((const char *)args)[i];
		buf[n] = 0;
		con_str("CMDLINE", buf);
		uart_puts("CMDLINE ");
		uart_puts(buf);
		uart_puts("\n");
	}

	con_skip();
	if (((mmfr0 >> 20) & 0xf) == 0) {
		banner("NO 16K GRANULE HERE - A75 HANDOFF NEEDED");
	} else {
		banner("16K GRANULE OK");
	}
	banner("STAGE 1 OK - HOLD POWER TO REBOOT");
	uart_puts("stage 1 ok\n");

	/* Nothing more to do until the A75 handoff and XNU exist. */
	for (;;)
		__asm__ volatile("wfe");
}

/* An unexpected exception: say so on the screen, then stop. */
void exc_handler(uint64_t slot, uint64_t *regs)
{
	con_clear(RED);
	con_str("PANIC", "unexpected exception");
	line2("SLOT", "n=", (uint32_t)slot, "cpu=", (uint32_t)rsr("mpidr_el1"));
	line2("ESR", "lo=", (uint32_t)rsr("esr_el1"), "hi=", (uint32_t)(rsr("esr_el1") >> 32));
	con_hex("ELR", rsr("elr_el1"));
	con_hex("FAR", rsr("far_el1"));
	uart_puts("\nPANIC exception slot ");
	uart_hex(slot);
	uart_puts("\n");
	for (;;)
		__asm__ volatile("wfe");
}

/* A second core, once someone starts it: nothing to do yet. */
void secondary_main(uint64_t idx)
{
	con_str("CPU-ON", "secondary started");
	line2("SEC", "idx=", (uint32_t)idx, "mpidr=", (uint32_t)rsr("mpidr_el1"));
	uart_puts("secondary up\n");
	for (;;)
		__asm__ volatile("wfe");
}

#pragma once
#include <stdint.h>

/*
 * merlin: the framebuffer is the one lk already set up, so its address and
 * geometry are read from the device tree ("atag,videolfb") instead of being
 * a compile-time constant.
 */
extern volatile uint32_t *con_fb;
extern uint32_t con_fb_base, con_fb_w, con_fb_h, con_fb_stride;

void con_setup(uint32_t base, uint32_t w, uint32_t h, uint32_t stride);
void con_clear(uint32_t bg);
void con_skip(void);
void con_str(const char *label, const char *s);
void con_hex(const char *label, uint64_t v);
/* label, then "a=xxxxxxxx b=xxxxxxxx" style pairs of 32-bit values */
void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb);

#define RED	0xffff0000U
#define BLUE	0xff0000a0U
#define WHITE	0xffffffffU
#define YELLOW	0xffffff00U
#define GREEN	0xff00ff00U

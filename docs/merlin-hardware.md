# merlin (Redmi Note 9, MediaTek MT6768) — hardware fact sheet for the XNU port

Facts gathered 2026-10-20 from the device itself (adb), from the downstream DTB of
the sibling board (lancelot, same SoC) and from MediaTek's lk sources.
Everything marked "lancelot" must be replaced by merlin's own DTB once the phone
is rooted (see "Work list" step 2).

## Device

| Item | Value |
| --- | --- |
| Marketing name / model | Redmi Note 9, M2003J15SC (India) |
| Codename | merlin (also merlin_id) |
| SoC | MediaTek MT6768 (Helio G85 / G80), Cortex-A53 + Cortex-A75 |
| Storage | eMMC, **dynamic partitions** ("super"), AVB 1.2, secure boot on |
| Android | 12, MIUI 13 (V13.0.2.0.SJOMIXM) |
| Bootloader | **locked** (ro.boot.flash.locked=1, vbmeta.device_state=locked) |
| USB | micro-USB, adb works, MediaTek fastboot after unlock |

## CPU topology (from the lancelot downstream DTB)

| MPIDR | `compatible` | Note |
| --- | --- | --- |
| 0x000, 0x100, 0x200, 0x300 | arm,cortex-a55 (really A53 class) | cluster 0 — **no 16K granule** |
| 0x400, 0x500 | arm,cortex-a55 (really A53 class) | cluster 1 — **no 16K granule** |
| 0x600, 0x700 | arm,cortex-a75 | cluster 1 — ARMv8.2, **16K granule OK** |

XNU for iOS 16 uses 16K pages on every CPU, so only the **two A75 cores** can run
the kernel. Confirm at runtime with MIDR_EL1 (A75 = 0xd0a, A53 = 0xd03) instead of
trusting the DTB strings.

## SoC registers (mt6768.dtsi + downstream DTB)

| Block | Address | Notes |
| --- | --- | --- |
| GICD | 0x0c000000 | size 0x40000, GICv3 |
| GICR | 0x0c040000 | size 0x200000, stride 0x20000 — same layout as topaz's 0xf200000/0xf300000 |
| INTPOL (sysirq) | 0x0c53a650 | MTK interrupt policy unit |
| UART0 | 0x11002000 | **MTK 16550-style, not PL011**; needs the infracfg clock gate and the 26 MHz baud clock |
| UART1 | 0x11003000 | |
| MSDC0 (eMMC) | 0x11230000 | size 0x10000, IRQ GIC SPI 256, 8-bit bus, HS200/HS400, non-removable |
| msdc0_top (clock/reset) | 0x11cd0000 | |
| MSDC1 (SD card) | 0x11240000 | |
| topckgen | 0x10000000 | clock controller (SYSFS style) |
| infracfg | 0x10001000 | per-infra clock gates (UART0/1, MSDC, PMIC) |
| pericfg | 0x10003000 | |
| apmixed | 0x1000c000 | analog mixed clocks (26 MHz, PLLs) |
| pwrap | 0x1000d000 | MT6358 PMIC wrapper (SPI + mailbox) |
| pinctrl | 0x10005000 (+ iocfg banks 0x10002000..0x10002e00) | 186 GPIOs, EINT at 0x1000b000 |
| watchdog | 0x10007000 | |
| I2C0..8 | 0x11007000, 0x11008000, 0x11009000, 0x1100f000, 0x11011000, 0x11016000, 0x1100d000, 0x11004000, 0x11005000 | the touch panel sits on I2C |
| SPI0..3 | 0x1100a000, 0x11010000, 0x11012000, 0x11013000 | |
| disp_pwm | 0x1100e000 | backlight |

RAM starts at 0x40000000 (lancelot 3 GB: 0x40000000 + 0x3dcb0000). LK reserves the
top of DRAM for the framebuffer (lancelot: 0x7dcb0000, size 0x2250000, 1080x2340,
**stride (1080+8)*4 = 4352** — padded, not 1080*4).

## Boot chain (MediaTek LK)

```
preloader (BROM/DA) -> lk (BL33, S-EL1) -> boot.img (kernel + ramdisk + dtb)
```

From MediaTek's `app/mt_boot/mt_boot.c`:

```c
void lk_jump64(u32 addr, u32 arg1, u32 arg2, u32 arg3) { jumparch64_smc(addr, arg1, arg2, arg3); }
...
if (g_is_64bit_kernel) {
        lk_jump64((u32)entry, (u32)tags, 0, KERNEL_64BITS);
}
```

So a 64-bit kernel is entered with

| Register | Value |
| --- | --- |
| x0 | entry address |
| x1 | ATAGS pointer (the DTB is reachable from here, **not** in x0 as on Qualcomm ABL) |
| x2 | 0 |
| x3 | 1 (KERNEL_64BITS) |

LK also exports `g_fb_base` / `g_fb_size` — the framebuffer it configured — and
implements PSCI (CPU_ON through its SMC), so a second A75 core can be started.

MTK's boot image wraps the kernel and the ramdisk in MTK headers; the kernel
section is a raw binary, so the shim can be an "Image" as on Qualcomm.

## What the sweet/topaz tree gives us, and what must be written

**Reuse as is**

- XNU patch series 0001-0079 (the Qualcomm bring-up).
- `shim/fdt.c` — FDT parser (we need it for the DTB inside the ATAGS).
- `shim/mmu.c` — 16K MMU setup.
- The GICv3 code: it is ARM-standard, only the base addresses and the core count
  change (0xf200000/0xf300000 -> 0x0c000000/0x0c040000).
- `SWEETXNU` payload format + `tools/mkpayload.py`, `tools/mkadt.py`.
- The whole iOS root pipeline: `tools/mkiosroot.sh`, `tools/sweet-root-tweaks.py`,
  `img2simg` (device independent — the same image serves every port).

**Write from scratch**

- `shim/mtk/`: entry for the LK calling convention, ATAGS parsing to find the
  DTB, an MTK UART console (0x11002000 + infracfg clock gate), payload loading
  from the boot.img ramdisk, PSCI start of the second A75 core.
- An eMMC (MSDC) block driver inside XNU, plus the topckgen/infracfg clock gates
  it needs. Lead: XNU already carries an SD host controller driver (AppleSDHC in
  IOStorageFamily) — its command/response machinery can be reused for MSDC.
- Clock control (topckgen/infracfg/apmixed) and GPIO (pinctrl) access, which the
  Qualcomm code got from RPM/SPMI.
- The display path: copy the rendered frames into LK's framebuffer.
- Later: touch (Novatek NT36672 on I2C), battery/PMIC (MT6358 over pwrap).

## Work list

1. **Unlock the bootloader** — mtkclient: phone in BROM mode, then
   `mtk.py printgpt`, `mtk.py e metadata,userdata,md_udc`,
   `mtk.py da seccfg unlock`, `mtk.py reset`. Needs the MTK VCOM driver and
   UsbDk (unsigned -> test signing). After that `adb reboot bootloader` gives
   MediaTek fastboot.
2. **Get merlin's own DTB** — root via a universal recovery for mt6768, then read
   /proc/device-tree or dump `boot`; replace the lancelot numbers (RAM size,
   framebuffer address/stride, panel, touch, eMMC settings).
3. **New shim for LK** (the Qualcomm shim cannot be reused as is: wrong entry
   convention, wrong console, wrong core set).
4. **XNU patches for mt6768** — CPU topology (2 A75 cores), the MSDC/eMMC driver,
   the clock gates, the framebuffer, then touch and power.
5. **Root image on eMMC** — the HFS+ volume is the same as sweet's, but the
   device uses dynamic partitions: `userdata` is a logical partition inside
   `super`, so either flash a dedicated logical partition or use
   `fastboot flash userdata`.
6. **Boot** — build a MTK-format boot.img with our shim as the kernel and the
   XNU payload in the ramdisk; keep a copy of the stock boot image first.

## Risk

- The MSDC driver inside XNU is the long pole. If MSDC turns out to be too far
  from the SDHC driver, the fallback is a RAM disk, which does not fit (the iOS
  root is ~12 GB) — so this part is effectively mandatory.
- Only two usable cores (A75 @ ~2 GHz) and no GPU driver for the Mali-G57: the
  UI would be rendered by the CPU at a few frames per second, like topaz.
- If the MediaTek preloader refuses the unlock, the port has no way in; the
  fallback is a different phone (a Redmi Note 12 4G would run the existing
  ios-topaz port as is).

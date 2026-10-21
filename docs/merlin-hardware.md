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

## 20 Oct 2026 (evening) - what the phone actually does

Everything below was observed on the phone itself, not assumed.

### The LK boot menu

```
Select Boot Mode:  (VOLUME_UP to select, VOLUME_DOWN is OK.)
[Recovery  Mode]   -> the MIUI recovery (adb in sideload mode only)
[Fastboot  Mode]   -> USB VID_0BB4&PID_0C01, interface class FF/42/03 (fastboot)
[Normal   Boot]
```

- **VOLUME_UP moves the cursor, VOLUME_DOWN confirms** (not the other way round).
- There is **no BROM entry** in the menu. BROM is reached from a cold
  power-off: hold **Vol Up + Vol Down** while plugging the cable in.
- Plugging the cable in with the phone off and **no buttons pressed** gives
  the **preloader** (`USB\VID_0E8D&PID_0003`) which exposes a working
  **COM port** - that is the path mtkclient talks to (`--serialport COMx`),
  and it needs no extra driver.
- The preloader also shows up as a HID-only device
  (`USB\VID_0E8D&PID_20FF`, class 03) when Windows picks the HID driver;
  WinUSB on that node (Zadig) makes it usable as well.

### fastboot

`USB\VID_0BB4&PID_0C01` is a real fastboot interface (class FF/42/03) but
MediaTek uses its own VID, so Windows has no driver for it by default. The
inbox `winusb.inf` only matches `Class_ff&SubClass_42&Prot_01`, so
**Zadig -> WinUSB** on that node is what makes the AOSP fastboot tool work.

`fastboot flashing unlock` fails on Xiaomi ("Unlock failed") - the phone
needs Mi Unlock (authorised Mi account). The MTK path (`mtk.py da seccfg
unlock`) does not need an account and is the way in.

Useful numbers from `fastboot getvar all`:

| item | value |
| --- | --- |
| product / bootloader | merlin, `merlin-f617d8537-20220822153313` |
| boot | 0x4000000 (64 MiB) |
| dtbo | 0x1000000 (16 MiB) |
| vbmeta | 0x800000 |
| metadata | 0x2000000 |
| userdata | 0xc1f4f8000 (31 GiB) |
| max-download-size | 0x8000000 (128 MiB) |
| unlocked / secure | no / yes, anti 2 |

`fastboot fetch` is not supported by this bootloader, so the stock boot
image has to be read with mtkclient instead.

### The LK handover (confirmed from the lk sources)

`app/mt_boot/mt_boot.c`: `boot_linux()` -> `lk_jump64(entry, tags, 0,
KERNEL_64BITS)`, so **x1 is the device tree lk built** (not x0 like Qualcomm
ABL). That tree carries lk's own root properties - `atag,videolfb` (the
framebuffer lk set up: base, size, width, height, depth, **linelength**),
`atag,mem`, `atag,cmdline` and `bootargs` - so the shim reads the real
geometry from it. `app/mt_boot/decompressor.c` gunzips the kernel section
of a 64-bit boot image, so the shim and the XNU payload ride in there
together (the decompressed size has to stay under 0x1C00000 = 28 MiB).

The device tree of this phone says `/memory reg = 0x40000000+0x3e605000`,
and the eMMC node is `/msdc@11230000` (reg 0x11230000+0x10000,
**interrupts 0 100 8**, bus-width 8, max-frequency 200 MHz, non-removable).

### The iOS root image

The CI build-root artifact is a 5.98 GB zip holding `ios16-root.simg` split
into parts; the sparse image itself is 12,145,439,044 bytes (11.31 GB).
The sweet project flashes that image to **userdata**
(`fastboot flash -S 512M userdata <img>.simg`), and the kernel boots it
through the HFS+ driver with `rd=<root device>`. For merlin that is
`rd=msdcroot0` with `msdcroot=userdata` naming the GPT partition.

## 21 Oct 2026 (morning) - the USB modes and what mtkclient needs

### The USB modes of this phone, and how to reach them

| what you do | what the PC sees |
| --- | --- |
| power off, plug in, press no button | preloader, `USB\VID_0E8D&PID_20FF`, **interface class 03 (HID)** - it is a keyboard, no serial |
| power off, plug in, hold **Vol Up** | the MIUI recovery menu |
| power off, plug in, hold **Vol Up + Vol Down** | preloader again (HID) |
| power off, plug in, hold **Vol Up + Vol Down + Power** | preloader again (HID) |
| `adb reboot bootloader` | the LK fastboot screen, `USB\VID_0BB4&PID_4E11` or `...&PID_4EE7` (fastboot interface, class FF/42/03) |
| while the phone boots | the **BROM**, `USB\VID_0E8D&PID_0003`, a real CDC-ACM serial port (COM5) - visible for a second or two |

Only the BROM has a usable serial port. The preloader's HID interface cannot be
bound to a serial driver: Windows will create a COM port for it, but opening
that port fails ("could not open port: The system cannot find the file
specified") because the interface is not CDC-ACM at all.

### mtkclient bugs hit on the way (all four are in the tool, not the phone)

1. `mtk_main.py`: the subparser of argparse **resets `--serialport` to its own
   default**, so the flag never reached the port. Fixed by reading the value
   from `sys.argv` when `args.serialport` is None.
2. `seriallib.py`: `detectdevices()` goes through pyusb and dies with
   "Operation not supported or unimplemented on this platform" on this PC.
   Fixed by trusting the port given on the command line and by wrapping the
   enumeration in try/except.
3. `seriallib.py`: it took the *first* detected port. The phone exposes a
   broken port next to the working one, so it now tries every candidate and
   keeps the first that really opens.
4. `seriallib.py`: `connect()` gave up on the first miss. The BROM only shows
   up for a second or two, so it now waits up to 120 s, polling every 100 ms.

With those fixes `mtk.py --serialport DETECT printgpt` grabs the BROM's COM
port within a second or two of the phone booting.

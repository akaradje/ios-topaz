# merlin — how the boot is wired, and what has to change for MediaTek

Written 20 Oct 2026 while porting iOS 16 to the Redmi Note 9 (merlin, MT6768).
Everything here is read out of MediaTek's own lk sources
(`yusixiao/lk-mtk`) and the phone itself, not guessed.

## What lk does with a 64-bit kernel

```
app/mt_boot/mt_boot.c
    boot_linux(kernel_target_addr, tags_target_addr, machtype,
               ramdisk_target_addr, ramdisk_real_sz)
      -> lk_jump64(entry, tags, 0, KERNEL_64BITS)
         (jumparch64_smc: a PSCI SMC call into the secure world)
```

So the kernel is entered with

| Register | Value |
| --- | --- |
| x0 | entry address |
| x1 | **the device tree lk built** (`tags_target_addr`) |
| x2 | 0 |
| x3 | 1 (KERNEL_64BITS) |

The DTB is in **x1**, not in x0 like Qualcomm's ABL. lk builds that tree
itself (`bootargs_init(fdt)`), so it is the *same* tree the Android kernel
booted with, plus lk's own properties in the root node:

| Root property | Content |
| --- | --- |
| `atag,videolfb` | whole ATAG: `[u32 size][u32 tag 0x54410008][struct tag_videolfb]` — the framebuffer lk set up (base, size, width, height, depth, **linelength**) |
| `atag,mem` | whole ATAG: `[u32 size][u32 tag 0x54410002][struct mem_info]` — size and start address of RAM |
| `atag,cmdline`, `bootargs` | the kernel command line lk assembled |
| `atag,boot`, `atag,devinfo`, ... | other lk boot tags |

The shim therefore reads the framebuffer geometry from the tree instead of
hard-coding lancelot's numbers.

## The kernel section is gzip

`app/mt_boot/decompressor.c` -> `decompress_kernel()` gunzips the kernel
section of a 64-bit boot image into `kernel_target_addr` (must be 512 KiB
aligned, e.g. 0x40080000) before jumping to it. Consequences:

- the shim is an arm64 `Image` (64-byte header + code), gzipped, and
- **the XNU payload rides behind the shim inside that same section**: LK
  decompresses `shim | payload` as one blob, the shim finds the payload
  at `_end` (the topaz trick) and boots XNU. The decompressed size has to
  stay under `KERNEL_DECOMPRESS_SIZE` (0x1C00000 = 28 MiB); the XNU
  kernel is ~18 MiB, so it fits.
- the ramdisk does not have to carry the payload, and the stock ramdisk
  can simply be left in place.

## Flashable image

`tools/mkbootimg_mtk.py` patches the **stock** boot image: only the kernel
section is replaced (gzip of shim + payload), the ramdisk, the DTB section
and the header stay as the phone has them. The DTB matters: it is what lk
turns into the tree the shim gets in x1, so the real board file is used.

Layout of an MTK boot image (lk: `platform/common/include/bootimg.h`):

```
header (0x800 bytes = 1 page) | kernel | ramdisk | second | recovery_dtbo | dtb
```

## Memory map and the shim's own address

lk loads the shim at `kernel_target_addr` (0x40080000) — inside the RAM
that XNU will use. XNU's `phys_base` must therefore sit **above** the
shim, e.g. 0x44000000, so that copying the kernel image into place does
not overwrite the shim that is still running. That is a job for the merlin
`tools/mkadt.py` (the topaz one hard-codes the topaz map).

## Cores

| MPIDR | Core | Note |
| --- | --- | --- |
| 0x000–0x500 | 6× A53 | no 16K granule — cannot run the kernel |
| 0x600, 0x700 | 2× A75 | 16K granule, ARMv8.2 — these run XNU |

iOS 16 needs 16K pages on every CPU, so the shim has to hand over to an
A75 with PSCI `CPU_ON` (like topaz hands over from the Silver cores to the
Gold ones). Which core lk leaves us on, and what context structure
lk's PSCI expects, is still to be checked on the phone.

## Stage 1 (done)

`shim/mtk/` boots, reads the tree lk handed over and prints the
framebuffer geometry, the memory and the command line on the screen lk
already had up. It is built by `shim/build-mtk.sh` in CI
(`.github/workflows/shim-mtk.yml`); there is no local aarch64 toolchain
on this PC and no WSL, so CI is the only way to build.

## Still open

1. unlock the bootloader (mtkclient `da seccfg unlock`; the phone must be
   in BROM mode, and UsbDk must **not** be loaded while it is plugged in —
   it crashed the PC with a WDF_VIOLATION bugcheck).
2. read the stock `boot` partition for the image to patch.
3. merlin `tools/mkadt.py` (2 A75 cores, memory map, framebuffer).
4. the XNU patch series for mt6768 — the long pole is the eMMC (MSDC)
   driver in the kernel; XNU's own SD host driver is the starting point.

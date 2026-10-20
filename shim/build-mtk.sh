#!/bin/bash
# Build the merlin (MediaTek MT6768) boot shim.
#
# The shim is an arm64 Image like the topaz one, but entered the way
# MediaTek's lk enters a 64-bit kernel: x1 = the device tree, x0 = entry.
set -euo pipefail
cd "$(dirname "$0")/.."

CC=${CC:-aarch64-linux-gnu-gcc}
OBJCOPY=${OBJCOPY:-aarch64-linux-gnu-objcopy}
READELF=${READELF:-aarch64-linux-gnu-readelf}
NM=${NM:-aarch64-linux-gnu-nm}
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra"

out=shim/out-mtk
mkdir -p "$out"
for f in shim/mtk/start_mtk.S shim/mtk/shim_mtk.c shim/mtk/console.c shim/mtk/uart.c shim/mtk/loader.c shim/mtk/fdt.c; do
	$CC $CFLAGS -c "$f" -o "$out/$(basename "${f%.*}").o"
done

# The image runs wherever lk puts it, with no relocation pass: only the
# header's image_size (start_mtk.o, linked at 0) may be an absolute address.
abs=$($READELF -r "$out/shim_mtk.o" "$out/console.o" "$out/uart.o" "$out/loader.o" "$out/fdt.o" | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }

$CC $CFLAGS -static -T shim/mtk/shim_mtk.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	"$out/start_mtk.o" "$out/shim_mtk.o" "$out/console.o" "$out/uart.o" "$out/loader.o" "$out/fdt.o" -o "$out/shim-mtk.elf"
$OBJCOPY -O binary "$out/shim-mtk.elf" "$out/Image"

# lk copies the kernel section and pads it to image_size, so .bss/stacks
# exist as zeroed bytes.
size=$((16#$($NM "$out/shim-mtk.elf" | awk '$3=="_end"{print $1}')))
truncate -s "$size" "$out/Image"

# lk gunzips the kernel section of a 64-bit boot image
# (lk: app/mt_boot/decompressor.c), so keep a compressed copy as well.
gzip -9 -n -c "$out/Image" > "$out/Image.gz"

ls -l "$out/Image" "$out/Image.gz"
echo "build ok: $out/Image"

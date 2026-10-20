#!/usr/bin/env python3
"""Patch a MediaTek boot image (merlin / MT6768).

MTK's boot image is the AOSP layout with an extended header
(lk: platform/common/include/bootimg.h):

    header (header_size bytes, one page) | kernel | ramdisk | second |
    recovery_dtbo | dtb

Every section is page aligned.  For a 64-bit kernel lk gunzips the kernel
section (lk: app/mt_boot/decompressor.c) and jumps into the result, so the
shim and the XNU payload behind it go in there compressed.  The ramdisk, the
DTB and the rest of the header stay exactly as the stock image has them:
the DTB is what lk turns into the device tree the shim receives in x1, and
the stock ramdisk is simply ignored by the shim.

  usage:
    mkbootimg_mtk.py --info stock-boot.img
    mkbootimg_mtk.py --stock stock-boot.img --kernel shim-payload.gz \
                      --out boot-ios.img
"""
import argparse
import hashlib
import struct
import sys

# struct bootimg_hdr (packed, little endian) - lk: platform/common/include/bootimg.h
HDR = struct.Struct('<8s 10I 16s 512s 8I 1024s I Q I I Q')
MAGIC = b'ANDROID!'


def parse_header(data):
    if len(data) < HDR.size:
        raise SystemExit('file too small for a boot image header')
    f = HDR.unpack_from(data, 0)
    h = {
        'magic': f[0], 'kernel_sz': f[1], 'kernel_addr': f[2],
        'ramdisk_sz': f[3], 'ramdisk_addr': f[4], 'second_sz': f[5],
        'second_addr': f[6], 'tags_addr': f[7], 'page_sz': f[8],
        'header_version': f[9], 'os_version': f[10], 'name': f[11],
        'cmdline': f[12], 'id': tuple(f[13:21]), 'extra_cmdline': f[21],
        'recovery_dtbo_sz': f[22], 'recovery_dtbo_off': f[23],
        'header_size': f[24], 'dtb_sz': f[25], 'dtb_addr': f[26],
    }
    if h['magic'] != MAGIC:
        raise SystemExit('bad magic %r (not a MediaTek boot image)' % h['magic'])
    return h


def pack_header(h):
    return HDR.pack(
        h['magic'], h['kernel_sz'], h['kernel_addr'], h['ramdisk_sz'],
        h['ramdisk_addr'], h['second_sz'], h['second_addr'], h['tags_addr'],
        h['page_sz'], h['header_version'], h['os_version'], h['name'],
        h['cmdline'], *h['id'], h['extra_cmdline'], h['recovery_dtbo_sz'],
        h['recovery_dtbo_off'], h['header_size'], h['dtb_sz'], h['dtb_addr'],
    )


def align_up(n, page):
    return (n + page - 1) // page * page


def section_offsets(h):
    """Byte offsets of every section in the image."""
    page = h['page_sz']
    off = align_up(max(page, h['header_size']), page)
    out = {'header': (0, align_up(max(page, h['header_size']), page))}
    for key, sz_key in (('kernel', 'kernel_sz'), ('ramdisk', 'ramdisk_sz'),
                        ('second', 'second_sz'),
                        ('recovery_dtbo', 'recovery_dtbo_sz'), ('dtb', 'dtb_sz')):
        size = h[sz_key]
        if size:
            out[key] = (off, off + size)
            off = align_up(off + size, page)
        else:
            out[key] = None
    out['end'] = off
    return out


def show(h, path):
    print('file            : %s' % path)
    print('header_version  : %d   os_version: %08x' % (h['header_version'], h['os_version']))
    print('page_sz         : %d   header_size: %d' % (h['page_sz'], h['header_size']))
    print('name            : %s' % h['name'].split(b'\0')[0].decode('utf-8', 'replace'))
    print('cmdline         : %s' % h['cmdline'].split(b'\0')[0].decode('utf-8', 'replace'))
    if h['extra_cmdline'].strip(b'\0'):
        print('extra_cmdline   : %s' % h['extra_cmdline'].split(b'\0')[0].decode('utf-8', 'replace'))
    print('kernel          : size %d  addr 0x%x' % (h['kernel_sz'], h['kernel_addr']))
    print('ramdisk         : size %d  addr 0x%x' % (h['ramdisk_sz'], h['ramdisk_addr']))
    print('second          : size %d  addr 0x%x' % (h['second_sz'], h['second_addr']))
    print('recovery_dtbo   : size %d  off 0x%x' % (h['recovery_dtbo_sz'], h['recovery_dtbo_off']))
    print('dtb             : size %d  addr 0x%x' % (h['dtb_sz'], h['dtb_addr']))
    print('tags_addr       : 0x%x' % h['tags_addr'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stock', help='stock boot image to patch')
    ap.add_argument('--kernel', help='new kernel section (gzipped shim + payload)')
    ap.add_argument('--out', help='output image')
    ap.add_argument('--info', action='store_true',
                    help='only print the header of --stock')
    args = ap.parse_args()

    if args.info:
        if not args.stock:
            ap.error('--info needs --stock')
        with open(args.stock, 'rb') as f:
            data = f.read()
        show(parse_header(data), args.stock)
        return

    if not (args.stock and args.kernel and args.out):
        ap.error('--stock, --kernel and --out are needed')

    with open(args.stock, 'rb') as f:
        data = f.read()
    h = parse_header(data)
    off = section_offsets(h)

    with open(args.kernel, 'rb') as f:
        kernel = f.read()

    page = h['page_sz']
    tail = data[off['end'] - 0:] if 'end' in off else b''

    # Everything after the kernel section is copied over untouched.
    rest = b''
    if off['ramdisk']:
        rest = data[off['ramdisk'][0]:off['end']]

    h['kernel_sz'] = len(kernel)
    out = bytearray()
    out += pack_header(h)
    out += b'\0' * (off['kernel'][0] - len(out))
    out += kernel
    out += b'\0' * (align_up(len(out), page) - len(out))
    out += rest

    with open(args.out, 'wb') as f:
        f.write(out)

    print('wrote %s (%d bytes)' % (args.out, len(out)))
    print('  kernel section : %d bytes (was %d)' % (len(kernel), parse_header(data)['kernel_sz']))
    print('  sha1(kernel)   : %s' % hashlib.sha1(kernel).hexdigest())
    print('  kept           : ramdisk %d, dtb %d, header v%d' %
          (h['ramdisk_sz'], h['dtb_sz'], h['header_version']))


if __name__ == '__main__':
    main()

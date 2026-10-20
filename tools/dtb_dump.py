#!/usr/bin/env python3
"""Dump a flattened device tree (DTB) as a readable tree.

  dtb_dump.py FILE.dtb [--reg] [--all-props] [--grep SUBSTR]

The interesting properties are printed by default (compatible, reg, interrupts,
clocks, status, ...).  --reg decodes reg into address/size pairs using the
parent's #address-cells/#size-cells, --all-props prints every property and
--grep keeps only the nodes whose path or properties match a substring.

Used to read the board device tree of a phone without dtc (the port needs the
real addresses: GIC, UART, eMMC host, clocks, framebuffer).
"""
import struct
import sys

FDT_BEGIN_NODE = 0x1
FDT_END_NODE = 0x2
FDT_PROP = 0x3
FDT_NOP = 0x4
FDT_END = 0x9

INTERESTING = {
    'compatible', 'reg', 'ranges', 'interrupts', 'interrupt-parent', 'status',
    'clock-names', 'clocks', 'device_type', 'reg-names', '#address-cells',
    '#size-cells', '#interrupt-cells', 'model', 'memory', 'bootargs',
    'phy-mode', 'capabilities', 'num-lanes', 'max-link-speed', 'non-removable',
    'linux,phandle', 'phandle', 'pinctrl-0', 'operating-points-v2',
    'assigned-clock-rates', 'clock-frequency', 'bank-width', 'mmc-ext-csd',
}

CELL = 4


def align4(n):
    return (n + 3) & ~3


class Dtb:
    def __init__(self, path):
        with open(path, 'rb') as f:
            self.data = f.read()
        (self.magic, self.totalsize, self.off_struct, self.off_strings,
         self.off_rsv, self.version, self.lastcpuid, self.bootcpuid,
         self.size_strings, self.size_struct) = struct.unpack_from('>10I', self.data, 0)
        if self.magic != 0xd00dfeed:
            raise ValueError('not a device tree blob (magic 0x%08x)' % self.magic)
        self.strings = self.data[self.off_strings:self.off_strings + self.size_strings]

    def string(self, off):
        end = self.strings.index(b'\0', off)
        return self.strings[off:end].decode('utf-8', 'replace')

    def rsvmap(self):
        out = []
        p = self.off_rsv
        while True:
            a, b = struct.unpack_from('>QQ', self.data, p)
            p += 16
            if a == 0 and b == 0:
                break
            out.append((a, b))
        return out

    def walk(self):
        """Yield ('node', path, depth) and ('prop', path, name, value)."""
        p = self.off_struct
        stack = []
        while True:
            tok = struct.unpack_from('>I', self.data, p)[0]
            p += 4
            if tok == FDT_BEGIN_NODE:
                end = self.data.index(b'\0', p)
                name = self.data[p:end].decode('utf-8', 'replace')
                p = align4(end + 1)
                stack.append(name)
                yield ('node', '/'.join(stack), len(stack))
            elif tok == FDT_END_NODE:
                stack.pop()
            elif tok == FDT_PROP:
                ln, noff = struct.unpack_from('>II', self.data, p)
                p += 8
                val = self.data[p:p + ln]
                p = align4(p + ln)
                yield ('prop', '/'.join(stack), self.string(noff), val)
            elif tok == FDT_NOP:
                continue
            elif tok == FDT_END:
                break
            else:
                raise ValueError('bad token 0x%x at 0x%x' % (tok, p - 4))


def decode_reg(val, acells, scells):
    if acells == 2 and scells == 2 and len(val) % 16 == 0:
        parts = []
        for i in range(0, len(val), 16):
            hi, lo, shi, slo = struct.unpack_from('>4Q', val, i)
            base = (hi << 32) | lo
            parts.append('0x%x..0x%x' % (base, base + ((shi << 32) | slo)))
        return ' '.join(parts)
    if len(val) % 16 == 0:
        parts = []
        for i in range(0, len(val), 16):
            a, s = struct.unpack_from('>2Q', val, i)
            parts.append('0x%x+0x%x' % (a, s))
        return ' '.join(parts)
    if len(val) % 8 == 0:
        parts = []
        for i in range(0, len(val), 8):
            a = struct.unpack_from('>Q', val, i)[0]
            parts.append('0x%x' % a)
        return ' '.join(parts)
    if len(val) % 4 == 0:
        return ' '.join('0x%x' % v for v in struct.unpack('>%dI' % (len(val) // 4), val))
    return val.hex()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    want_reg = '--reg' in flags
    want_all = '--all-props' in flags
    grep = None
    for f in flags:
        if f.startswith('--grep='):
            grep = f.split('=', 1)[1]
    dtb = Dtb(path)
    print('# %s: %d bytes, version %d' % (path, dtb.totalsize, dtb.version))
    print('# reserved memory:')
    for a, b in dtb.rsvmap():
        print('#   0x%x..0x%x (%d MiB)' % (a, b, (b - a) >> 20))
    if '--tree' in flags:
        for item in dtb.walk():
            if item[0] == 'node':
                print('  ' * (item[2] - 1) + item[1].split('/')[-1] or '/')
        return 0
    acells, scells = 2, 1
    pending = {}
    keep = []
    for item in dtb.walk():
        if item[0] == 'node':
            path_ = item[1]
            if path_.count('/') == 1:
                acells, scells = 2, 1
        else:
            _, path_, name, val = item
            if name == '#address-cells':
                acells = struct.unpack('>I', val)[0] if len(val) >= 4 else 2
            elif name == '#size-cells':
                scells = struct.unpack('>I', val)[0] if len(val) >= 4 else 1
            pending.setdefault(path_, {})[name] = val
    for item in dtb.walk():
        if item[0] != 'prop':
            continue
        _, path_, name, val = item
        props = pending.get(path_, {})
        if grep and grep not in path_ and not any(grep in n for n in props):
            continue
        if name not in INTERESTING and not want_all:
            continue
        if name == 'reg' and want_reg:
            print('%-60s %-14s = %s' % (path_, name, decode_reg(val, acells, scells)))
        elif name in ('compatible', 'status', 'device_type', 'clock-names', 'reg-names',
                      'interrupt-parent', 'model', 'bootargs', 'phy-mode', 'num-lanes'):
            txt = val.rstrip(b'\0').decode('utf-8', 'replace').replace('\0', ', ')
            print('%-60s %-14s = %s' % (path_, name, txt))
        elif name == 'interrupts':
            nums = struct.unpack('>%dI' % (len(val) // 4), val)
            print('%-60s %-14s = %s' % (path_, name, ' '.join(str(n) for n in nums)))
        elif name in ('clocks', 'pinctrl-0', 'assigned-clock-rates'):
            nums = struct.unpack('>%dI' % (len(val) // 4), val)
            print('%-60s %-14s = %s' % (path_, name, ' '.join(str(n) for n in nums)))
        else:
            print('%-60s %-14s = %s' % (path_, name, val.hex()))
    return 0


if __name__ == '__main__':
    sys.exit(main())

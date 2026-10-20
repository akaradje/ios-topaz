#!/usr/bin/env python3
"""Build the Apple Device Tree the merlin (Redmi Note 9, MT6768) xnu needs.

Same shape as the topaz ADT (tools/mkadt.py) but with the MediaTek hardware
map.  Everything here is either read out of MediaTek's dtsi / lk sources or
has to be confirmed on the phone - the values marked TODO are the ones that
still need a real reading from the device.

  usage: mkadt_merlin.py OUT.adt [--dump]
                             [--phys-base 0x44000000] [--mem-size 0x3a000000]
                             [--fb-base 0x7dcb0000] [--fb-stride 4352]
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# /arm-io children are relative to this; it must not be 0 (serial_init bails).
SOC_BASE = 0x0c000000

# GICv3 on mt6768: interrupt-controller@c000000, redistributor stride 0x20000
GICD, GICD_SIZE = 0x0c000000, 0x40000
GICR, GICR_SIZE = 0x0c040000, 0x200000

# The generic timer: mt6768.dtsi lists PPI 13/14 (physical) and 11/10, so the
# virtual timer is INTID 11 here, not the usual 27.
VTIMER_INTID = 11
TIMEBASE = 26000000          # TODO: read cntfrq_el0 on the phone

# Only the two Cortex-A75 cores can run xnu (the A53s have no 16K granule).
# MPIDR 0x600 and 0x700 (cluster 1).
CPU_MPIDRS = (0x600, 0x700)
CPU_CLOCK = 2000000000       # TODO: read the A75 frequency on the phone

# lk loads the shim at 0x40080000, inside the RAM xnu will use, so xnu's
# physical window has to start above it.
PHYS_BASE = 0x44000000
MEM_SIZE = 0x3a000000        # TODO: the real RAM size of this phone

# Framebuffer lk set up. The shim reads the real values from the device tree
# ("atag,videolfb"), these are only the fallback in the ADT.
FB, FB_SIZE = 0x7dcb0000, 0x2250000
FB_W, FB_H, FB_STRIDE = 1080, 2340, 4352      # (1080 + 8) * 4, padded

# eMMC host (MSDC0) - the XNU driver for it does not exist yet.
MSDC, MSDC_SIZE = 0x11230000, 0x10000
TOPCKGEN = 0x10000000
INFRACFG = 0x10001000

MERLIN_ECID = 0x4d45524c000001                # 'MERL' + 1, synthetic
BOOT_MANIFEST_HASH = hashlib.sha384(b'merlin boot manifest').digest()

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW; the real
# D22AP tree is an Apple artifact and stays out of git (see tools/mkadt.py).
D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '../research/ipsw-x/d22ap.adt')


def d22ap_product(path=D22AP_ADT):
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')


u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build(phys_base=PHYS_BASE, mem_size=MEM_SIZE, fb=FB, fb_w=FB_W, fb_h=FB_H,
          fb_stride=FB_STRIDE):
    seed = os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('merlin-shim')),
        ('system-firmware-version', cstr('merlin-shim')),
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        ('crypto-hash-method', cstr('sha2-384')),
        # 1080x2340 @3x = 360x780 points
        ('display-scale', u32(3)),
        ('unique-chip-id', struct.pack('<Q', MERLIN_ECID)),
        ('chip-id', u32(0x8015)),
        # dev-fused, undemoted: mobileactivationd takes the native
        # "Hactivation" branch (no SEP, no baseband on this phone).
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        # SIP relaxed like `csrutil disable`: the iOS shared cache is in no
        # trust cache, so dyld can only map it with CSR_ALLOW_UNRESTRICTED_FS.
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # The two A75s. 'reg' is the real MPIDR (Aff1:Aff0), not a logical id.
    cpu_nodes = []
    for i, mpidr in enumerate(CPU_MPIDRS):
        cpu_nodes.append(node(f'cpu{i}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cstr('arm,cortex-a75') + cstr('arm,v8')),
            ('reg', u32(mpidr)),
            ('cpu-id', u32(i)),
            ('cluster-id', u32(0)),
            ('cluster-type', u32(0)),      # homogeneous CLUSTER_TYPE_SMP
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(i)),
            ('l2-cache-id', u32(0)),
            ('l3-cache-id', u32(0)),
            ('state', cstr('running' if i == 0 else 'stopped')),
            ('timebase-frequency', u32(TIMEBASE)),
            ('clock-frequency', u32(CPU_CLOCK)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1600000000)),
            ('peripheral-frequency', u32(TIMEBASE)),
            ('fixed-frequency', u32(TIMEBASE)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(VTIMER_INTID)),
        ('reg', u64(GICD - SOC_BASE, GICD_SIZE, GICR - SOC_BASE, GICR_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('sweet-io')),
        ('compatible', cstr('sweet-io') + cstr('merlin-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        # watchdogd crashes trying to set the PMU boot stage if this node
        # does not say there is no PMU.
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('sweet,display')),
            ('canvas-width', u32(fb_w)),
            ('canvas-height', u32(fb_h)),
        ])])

    fbcon = node('sweet-fbcon', [
        ph(),
        ('reg', u64(fb, FB_SIZE)),
        ('width', u32(fb_w)),
        ('height', u32(fb_h)),
        ('stride', u32(fb_stride)),
    ])

    # eMMC host: the XNU driver for it is still to be written.
    msdc = node('merlin-msdc', [
        ph(),
        ('compatible', cstr('mtk,msdc')),
        ('reg', u64(MSDC, MSDC_SIZE)),
        ('clocks', u64(TOPCKGEN, 0x1000)),
        ('clock-names', cstr('topckgen')),
        ('infracfg', u64(INFRACFG, 0x1000)),
    ])

    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('xiaomi,merlin') +
                    cstr('xiaomi,sweet') + cstr('mediatek,mt6768') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, msdc, buttons] + product)


def argval(flag, default):
    if flag in sys.argv:
        return int(sys.argv[sys.argv.index(flag) + 1], 0)
    return default


if __name__ == '__main__':
    blob = adt.serialize(build(
        phys_base=argval('--phys-base', PHYS_BASE),
        mem_size=argval('--mem-size', MEM_SIZE),
        fb=argval('--fb-base', FB),
        fb_w=argval('--fb-w', FB_W),
        fb_h=argval('--fb-h', FB_H),
        fb_stride=argval('--fb-stride', FB_STRIDE),
    ))
    open(sys.argv[1], 'wb').write(blob)
    if '--dump' in sys.argv:
        adt.dump(adt.parse(blob)[0])
    print(f'{sys.argv[1]}: {len(blob)} bytes', file=sys.stderr)

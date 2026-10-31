"""Local, read-only disassembly aid (requires pefile and capstone)."""
import argparse
import struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

parser = argparse.ArgumentParser(__doc__)
parser.add_argument('executable')
parser.add_argument('--string')
parser.add_argument('--rva', type=lambda s: int(s, 0))
parser.add_argument('--size', type=lambda s: int(s, 0), default=512)
parser.add_argument('--xref', type=lambda s: int(s, 0))
parser.add_argument('--function', type=lambda s: int(s, 0))
args = parser.parse_args()
pe = pefile.PE(args.executable, fast_load=True)
image = pe.get_memory_mapped_image()
md = Cs(CS_ARCH_X86, CS_MODE_64)
if args.function is not None:
    section = next(s for s in pe.sections if s.Name.startswith(b'.pdata'))
    for start, end, unwind in struct.iter_unpack('<III', section.get_data()[:section.Misc_VirtualSize//12*12]):
        if start <= args.function < end:
            args.rva, args.size = start, end-start
            print('function', hex(start), hex(end))
if args.xref is not None:
    section = pe.sections[0]
    data = section.get_data()
    for off in range(len(data)-4):
        if section.VirtualAddress + off + 4 + struct.unpack_from('<i', data, off)[0] == args.xref:
            print('relative displacement at', hex(section.VirtualAddress+off))
if args.string:
    target = image.find(args.string.encode())
    print('string RVA:', hex(target))
    text = pe.sections[0]
    data = text.get_data()
    for off in range(len(data)-7):
        if data[off] in (0x48, 0x4c) and data[off+1] == 0x8d and data[off+2] & 0xc7 == 5:
            rva = text.VirtualAddress + off
            if rva + 7 + struct.unpack_from('<i', data, off+3)[0] == target:
                print('xref:', hex(rva))
                for ins in md.disasm(image[rva-64:rva+128], rva-64):
                    print(f'{ins.address:08x} {ins.bytes.hex():24} {ins.mnemonic} {ins.op_str}')
if args.rva is not None:
    for ins in md.disasm(image[args.rva:args.rva+args.size], args.rva):
        print(f'{ins.address:08x} {ins.bytes.hex():24} {ins.mnemonic} {ins.op_str}')

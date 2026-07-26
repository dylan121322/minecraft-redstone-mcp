#!/usr/bin/env python3
"""4-bit CPU simulator — instruction set, ALU, and program execution."""

def alu(op, a, b, cin=0):
    a, b = a & 0xF, b & 0xF
    if op == 'ADD': return {'r': (a+b+cin)&0xF, 'c': 1 if a+b+cin>15 else 0, 'z': (a+b+cin)&0xF==0}
    if op == 'SUB': b_inv = (~b)&0xF; r = (a+b_inv+1)&0xF; return {'r': r, 'c': 1 if a>=b else 0, 'z': r==0}
    if op == 'AND': r = a&b; return {'r': r, 'c': 0, 'z': r==0}
    if op == 'OR':  r = a|b; return {'r': r, 'c': 0, 'z': r==0}
    if op == 'NOT': r = (~a)&0xF; return {'r': r, 'c': 0, 'z': r==0}
    if op == 'XOR': r = a^b; return {'r': r, 'c': 0, 'z': r==0}
    if op == 'INC': r = (a+1)&0xF; return {'r': r, 'c': 1 if a==15 else 0, 'z': r==0}
    if op == 'DEC': r = (a-1)&0xF; return {'r': r, 'c': 0 if a==0 else 1, 'z': r==0}
    if op == 'SHL': r = (a<<1)&0xF; return {'r': r, 'c': (a>>3)&1, 'z': r==0}
    if op == 'SHR': r = a>>1; return {'r': r, 'c': a&1, 'z': r==0}
    return {'r': 0, 'c': 0, 'z': True}

ISA = {
    'NOP': 0, 'ADD': 1, 'SUB': 2, 'AND': 3,
    'OR': 4, 'NOT': 5, 'XOR': 6, 'INC': 7,
    'DEC': 8, 'LOAD': 9, 'SHL': 10, 'SHR': 11,
    'JZ': 12, 'JMP': 13, 'JNZ': 14, 'HALT': 15,
}
OP_NAMES = {v: k for k, v in ISA.items()}
ALU_OPS = {1:'ADD',2:'SUB',3:'AND',4:'OR',5:'NOT',6:'XOR',7:'INC',8:'DEC',10:'SHL',11:'SHR'}

def run(program):
    acc, pc, cycle, trace, halted = 0, 0, 0, [], False
    while not halted and cycle < 64:
        if pc >= len(program): break
        opcode, op = program[pc]
        name = OP_NAMES.get(opcode, '???')
        next_pc = pc + 1

        if opcode == 15:
            halted = True; trace.append(f'{pc:02d} HALT')
        elif opcode == 9:
            acc = op & 0xF; trace.append(f'{pc:02d} LOAD {op} -> ACC={acc}')
        elif opcode == 12:
            if acc == 0: next_pc = op & 0xF; trace.append(f'{pc:02d} JZ {op} JUMP')
            else: trace.append(f'{pc:02d} JZ {op} (ACC={acc}, no jump)')
        elif opcode == 13:
            next_pc = op & 0xF; trace.append(f'{pc:02d} JMP {op}')
        elif opcode == 14:
            if acc != 0: next_pc = op & 0xF; trace.append(f'{pc:02d} JNZ {op} JUMP')
            else: trace.append(f'{pc:02d} JNZ {op} (ACC=0, no jump)')
        elif opcode in ALU_OPS:
            r = alu(ALU_OPS[opcode], acc, op & 0xF)
            acc = r['r']
            extra = f" C={r['c']} Z={1 if r['z'] else 0}"
            trace.append(f'{pc:02d} {ALU_OPS[opcode]} {op&0xF} -> ACC={acc}{extra}')
        else:
            trace.append(f'{pc:02d} {name}')

        pc = next_pc & 0xF; cycle += 1
    return acc, cycle, trace

if __name__ == '__main__':
    print("=" * 50)
    print("  4-BIT CPU SIMULATOR")
    print("=" * 50)

    tests = [
        ("3+5=8", [(9,3),(1,5),(15,0)], 8),
        ("6 AND 3 = 2", [(9,6),(3,3),(15,0)], 2),
        ("2 OR 8 = 10", [(9,2),(4,8),(15,0)], 10),
        ("NOT 5 = 10", [(9,5),(5,0),(15,0)], 10),
        ("7 XOR 3 = 4", [(9,7),(6,3),(15,0)], 4),
        ("INC 14 -> 15", [(9,14),(7,0),(15,0)], 15),
        ("Countdown 5->0", [(9,5),(8,0),(14,1),(15,0)], 0),
        ("Shift left 3<<1=6", [(9,3),(10,0),(15,0)], 6),
    ]

    all_ok = True
    for label, prog, expected in tests:
        acc, cycles, trace = run(prog)
        ok = acc == expected
        if not ok: all_ok = False
        print(f"\n[{label}] {'PASS' if ok else 'FAIL'}")
        for t in trace: print(f"  {t}")

    print(f"\n{'='*50}")
    print(f"  {'ALL TESTS PASSED' if all_ok else 'SOME TESTS FAILED'}")
    print(f"{'='*50}")

    print("\nISA (16 instructions, 4-bit opcode + 4-bit operand):")
    for code in range(16):
        print(f"  {code:04b} ({code:1X}): {OP_NAMES[code]:<5}", end="")
        if (code+1) % 4 == 0: print()

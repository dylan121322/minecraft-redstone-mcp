"""
riscv_synth.py — RISC-V combinational modules → yosys synthesize → hierarchical verify.
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'redstone3d'))
from yosys_frontend import compile_verilog
from regress import eval_netlist, verify_physical
from collections import Counter

WORKDIR = os.path.dirname(os.path.abspath(__file__))

def n(pb, port, i=0):
    b = pb[port][i]
    return f"n{b}" if not isinstance(b, str) else f"const_{b}"

def set_bus(iv, pb, port, val, w):
    for i in range(w): iv[n(pb, port, i)] = (val >> i) & 1

def get_bus(allv, pb, port, w):
    v = 0
    for i in range(w): v |= (allv.get(n(pb, port, i), 0) & 1) << i
    return v

def test_one(nl, pb, name, tvs):
    ok=0
    for tv in tvs:
        iv={}; [set_bus(iv,pb,p,v,w) for p,v,w in tv["in"]]
        for inet in nl["inputs"]:
            if inet not in iv: iv[inet] = 0
        allv = eval_netlist(nl, iv)
        matches=True
        for p,v,w in tv["out"]:
            if get_bus(allv,pb,p,w) != v: matches=False
        ok+=matches
    print(f"  {name}: {ok}/{len(tvs)}", flush=True)
    return ok==len(tvs)

def synth_one(file, top, tvs):
    t0=time.time()
    nl=compile_verilog(os.path.join(WORKDIR,file),top=top)
    dt=time.time()-t0
    ct=Counter(c["type"] for c in nl["cells"].values())
    print(f"  yosys: {len(nl['cells'])} gates {dt:.1f}s {dict(ct)}", flush=True)
    ok=test_one(nl, nl["port_bits"], top, tvs)
    return ok,nl

if __name__=="__main__":
    print("="*60)
    print("  RISC-V 8-bit Combinational → Redstone Synthesis")
    print("="*60)
    phys=verify_physical(verbose=False)
    print(f"  cell lib MCHPRS-verified: {'YES' if phys else 'NO'}\n")

    all_ok=True
    results={}

    # Control: 7-bit opcode → 7 ctrl signals
    ctrl=[  # (port,value,width) tuples
        {"in": [("opcode",0b0110011,7)], "out": [("alu_op",2,2),("reg_write",1,1),("branch",0,1),("mem_read",0,1)]},
        {"in": [("opcode",0b0000011,7)], "out": [("reg_write",1,1),("mem_read",1,1),("mem_to_reg",1,1),("alu_src",1,1),("branch",0,1)]},
        {"in": [("opcode",0b0100011,7)], "out": [("mem_write",1,1),("alu_src",1,1),("reg_write",0,1),("branch",0,1)]},
        {"in": [("opcode",0b1100011,7)], "out": [("branch",1,1),("alu_op",1,2)]},
        {"in": [("opcode",0b1101111,7)], "out": [("branch",1,1),("alu_op",3,2),("reg_write",1,1),("alu_src",1,1)]},
        {"in": [("opcode",0,7)],            "out": [("reg_write",0,1),("branch",0,1),("mem_read",0,1)]},
    ]
    ok,nl=synth_one("Control.v","Control",ctrl)
    all_ok&=ok; results["Control"]=nl

    # ALU_Control
    ac=[{"in": [("alu_op",0,2)],                "out": [("alu_control",2,4)]},
        {"in": [("alu_op",1,2)],                "out": [("alu_control",6,4)]},
        {"in": [("alu_op",2,2),("funct",0b0000000_000,10)], "out":[("alu_control",2,4)]},
        {"in": [("alu_op",2,2),("funct",0b0100000_000,10)], "out":[("alu_control",6,4)]},
        {"in": [("alu_op",2,2),("funct",0b0000000_111,10)], "out":[("alu_control",0,4)]},
        {"in": [("alu_op",2,2),("funct",0b0000000_110,10)], "out":[("alu_control",1,4)]},
        {"in": [("alu_op",3,2)],                "out": [("alu_control",12,4)]},
        ]
    ok,nl=synth_one("ALU_Control.v","ALU_Control",ac)
    all_ok&=ok; results["ALU_Control"]=nl

    # Mux_2to1 (8-bit)
    mux=[{"in":[("D0",0x55,8),("D1",0xAA,8),("S0",0,1)],"out":[("Y",0x55,8)]},
         {"in":[("D0",0x55,8),("D1",0xAA,8),("S0",1,1)],"out":[("Y",0xAA,8)]}]
    ok,nl=synth_one("Mux_2to1.v","Mux_2to1",mux)
    all_ok&=ok; results["Mux2to1"]=nl

    # Forwarding_Unit (2-bit RS for synth test)
    fwd=[{"in":[("reg_RS1",1,2),("reg_RS2",2,2),("ex_mem_reg_RD",1,2),("mem_wb_reg_RD",3,2),("ex_mem_regwrite",1,1),("mem_wb_regwrite",0,1)], "out":[("fwd_A",2,2),("fwd_B",0,2)]},
         {"in":[("reg_RS1",3,2),("reg_RS2",3,2),("ex_mem_reg_RD",0,2),("mem_wb_reg_RD",3,2),("ex_mem_regwrite",0,1),("mem_wb_regwrite",1,1)], "out":[("fwd_A",1,2),("fwd_B",1,2)]},
         {"in":[("reg_RS1",1,2),("reg_RS2",2,2),("ex_mem_reg_RD",0,2),("mem_wb_reg_RD",0,2),("ex_mem_regwrite",1,1),("mem_wb_regwrite",1,1)], "out":[("fwd_A",0,2),("fwd_B",0,2)]}]
    ok,nl=synth_one("Forwarding_Unit.v","Forwarding_Unit",fwd)
    all_ok&=ok; results["Forwarding"]=nl

    # Imm_Gen: R-type (opcode=0110011) → imm=0, I-type (ld 0000011) → imm[31:20], UJ-type (jal 1101111) → imm[31:20]
    r_type = 0x002081B3;  # R-type: imm=0
    i_type = 0xABC00103;  # I-type: imm = inst[31:20] = 0xABC
    uj_type= 0x004000EF;  # JAL: PC+0x004 (jump 0x1), imm=0x001
    ig=[{"in":[("instruction",r_type,32)],  "out":[("immediate",0,12)]},
        {"in":[("instruction",i_type,32)],  "out":[("immediate",(i_type>>20)&0xFFF,12)]},
        {"in":[("instruction",uj_type,32)], "out":[("immediate",(uj_type>>20)&0xFFF,12)]},
        ]
    ok,nl=synth_one("Imm_Gen.v","Imm_Gen",ig)
    all_ok&=ok; results["ImmGen"]=nl

    print("\n"+"="*60)
    for n,r in results.items():
        ct=Counter(c["type"] for c in r["cells"].values())
        print(f"  {n}: {len(r['cells'])} gates {dict(ct)}")
    print(f"  {'ALL COMB MODULES PASSED' if all_ok else 'SOME FAILED'}")
    print("="*60)

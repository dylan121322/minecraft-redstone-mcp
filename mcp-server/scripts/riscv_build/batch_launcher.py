"""
batch_launcher.py — spawn one INDEPENDENT python process per config (no
process pools: one crash loses only its own config) and wait. Restart-safe:
configs whose result_*.json exists are skipped by run_one_config.py.
"""
import os, subprocess, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
# Windows 端 python 解释器路径，通过环境变量提供；无则使用占位符（运行前必须设置）
PY = os.environ.get("WIN_PYTHON", r"<path-to-windows-python.exe>")

# support-safe era sweep: the y2 express lanes can no longer pass over via
# interiors (in-game the wire pops), so the sweep favours taller stacks where
# the lanes sit on their own level. ROUNDS bumped to 40 for the tighter space.
T, R, D, P, L, F = (3.0, 12.0, 10.0, 128.0, 4, 12.0)
CONFIGS = [
    (T, R, D, P, L, F),      # 0 baseline L4 fm12
    (T, R, D, P, 5, F),      # 1 L5
    (T, R, D, P, 6, F),      # 2 L6
    (T, R, D, P, L, 6),      # 3 L4 fm6
    (T, R, D, P, L, 8),      # 4 L4 fm8
    (T, R, D, P, L, 16),     # 5 L4 fm16
    (T, R, D, P, L, 20),     # 6 L4 fm20
    (T, R, D, P, 5, 8),      # 7 L5 fm8
    (T, R, D, P, 5, 16),     # 8 L5 fm16
    (0, R, D, P, L, F),      # 9 L4 turn0
    (6, R, D, P, L, F),      # 10 L4 turn6
    (T, R, D, 64, L, F),     # 11 L4 pcap64
    (T, R, D, 256, L, F),    # 12 L4 pcap256
    (T, 16, 14, P, L, F),    # 13 L4 expensive vias
    (T, 8, 6, P, L, F),      # 14 L4 cheap vias
    (T, R, D, 64, 5, F),     # 15 L5 pcap64
    (0, R, D, P, 5, 8),      # 16 L5 turn0 fm8
    (T, R, D, 256, 5, F),    # 17 L5 pcap256
    (T, 16, 14, P, 5, F),    # 18 L5 expensive vias
    (T, R, D, P, 6, 8),      # 19 L6 fm8
]
ROUNDS = 40


def main():
    t0 = time.time()
    procs = []
    for i, (turn, rise, drop, pcap, layers, fmult) in enumerate(CONFIGS):
        if os.path.exists(os.path.join(BASE, f"result_{i}.json")):
            print(f"#{i} already done, skip", flush=True)
            continue
        log = open(os.path.join(BASE, f"cfg_{i}.log"), "a")
        args = [PY, os.path.join(BASE, "run_one_config.py"), str(i),
                str(turn), str(rise), str(drop), str(pcap), str(layers),
                str(fmult), str(ROUNDS)]
        p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                             cwd=BASE)
        procs.append((i, p))
        print(f"started #{i} pid={p.pid}", flush=True)
    print(f"{len(procs)} configs running, wall {time.time()-t0:.0f}s",
          flush=True)
    while procs:
        for i, p in list(procs):
            rc = p.poll()
            if rc is not None:
                procs.remove((i, p))
                print(f"#{i} exited rc={rc} "
                      f"done={os.path.exists(os.path.join(BASE, f'result_{i}.json'))}",
                      flush=True)
        time.sleep(10)
    with open(os.path.join(BASE, "batch_done.txt"), "w") as fh:
        fh.write(time.asctime())
    print(f"ALL DONE, wall {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

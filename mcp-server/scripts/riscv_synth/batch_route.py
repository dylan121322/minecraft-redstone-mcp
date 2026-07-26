"""Launch all RISC-V module routing jobs in PARALLEL processes.
Each module runs serial PathFinder (proven to converge); running all 6
concurrently saturates the 32-thread CPU. Big modules get more iterations.

Usage: py batch_route.py
"""
import subprocess, sys, os, time

HERE = os.path.dirname(os.path.abspath(__file__))

# (module, netlist_json, max_iters) — big modules need more iters
JOBS = [
    ("Control",     "nl_Control.json",     200),
    ("Mux",         "nl_Mux.json",         200),
    ("ALU_Control", "nl_ALU_Control.json", 300),
    ("ImmGen",      "nl_ImmGen.json",      300),
    ("Forwarding",  "nl_Forwarding.json",  600),
    ("ALU",         "nl_ALU.json",         800),
]

def main():
    procs = []
    for name, nlj, iters in JOBS:
        log = open(os.path.join(HERE, f"{name}_batch.log"), "w")
        p = subprocess.Popen(
            [sys.executable, "-u", os.path.join(HERE, "route_job.py"), name, nlj, str(iters)],
            stdout=log, stderr=subprocess.STDOUT, cwd=HERE)
        procs.append((name, p, log))
        print(f"launched {name} (pid {p.pid}, {iters} iters)", flush=True)

    print(f"\n{len(procs)} jobs running in parallel across CPU cores.", flush=True)
    # poll
    t0 = time.time()
    done = set()
    while len(done) < len(procs):
        time.sleep(15)
        for name, p, log in procs:
            if name in done: continue
            if p.poll() is not None:
                done.add(name)
                print(f"[{time.time()-t0:.0f}s] {name} FINISHED (rc={p.returncode})", flush=True)
        remaining = [n for n, _, _ in procs if n not in done]
        if remaining:
            print(f"[{time.time()-t0:.0f}s] still running: {remaining}", flush=True)

    print("\nALL JOBS DONE. Results:", flush=True)
    for name, _, log in procs:
        log.close()
        rj = os.path.join(HERE, f"{name}_route.json")
        if os.path.exists(rj):
            import json
            r = json.load(open(rj))
            print(f"  {name}: {r['status']} {r['gates']}g {r['wires']}w "
                  f"shared={r['shared']} {r['time_s']}s", flush=True)

if __name__ == "__main__":
    main()

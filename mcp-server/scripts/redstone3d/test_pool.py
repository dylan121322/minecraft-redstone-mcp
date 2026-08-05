"""test_pool.py — minimal reproduction of the Windows ProcessPool failure.
Runs _trial through a 2-worker pool and prints the real exception, since the
32-worker launch died with an empty log."""
import sys, os, traceback
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from concurrent.futures import ProcessPoolExecutor, as_completed
import solve_parallel as sp


def main():
    jobs = [("alu1", (), 2), ("alu1", ("n2",), 2)]
    print(f"submitting {len(jobs)} jobs to a 2-worker pool")
    with ProcessPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(sp._trial, j): j for j in jobs}
        for f in as_completed(futs):
            j = futs[f]
            try:
                print("OK", j, f.result())
            except Exception:
                print("FAILED", j)
                traceback.print_exc()


if __name__ == "__main__":
    main()

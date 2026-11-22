#!/usr/bin/env python3
import argparse
import json
import math
import multiprocessing
import os
import signal
import statistics
import time

running = True

def handle_signal(signum, frame):
    global running
    running = False

def run_worker(duration, warmup, cpu_only, wid, out_q):
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    tmp_file = f"/tmp/host_ground_truth_{os.getpid()}_{wid}.dat"
    payload = b"H" * (256 * 1024)
    latencies_ms = []
    t_begin = time.perf_counter()

    try:
        while running and (time.perf_counter() - t_begin) < (warmup + duration):
            t0 = time.perf_counter()
            acc = 0.0
            iters = 150000 if cpu_only else 50000
            for i in range(1, iters):
                acc += math.sqrt(i * 3.14159)
            if not cpu_only:
                with open(tmp_file, "wb") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
            now = time.perf_counter()
            if (now - t_begin) >= warmup:
                latencies_ms.append((now - t0) * 1000.0)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    elapsed = max(0.001, (time.perf_counter() - t_begin) - warmup)
    out_q.put((latencies_ms, elapsed))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--warmup", type=float, default=0.0)
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    q = multiprocessing.Queue()
    procs = []
    for wid in range(max(1, args.workers)):
        p = multiprocessing.Process(
            target=run_worker,
            args=(args.duration, args.warmup, args.cpu_only, wid, q),
        )
        p.start()
        procs.append(p)

    def forward_sig(signum, frame):
        for p in procs:
            if p.is_alive():
                p.terminate()

    signal.signal(signal.SIGTERM, forward_sig)
    signal.signal(signal.SIGINT, forward_sig)

    all_lat = []
    total_ops = 0.0
    max_elapsed = 0.0
    for _ in procs:
        lats, el = q.get()
        all_lat.extend(lats)
        total_ops += len(lats) / el
        max_elapsed = max(max_elapsed, el)
    for p in procs:
        p.join()

    result = {
        "workers": max(1, args.workers),
        "iterations": len(all_lat),
        "elapsed_sec": round(max_elapsed, 3),
        "mean_ms": round(statistics.mean(all_lat), 2) if all_lat else 0.0,
        "median_ms": round(statistics.median(all_lat), 2) if all_lat else 0.0,
        "max_ms": round(max(all_lat), 2) if all_lat else 0.0,
        "throughput_ops_sec": round(total_ops, 2),
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    main()

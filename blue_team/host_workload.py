#!/usr/bin/env python3
import argparse
import json
import math
import os
import signal
import statistics
import time

running = True

def handle_signal(signum, frame):
    global running
    running = False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--warmup", type=float, default=0.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    tmp_file = f"/tmp/host_ground_truth_{os.getpid()}.dat"
    payload = b"H" * (256 * 1024)
    latencies_ms = []
    t_begin = time.perf_counter()

    try:
        while running and (time.perf_counter() - t_begin) < (args.warmup + args.duration):
            t0 = time.perf_counter()
            acc = 0.0
            for i in range(1, 50000):
                acc += math.sqrt(i * 3.14159)
            with open(tmp_file, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            now = time.perf_counter()
            if (now - t_begin) >= args.warmup:
                latencies_ms.append((now - t0) * 1000.0)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    elapsed = max(0.001, (time.perf_counter() - t_begin) - args.warmup)
    result = {
        "iterations": len(latencies_ms),
        "elapsed_sec": round(elapsed, 3),
        "mean_ms": round(statistics.mean(latencies_ms), 2) if latencies_ms else 0.0,
        "median_ms": round(statistics.median(latencies_ms), 2) if latencies_ms else 0.0,
        "max_ms": round(max(latencies_ms), 2) if latencies_ms else 0.0,
        "throughput_ops_sec": round(len(latencies_ms) / elapsed, 2) if latencies_ms else 0.0,
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    main()

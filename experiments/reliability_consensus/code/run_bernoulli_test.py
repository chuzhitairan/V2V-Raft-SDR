#!/usr/bin/env python3
"""
 count  p Run

:
  python3 run_bernoulli_test.py --n 1000 --p 0.8
  python3 run_bernoulli_test.py --n 10000 --p 0.7 --reps 50 --seed 42
"""
import argparse
import time
import statistics

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False


def run_once(n, p):
    if _HAS_NUMPY:
        count = int(np.random.binomial(n, p))
    else:
        import random
        count = 0
        for _ in range(n):
            if random.random() < p:
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description='Run')
    parser.add_argument('--n', type=int, required=True, help=' count  ( count )')
    parser.add_argument('--p', type=float, required=True, help=' p (0-1)')
    parser.add_argument('--reps', type=int, default=1, help=' count 1')
    parser.add_argument('--seed', type=int, default=None, help='')
    args = parser.parse_args()

    if args.seed is not None:
        if _HAS_NUMPY:
            np.random.seed(args.seed)
        else:
            import random
            random.seed(args.seed)

    freqs = []
    start = time.time()
    for i in range(1, args.reps + 1):
        cnt = run_once(args.n, args.p)
        freq = cnt / args.n if args.n > 0 else 0.0
        freqs.append(freq)
        print(f"Rep {i:3d}: count={cnt}/{args.n}  frequency={freq:.6f}")

    elapsed = time.time() - start
    if args.reps > 1:
        mean = statistics.mean(freqs)
        stdev = statistics.pstdev(freqs)
        print(f"\nSummary over {args.reps} reps:")
        print(f"  mean frequency = {mean:.6f}")
        print(f"  std dev (population) = {stdev:.6f}")
    print(f"Elapsed: {elapsed:.3f}s")


if __name__ == '__main__':
    main()

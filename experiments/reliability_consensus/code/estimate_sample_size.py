#!/usr/bin/env python3
"""


 p () tol confidence
 count  N  |mean - p| <= tol  confidence

 N


    python3 estimate_sample_size.py --p 0.8 --tol 0.01 --confidence 0.95 --reps 1000

 N  N 
"""
import sys
import argparse
import time

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    import random
    _HAS_NUMPY = False


def fraction_within_tol(p, N, reps):
    """ reps  count  p  <= tol  tol"""
    raise NotImplementedError


def _fraction_numpy(p, N, reps, tol):
    samples = np.random.binomial(N, p, size=reps)
    means = samples / N
    return float(np.mean(np.abs(means - p) <= tol))


def _fraction_pure_python(p, N, reps, tol):
    cnt = 0
    import random
    for _ in range(reps):
        s = 0
        for _ in range(N):
            if random.random() < p:
                s += 1
        mean = s / N
        if abs(mean - p) <= tol:
            cnt += 1
    return cnt / reps


def find_minimum_N(p, tol=0.01, confidence=0.95, reps=1000, max_N=200000):
    """ +   N

     (N_found, fraction_at_N)
    """
    if _HAS_NUMPY:
        frac_fn = _fraction_numpy
    else:
        frac_fn = _fraction_pure_python

    N = 10
    prev_N = 1
    start = time.time()
    while N <= max_N:
        frac = frac_fn(p, N, reps, tol)
        print(f"Test  N={N:7d}  -> ={frac:.4f}")
        if frac >= confidence:
            lo = max(prev_N, 1)
            hi = N
            while lo + 1 < hi:
                mid = (lo + hi) // 2
                frac_mid = frac_fn(p, mid, reps, tol)
                print(f"   mid={mid:7d} -> {frac_mid:.4f}")
                if frac_mid >= confidence:
                    hi = mid
                else:
                    lo = mid
            frac_hi = frac_fn(p, hi, reps, tol)
            elapsed = time.time() - start
            return hi, frac_hi, elapsed
        prev_N = N
        N *= 2
    elapsed = time.time() - start
    return None, None, elapsed


def main():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--p', type=float, default=0.8, help=' p (0-1)')
    parser.add_argument('--tol', type=float, default=0.01, help='')
    parser.add_argument('--confidence', type=float, default=0.95, help=' ()')
    parser.add_argument('--reps', type=int, default=1000, help=' N  count  ( count )')
    parser.add_argument('--max-n', type=int, default=200000, help='')
    parser.add_argument('--seed', type=int, default=None, help='')
    args = parser.parse_args()

    if args.seed is not None:
        if _HAS_NUMPY:
            np.random.seed(args.seed)
        else:
            import random
            random.seed(args.seed)

    print(f": p={args.p}, tol={args.tol}, confidence={args.confidence}, reps={args.reps}")
    N_found, frac, elapsed = find_minimum_N(args.p, tol=args.tol, confidence=args.confidence,
                                           reps=args.reps, max_N=args.max_n)
    if N_found is None:
        print(f" max_n={args.max_n}  N (Time  {elapsed:.1f}s)")
    else:
        print(f" N = {N_found}  N ={frac:.4f} (Time  {elapsed:.1f}s)")


if __name__ == '__main__':
    main()

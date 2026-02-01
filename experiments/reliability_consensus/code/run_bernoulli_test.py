#!/usr/bin/env python3
"""
简单脚本：按输入的实验次数和阈值 p 运行伯努利试验，输出实际频率。

用法示例:
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
    parser = argparse.ArgumentParser(description='运行伯努利试验并报告实际频率')
    parser.add_argument('--n', type=int, required=True, help='每次试验的样本数 (实验次数)')
    parser.add_argument('--p', type=float, required=True, help='判定阈值 p (0-1)')
    parser.add_argument('--reps', type=int, default=1, help='重复独立实验次数，默认1')
    parser.add_argument('--seed', type=int, default=None, help='可选随机种子，便于复现')
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

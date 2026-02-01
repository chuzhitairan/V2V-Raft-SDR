#!/usr/bin/env python3
"""
估计伯努利试验所需样本量的脚本

策略：对给定的 p (真实期望)、误差容忍 tol、置信度 confidence，
通过蒙特卡洛判断当试验次数为 N 时，样本均值与期望 |mean - p| <= tol 的比例是否达到 confidence。

搜索策略：倍增搜索找到上界后，二分搜索最小满足条件的 N。

用法示例：
    python3 estimate_sample_size.py --p 0.8 --tol 0.01 --confidence 0.95 --reps 1000

脚本会打印找到的最小 N 以及在该 N 下的实际覆盖率。
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
    """返回在 reps 次重复试验中，样本均值与 p 的绝对误差 <= tol 的比例（使用闭包传入 tol）。"""
    # 这里将由外部提供 tol via closure binding
    raise NotImplementedError


def _fraction_numpy(p, N, reps, tol):
    # 使用 numpy 向量化采样
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
    """倍增 + 二分 搜索满足条件的最小 N。

    返回 (N_found, fraction_at_N)
    """
    if _HAS_NUMPY:
        frac_fn = _fraction_numpy
    else:
        frac_fn = _fraction_pure_python

    # 快速检查 small N
    N = 10
    prev_N = 1
    start = time.time()
    while N <= max_N:
        frac = frac_fn(p, N, reps, tol)
        print(f"测试 N={N:7d}  -> 覆盖率={frac:.4f}")
        if frac >= confidence:
            # 找到上界：prev_N < N 满足条件的最小 N 在 (prev_N, N]
            lo = max(prev_N, 1)
            hi = N
            # 二分搜索
            while lo + 1 < hi:
                mid = (lo + hi) // 2
                frac_mid = frac_fn(p, mid, reps, tol)
                print(f"  二分 mid={mid:7d} -> {frac_mid:.4f}")
                if frac_mid >= confidence:
                    hi = mid
                else:
                    lo = mid
            frac_hi = frac_fn(p, hi, reps, tol)
            elapsed = time.time() - start
            return hi, frac_hi, elapsed
        prev_N = N
        N *= 2
    # 未在 max_N 内找到
    elapsed = time.time() - start
    return None, None, elapsed


def main():
    parser = argparse.ArgumentParser(description='估计伯努利样本量')
    parser.add_argument('--p', type=float, default=0.8, help='真实概率 p (0-1)')
    parser.add_argument('--tol', type=float, default=0.01, help='允许的均值偏差')
    parser.add_argument('--confidence', type=float, default=0.95, help='所需覆盖率 (置信度)')
    parser.add_argument('--reps', type=int, default=1000, help='每个 N 的重复次数 (蒙特卡洛次数)')
    parser.add_argument('--max-n', type=int, default=200000, help='搜索的最大样本数')
    parser.add_argument('--seed', type=int, default=None, help='可选随机种子（便于复现）')
    args = parser.parse_args()

    if args.seed is not None:
        if _HAS_NUMPY:
            np.random.seed(args.seed)
        else:
            import random
            random.seed(args.seed)

    print(f"参数: p={args.p}, tol={args.tol}, confidence={args.confidence}, reps={args.reps}")
    N_found, frac, elapsed = find_minimum_N(args.p, tol=args.tol, confidence=args.confidence,
                                           reps=args.reps, max_N=args.max_n)
    if N_found is None:
        print(f"在 max_n={args.max_n} 内未找到满足条件的 N (耗时 {elapsed:.1f}s)")
    else:
        print(f"找到最小 N = {N_found} 在此 N 下覆盖率={frac:.4f} (耗时 {elapsed:.1f}s)")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
可靠性共识实验 - 纯软件仿真版
================================

完全复制 raft_leader_reliability.py 中 collect_weighted_votes_debug 的逻辑，
用于验证算法正确性。

关键代码路径：
1. Follower 投票：votes_received[node_id] = success (伯努利试验)
2. Follower SNR：self.peers[node_id].get('snr', 0.0)
3. Leader 投票：random.random() < self.current_p_node
4. Leader SNR：max(Follower SNR) + 2.0
5. 权重计算：1.0 + 0.001 * (snr - snr_min) / snr_range
6. 判定：W_yes > W_no
"""

import random
import statistics
import argparse
from typing import List, Dict, Tuple
from dataclasses import dataclass


def collect_weighted_votes_simulation(
    votes_received: Dict[int, bool],  # {node_id: success}
    peers: Dict[int, dict],           # {node_id: {'snr': float}}
    n: int,                           # 系统规模
    leader_node_id: int,              # Leader 的 node_id
    current_p_node: float,            # 当前可信度
    target_snr: float = 18.0          # 默认目标 SNR
) -> Tuple[float, float, bool, str]:
    """
    完全复制 raft_leader_reliability.py 中的 collect_weighted_votes_debug 逻辑
    """
    # 1. 收集 Follower 的投票
    # 注意：Follower ID 是 1~n 中排除 Leader 的节点
    follower_ids = [i for i in range(1, n + 1) if i != leader_node_id]
    voters = []
    for node_id, success in votes_received.items():
        if node_id in follower_ids:
            snr = 0.0
            if node_id in peers:
                snr = peers[node_id].get('snr', 0.0)
            voters.append({'id': node_id, 'success': success, 'snr': snr})
    
    # 2. Leader 投票 (也做伯努利试验)
    # 使用特殊 ID = -1 以避免与 Follower ID 冲突
    max_follower_snr = max((v['snr'] for v in voters), default=target_snr)
    leader_virtual_snr = max_follower_snr + 2.0
    leader_vote = random.random() < current_p_node
    voters.append({'id': -1, 'success': leader_vote, 'snr': leader_virtual_snr, 'is_leader': True})
    
    # 3. 计算 SNR 权重
    snr_values = [v['snr'] for v in voters]
    snr_min = min(snr_values)
    snr_max = max(snr_values)
    snr_range = snr_max - snr_min if snr_max > snr_min else 1.0
    
    for v in voters:
        v['weight'] = 1.0 + 0.001 * (v['snr'] - snr_min) / snr_range
    
    # 4. 统计加权投票
    W_yes = sum(v['weight'] for v in voters if v['success'])
    W_no = sum(v['weight'] for v in voters if not v['success'])
    W_total = W_yes + W_no
    
    # 5. 判定：加权赞成 > 加权反对
    consensus_reached = W_yes > W_no
    
    # 6. 生成详细信息字符串
    follower_count = len([v for v in voters if v.get('id', 0) in follower_ids])
    no_reply = len(follower_ids) - follower_count
    
    leader_icon = "✓" if leader_vote else "✗"
    
    follower_vote_strs = []
    for fid in follower_ids:
        v = next((x for x in voters if x.get('id') == fid and not x.get('is_leader')), None)
        if v is None:
            follower_vote_strs.append(f"F{fid}:-")
        elif v['success']:
            follower_vote_strs.append(f"F{fid}:✓")
        else:
            follower_vote_strs.append(f"F{fid}:✗")
    
    yes_count = sum(1 for v in voters if v['success'])
    no_count = sum(1 for v in voters if not v['success'])
    
    result_icon = "✓共识" if consensus_reached else "✗未达"
    
    details = (f"赞成:{yes_count} 反对:{no_count} 未回复:{no_reply} | "
              f"L:{leader_icon} {' '.join(follower_vote_strs)} | "
              f"W_yes={W_yes:.3f}>W_no={W_no:.3f}? {result_icon}")
    
    return W_yes, W_total, consensus_reached, details


def simulate_one_round(
    n: int,                    # 系统规模（包含 Leader）
    leader_node_id: int,       # Leader 的 node_id
    p_node: float,             # 节点可信度
    follower_snr_base: float = 18.0,  # Follower 基础 SNR
    follower_snr_spread: float = 2.0, # Follower SNR 随机波动范围
    packet_loss_rate: float = 0.0,    # Follower 响应丢包率
    snr_missing: bool = False         # 模拟 SNR 没传回来（全为 0）
) -> Tuple[bool, str]:
    """
    模拟一轮完整的投票流程
    
    这个函数模拟：
    1. Leader 发送投票请求
    2. 每个 Follower 以 p_node 概率投赞成票，以 packet_loss_rate 概率丢失响应
    3. Leader 收集投票并判定
    """
    # 模拟 votes_received 和 peers 字典
    votes_received: Dict[int, bool] = {}
    peers: Dict[int, dict] = {}
    
    # Follower ID 是 1~n 中排除 Leader 的节点
    follower_ids = [i for i in range(1, n + 1) if i != leader_node_id]
    
    for fid in follower_ids:
        # 模拟丢包
        if random.random() < packet_loss_rate:
            continue  # 这个 Follower 的响应丢失了
        
        # 伯努利投票
        vote = random.random() < p_node
        votes_received[fid] = vote
        
        # 模拟 Follower 的 SNR（在响应中携带）
        if snr_missing:
            # 模拟 SNR 没传回来的 bug
            peers[fid] = {'snr': 0.0}
        else:
            snr = follower_snr_base + random.uniform(-follower_snr_spread, follower_snr_spread)
            peers[fid] = {'snr': snr}
    
    # 调用与 raft_leader_reliability.py 完全相同的投票收集逻辑
    W_yes, W_total, consensus, details = collect_weighted_votes_simulation(
        votes_received=votes_received,
        peers=peers,
        n=n,
        leader_node_id=leader_node_id,
        current_p_node=p_node,
        target_snr=follower_snr_base
    )
    
    return consensus, details


def run_experiment(
    n: int,
    leader_node_id: int,
    p_node: float,
    rounds: int,
    packet_loss_rate: float = 0.0,
    snr_missing: bool = False,
    verbose: bool = False
) -> float:
    """运行实验，返回 P_sys"""
    success_count = 0
    
    for k in range(rounds):
        consensus, details = simulate_one_round(
            n=n,
            leader_node_id=leader_node_id,
            p_node=p_node,
            packet_loss_rate=packet_loss_rate,
            snr_missing=snr_missing
        )
        
        if consensus:
            success_count += 1
        
        if verbose and (k < 5 or (k + 1) % 10 == 0):
            print(f"  轮 {k+1:3d}: {details}")
    
    return success_count / rounds


def theoretical_p_sys(n: int, p: float) -> float:
    """
    计算理论 P_sys
    
    n 个节点，规则 W_yes > W_no，Leader 权重略高。
    平票时由 Leader 决定。
    """
    from math import comb
    
    P_sys = 0.0
    for k in range(n + 1):
        prob_k = comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
        
        if k > n - k:
            P_sys += prob_k
        elif k == n - k:
            # 平票时 Leader 决定
            P_sys += prob_k * (k / n)
    
    return P_sys


def main():
    parser = argparse.ArgumentParser(description="可靠性共识实验 - 软件仿真（复用真实代码逻辑）")
    parser.add_argument("--n", type=int, default=4, help="节点数（包含 Leader）")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader 的 node_id")
    parser.add_argument("--p-levels", type=str, default="0.6,0.7,0.8,0.9",
                        help="p_node 等级（逗号分隔）")
    parser.add_argument("--rounds", type=int, default=1000, help="每组测试轮数")
    parser.add_argument("--packet-loss", type=float, default=0.0, 
                        help="Follower 响应丢包率（0.0-1.0）")
    parser.add_argument("--no-snr", action="store_true",
                        help="模拟 SNR 没传回来的 bug（所有权重为 1.0）")
    parser.add_argument("--verbose", action="store_true", help="显示详细投票过程")
    args = parser.parse_args()
    
    p_levels = [float(x) for x in args.p_levels.split(',')]
    n = args.n
    leader_id = args.leader_id
    rounds = args.rounds
    packet_loss = args.packet_loss
    snr_missing = args.no_snr
    
    # 计算实际 Follower 数量
    follower_ids = [i for i in range(1, n + 1) if i != leader_id]
    num_followers = len(follower_ids)
    
    print("=" * 70)
    print("🔬 可靠性共识实验 - 软件仿真（复用真实代码逻辑）")
    print("=" * 70)
    print(f"\n📋 实验参数:")
    print(f"   ├─ 节点数 n:       {n}")
    print(f"   ├─ Leader ID:      {leader_id}")
    print(f"   ├─ Follower IDs:   {follower_ids}（共 {num_followers} 个）")
    print(f"   ├─ p_node 等级:    {p_levels}")
    print(f"   ├─ 每组测试轮数:   {rounds}")
    print(f"   ├─ 丢包率:         {packet_loss*100:.1f}%")
    print(f"   ├─ SNR 缺失:       {'是（模拟 bug）' if snr_missing else '否'}")
    print(f"   └─ 投票规则:       W_yes > W_no（加权，Leader权重略高）")
    
    print("\n" + "=" * 70)
    print("📊 理论分析 vs 仿真结果")
    print("=" * 70)
    print(f"\n{'p_node':<10} {'理论P_sys':<12} {'仿真P_sys':<12} {'误差':<10}")
    print("-" * 50)
    
    results = []
    
    for p in p_levels:
        # 理论值（假设无丢包）
        # 实际投票人数 = 1 (Leader) + num_followers
        theory = theoretical_p_sys(1 + num_followers, p)
        
        if args.verbose:
            print(f"\n--- p_node = {p} ---")
        
        P_sys = run_experiment(
            n=n,
            leader_node_id=leader_id,
            p_node=p,
            rounds=rounds,
            packet_loss_rate=packet_loss,
            snr_missing=snr_missing,
            verbose=args.verbose
        )
        
        error = P_sys - theory
        error_pct = abs(error / theory) * 100 if theory > 0 else 0
        
        results.append({
            'p_node': p,
            'theory': theory,
            'simulated': P_sys,
            'error': error,
            'error_pct': error_pct
        })
        
        print(f"{p:<10.2f} {theory:<12.4f} {P_sys:<12.4f} {error:+.4f} ({error_pct:.1f}%)")
    
    print("\n" + "=" * 70)
    print("📈 结论")
    print("=" * 70)
    
    avg_error = statistics.mean(r['error_pct'] for r in results)
    print(f"\n   平均误差: {avg_error:.2f}%")
    
    if avg_error < 5:
        print("   ✅ 仿真结果与理论值吻合良好")
    else:
        print("   ⚠️ 仿真结果与理论值有较大偏差，请检查算法实现")


if __name__ == "__main__":
    main()

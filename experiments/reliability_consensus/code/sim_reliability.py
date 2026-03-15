#!/usr/bin/env python3
"""
 - 
================================

 raft_leader_reliability.py  collect_weighted_votes_debug 



1. Follower Vote votes_received[node_id] = success ()
2. Follower SNRself.peers[node_id].get('snr', 0.0)
3. Leader Vote random.random() < self.current_p_node
4. Leader SNRmax(Follower SNR) + 2.0
5. 1.0 + 0.001 * (snr - snr_min) / snr_range
6. W_yes > W_no
"""

import random
import statistics
import argparse
from typing import List, Dict, Tuple
from dataclasses import dataclass


def collect_weighted_votes_simulation(
    votes_received: Dict[int, bool],  # {node_id: success}
    peers: Dict[int, dict],           # {node_id: {'snr': float}}
    n: int,
    leader_node_id: int,
    current_p_node: float,
    target_snr: float = 18.0
) -> Tuple[float, float, bool, str]:
    """
     raft_leader_reliability.py  collect_weighted_votes_debug 
    """
    follower_ids = [i for i in range(1, n + 1) if i != leader_node_id]
    voters = []
    for node_id, success in votes_received.items():
        if node_id in follower_ids:
            snr = 0.0
            if node_id in peers:
                snr = peers[node_id].get('snr', 0.0)
            voters.append({'id': node_id, 'success': success, 'snr': snr})
    
    max_follower_snr = max((v['snr'] for v in voters), default=target_snr)
    leader_virtual_snr = max_follower_snr + 2.0
    leader_vote = random.random() < current_p_node
    voters.append({'id': -1, 'success': leader_vote, 'snr': leader_virtual_snr, 'is_leader': True})
    
    snr_values = [v['snr'] for v in voters]
    snr_min = min(snr_values)
    snr_max = max(snr_values)
    snr_range = snr_max - snr_min if snr_max > snr_min else 1.0
    
    for v in voters:
        v['weight'] = 1.0 + 0.001 * (v['snr'] - snr_min) / snr_range
    
    W_yes = sum(v['weight'] for v in voters if v['success'])
    W_no = sum(v['weight'] for v in voters if not v['success'])
    W_total = W_yes + W_no
    
    consensus_reached = W_yes > W_no
    
    follower_count = len([v for v in voters if v.get('id', 0) in follower_ids])
    no_reply = len(follower_ids) - follower_count
    
    leader_icon = "" if leader_vote else ""
    
    follower_vote_strs = []
    for fid in follower_ids:
        v = next((x for x in voters if x.get('id') == fid and not x.get('is_leader')), None)
        if v is None:
            follower_vote_strs.append(f"F{fid}:-")
        elif v['success']:
            follower_vote_strs.append(f"F{fid}:")
        else:
            follower_vote_strs.append(f"F{fid}:")
    
    yes_count = sum(1 for v in voters if v['success'])
    no_count = sum(1 for v in voters if not v['success'])
    
    result_icon = "" if consensus_reached else ""
    
    details = (f"Approve :{yes_count} :{no_count} :{no_reply} | "
              f"L:{leader_icon} {' '.join(follower_vote_strs)} | "
              f"W_yes={W_yes:.3f}>W_no={W_no:.3f}? {result_icon}")
    
    return W_yes, W_total, consensus_reached, details


def simulate_one_round(
    n: int,
    leader_node_id: int,
    p_node: float,
    follower_snr_base: float = 18.0,
    follower_snr_spread: float = 2.0,
    packet_loss_rate: float = 0.0,
    snr_missing: bool = False
) -> Tuple[bool, str]:
    """
    Simulate Vote 
    
    Simulate 
    1. Leader Send Vote 
    2.  Follower  p_node Approve  packet_loss_rate 
    3. Leader Vote 
    """
    votes_received: Dict[int, bool] = {}
    peers: Dict[int, dict] = {}
    
    follower_ids = [i for i in range(1, n + 1) if i != leader_node_id]
    
    for fid in follower_ids:
        if random.random() < packet_loss_rate:
            continue
        
        vote = random.random() < p_node
        votes_received[fid] = vote
        
        if snr_missing:
            peers[fid] = {'snr': 0.0}
        else:
            snr = follower_snr_base + random.uniform(-follower_snr_spread, follower_snr_spread)
            peers[fid] = {'snr': snr}
    
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
    """Run P_sys"""
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
            print(f"   {k+1:3d}: {details}")
    
    return success_count / rounds


def theoretical_p_sys(n: int, p: float) -> float:
    """
     P_sys
    
    n Node  W_yes > W_noLeader 
     Leader 
    """
    from math import comb
    
    P_sys = 0.0
    for k in range(n + 1):
        prob_k = comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
        
        if k > n - k:
            P_sys += prob_k
        elif k == n - k:
            P_sys += prob_k * (k / n)
    
    return P_sys


def main():
    parser = argparse.ArgumentParser(description=" - ")
    parser.add_argument("--n", type=int, default=4, help="Node  Leader")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader  node_id")
    parser.add_argument("--p-levels", type=str, default="0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90",
                        help="p_node ")
    parser.add_argument("--rounds", type=int, default=1000, help="Test ")
    parser.add_argument("--packet-loss", type=float, default=0.0, 
                        help="Follower Loss Rate 0.0-1.0")
    parser.add_argument("--no-snr", action="store_true",
                        help="Simulate  SNR  bug 1.0")
    parser.add_argument("--verbose", action="store_true", help="Vote ")
    args = parser.parse_args()
    
    p_levels = [float(x) for x in args.p_levels.split(',')]
    n = args.n
    leader_id = args.leader_id
    rounds = args.rounds
    packet_loss = args.packet_loss
    snr_missing = args.no_snr
    
    follower_ids = [i for i in range(1, n + 1) if i != leader_id]
    num_followers = len(follower_ids)
    
    print("=" * 70)
    print("  - ")
    print("=" * 70)
    print(f"\n :")
    print(f"    Node  n:       {n}")
    print(f"    Leader ID:      {leader_id}")
    print(f"    Follower IDs:   {follower_ids} {num_followers} ")
    print(f"    p_node :    {p_levels}")
    print(f"    Test :   {rounds}")
    print(f"    Loss Rate :         {packet_loss*100:.1f}%")
    print(f"    SNR :       {'Simulate  bug' if snr_missing else ''}")
    print(f"    Vote :       W_yes > W_noLeader")
    
    print("\n" + "=" * 70)
    print(" Analysis vs Result ")
    print("=" * 70)
    print(f"\n{'p_node':<10} {'P_sys':<12} {'P_sys':<12} {'':<10}")
    print("-" * 50)
    
    results = []
    
    for p in p_levels:
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
    print(" ")
    print("=" * 70)
    
    avg_error = statistics.mean(r['error_pct'] for r in results)
    print(f"\n   Avg : {avg_error:.2f}%")
    
    if avg_error < 5:
        print("    Result ")
    else:
        print("    Result ")


if __name__ == "__main__":
    main()

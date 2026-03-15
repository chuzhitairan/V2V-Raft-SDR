#!/usr/bin/env python3
"""
 - Leader  ()
=========================================


1. SNR ()
2. p_node (Node )
3. n ()

 K Test Stats 
- Valid  (Effective Scale)
-  (P_sys)

:
    python3 raft_leader_reliability.py --id 1 --total 6 --tx 10001 --rx 20001

: V2V-Raft-SDR 
"""

import socket
import time
import random
import json
import argparse
import threading
import statistics
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple
from datetime import datetime

BROADCAST_IP = "127.0.0.1"


# ============================================================================
# ============================================================================

@dataclass
class PhyState:
    """Status """
    snr: float = 0.0


@dataclass
class LogEntry:
    """Log """
    term: int
    index: int
    command: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Message:
    """ ()"""
    type: str
    term: int
    sender_id: int
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0
    last_log_index: int = 0
    success: bool = False
    phy_state: PhyState = field(default_factory=PhyState)
    snr_report: Dict[int, float] = field(default_factory=dict)
    target_snr: float = 0.0
    p_node: float = 1.0
    vote_request_id: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(json_str: str) -> 'Message':
        try:
            data = json.loads(json_str)
            if 'phy_state' in data:
                data['phy_state'] = PhyState(**data['phy_state'])
            if 'entries' in data:
                data['entries'] = [LogEntry(**e) for e in data['entries']]
            if 'snr_report' in data and data['snr_report']:
                data['snr_report'] = {int(k): v for k, v in data['snr_report'].items()}
            return Message(**data)
        except:
            return None


# ============================================================================
# ============================================================================

class LeaderReliability:
    """
     Leader
    
    
    1.  (SNR -> p_node -> n)
    2. Broadcast  p_node  Follower
    3. Vote Stats 
    4. Result 
    """
    
    def __init__(self, node_id: int, total_nodes: int, 
                 tx_port: int, rx_port: int):
        self.node_id = node_id
        self.role = 'leader'
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.leader_id = node_id
        
        # Raft Status 
        self.current_term = 1
        self.log: List[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0
        
        # Leader Status 
        self.next_index: Dict[int, int] = {}
        self.match_index: Dict[int, int] = {}
        for i in range(1, total_nodes + 1):
            if i != node_id:
                self.next_index[i] = 1
                self.match_index[i] = 0
        
        self.peers: Dict[int, dict] = {}
        
        # Config 
        self.heartbeat_interval = 0.1
        self.snr_report_interval = 0.2
        self.status_interval = 1.0
        
        self.target_snr = 16.0
        self.current_p_node = 1.0
        self.current_n = 6
        self.current_p_node = 1.0
        
        self.snr = 16.0
        self.p_node_levels = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
        self.n = 4
        self.rounds_per_config = 30
        self.vote_deadline = 0.4
        self.stabilize_time = 2.0
        self.snr_tolerance = 3.0
        self.cluster_timeout = 0.4
        
        self.vote_request_id = 0
        self.votes_received: Dict[int, bool] = {}  # {node_id: success}
        self.votes_lock = threading.Lock()
        
        self.results: List[dict] = []
        self.experiment_running = False
        
        # Stats 
        self.stats = {
            'heartbeats_sent': 0,
            'snr_reports_sent': 0,
            'vote_requests_sent': 0,
            'votes_received_total': 0,
            'votes_expected_total': 0,
        }
        
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f" [Node  {node_id}]  LEADER")
        print(f"   TX:{tx_port} RX:{rx_port}")

    def send_heartbeat(self):
        """Send Heartbeat  -  target_snr  p_node"""
        with self.lock:
            msg = Message(
                type="APPEND",
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=0,
                prev_log_term=0,
                leader_commit=self.commit_index,
                entries=[],
                target_snr=self.target_snr,
                p_node=self.current_p_node,
                vote_request_id=0
            )
            self._broadcast(msg)
            self.stats['heartbeats_sent'] += 1
    
    def send_vote_request(self, command: str = "DECISION") -> int:
        """Send Vote  ID"""
        with self.lock:
            self.vote_request_id += 1
            request_id = self.vote_request_id
            
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=command
            )
            
            msg = Message(
                type="APPEND",
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=len(self.log),
                prev_log_term=self.log[-1].term if self.log else 0,
                leader_commit=self.commit_index,
                entries=[entry],
                target_snr=self.target_snr,
                p_node=self.current_p_node,
                vote_request_id=request_id
            )
            
            with self.votes_lock:
                self.votes_received = {}
            
            self._broadcast(msg)
            self.stats['vote_requests_sent'] += 1
            return request_id
    
    def _resend_vote_request(self, request_id: int):
        """Vote  ( request_idAlready Received Vote )"""
        with self.lock:
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=f"RESEND_{request_id}"
            )
            
            msg = Message(
                type="APPEND",
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=len(self.log),
                prev_log_term=self.log[-1].term if self.log else 0,
                leader_commit=self.commit_index,
                entries=[entry],
                target_snr=self.target_snr,
                p_node=self.current_p_node,
                vote_request_id=request_id
            )
            
            self._broadcast(msg)
    
    def send_snr_report(self):
        """Broadcast  SNR  -  p_node"""
        with self.lock:
            snr_data = {}
            for peer_id, info in self.peers.items():
                if time.time() - info['last_seen'] <= self.cluster_timeout:
                    snr_data[peer_id] = info['snr']
            
            if not snr_data:
                return
            
            msg = Message(
                type="SNR_REPORT",
                term=self.current_term,
                sender_id=self.node_id,
                snr_report=snr_data,
                target_snr=self.target_snr,
                p_node=self.current_p_node
            )
            self._broadcast(msg)
            self.stats['snr_reports_sent'] += 1
    
    def collect_votes(self, request_id: int, n: int) -> Tuple[int, int, int]:
        """
        Vote Result  ()
        
        Stats  Follower Vote Valid 
              Follower ID  1~n  Leader Node 
        
        Args:
            request_id: Vote  ID
            n: Current  (Stats  Follower ID Node )
        
        Returns:
            (yes_votes, no_votes, total_votes) -  Follower Vote 
        """
        with self.votes_lock:
            yes_votes = 0
            no_votes = 0
            
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            
            for node_id, success in self.votes_received.items():
                if node_id in follower_ids:
                    if success:
                        yes_votes += 1
                    else:
                        no_votes += 1
            
            total_votes = yes_votes + no_votes
            return yes_votes, no_votes, total_votes
    
    def collect_weighted_votes(self, request_id: int, n: int) -> Tuple[float, float, bool]:
        """
        Vote Result  ( SNR )
        
        
        1.  Follower Vote  (Result )
        2. Leader Vote 
        3. Received Vote Approve  > 
           (Node )
        4.  SNR 
        
        Args:
            request_id: Vote  ID
            n: Current  (Stats  ID <= n Node )
        
        Returns:
            (W_yes, W_total, consensus_reached)
        """
        with self.votes_lock:
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            voters = []
            for node_id, success in self.votes_received.items():
                if node_id in follower_ids:
                    snr = 0.0
                    if node_id in self.peers:
                        snr = self.peers[node_id].get('snr', 0.0)
                    voters.append({'id': node_id, 'success': success, 'snr': snr})
            
            max_follower_snr = max((v['snr'] for v in voters), default=self.target_snr)
            leader_virtual_snr = max_follower_snr + 2.0
            leader_vote = random.random() < self.current_p_node
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
            
            return W_yes, W_total, consensus_reached
    
    def collect_weighted_votes_debug(self, request_id: int, n: int) -> Tuple[float, float, bool, str]:
        """
        Vote Result  ()
        
        
        1.  Follower Vote  + Leader Vote 
        2. Approve  >  ()
        3.  SNR 
        
        Returns:
            (W_yes, W_total, consensus_reached, details_str)
        """
        with self.votes_lock:
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            voters = []
            for node_id, success in self.votes_received.items():
                if node_id in follower_ids:
                    snr = 0.0
                    if node_id in self.peers:
                        snr = self.peers[node_id].get('snr', 0.0)
                    voters.append({'id': node_id, 'success': success, 'snr': snr})
            
            max_follower_snr = max((v['snr'] for v in voters), default=self.target_snr)
            leader_virtual_snr = max_follower_snr + 2.0
            leader_vote = random.random() < self.current_p_node
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
            
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            follower_count = len([v for v in voters if v.get('id', 0) in follower_ids])
            no_reply = len(follower_ids) - follower_count
            
            # Leader Vote Status 
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
            
            # leader_w = next((v['weight'] for v in voters if v.get('is_leader')), 1.0)
            
            details = (f"Approve :{yes_count} :{no_count} :{no_reply} | "
                      f"L:{leader_icon} {' '.join(follower_vote_strs)} | "
                      f"W_yes={W_yes:.3f}>W_no={W_no:.3f}? {result_icon}")
            
            return W_yes, W_total, consensus_reached, details
    
    def _handle_append_response(self, msg: Message):
        """Vote """
        self._update_peer(msg.sender_id, msg.phy_state)
        
        if hasattr(msg, 'vote_request_id') and msg.vote_request_id > 0:
            with self.votes_lock:
                if msg.vote_request_id == self.vote_request_id:
                    self.votes_received[msg.sender_id] = msg.success
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """ SNR"""
        now = time.time()
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        
        alpha = 0.3
        old_snr = self.peers[sender_id]['snr']
        new_snr = phy_state.snr
        if old_snr > 0:
            smoothed = alpha * new_snr + (1 - alpha) * old_snr
        else:
            smoothed = new_snr
        
        self.peers[sender_id]['snr'] = smoothed
        self.peers[sender_id]['last_seen'] = now
        self.peers[sender_id]['count'] += 1
    
    def _broadcast(self, msg: Message):
        """Broadcast """
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f" Send Fail : {e}")

    def get_active_peer_count(self) -> int:
        """Current Node """
        now = time.time()
        count = 1
        with self.lock:
            for peer_id, info in self.peers.items():
                if now - info['last_seen'] <= self.cluster_timeout:
                    count += 1
        return count
    
    def print_cluster_status(self):
        """Status """
        now = time.time()
        print("\n" + "" * 60)
        print(" Status ")
        print("" * 60)
        print(f"   Node  {self.node_id:2d} (Leader)    SNR: ---- ()     ")
        
        with self.lock:
            for peer_id in sorted(self.peers.keys()):
                info = self.peers[peer_id]
                age = now - info['last_seen']
                if age <= self.cluster_timeout:
                    status = " "
                    snr_str = f"{info['snr']:5.1f}dB"
                else:
                    status = " "
                    snr_str = "-----"
                print(f"   Node  {peer_id:2d} (Follower)  SNR: {snr_str}      {status}  ({age:.1f}s)")
        
        active = self.get_active_peer_count()
        print(f"\n   Node : {active}/{self.total_nodes}")
        print("" * 60)
    
    def wait_for_snr_stable(self, target_snr: float, timeout: float = 30.0) -> bool:
        """Waiting  SNR """
        print(f"\n Waiting  SNR  {target_snr} dB...")
        print("   (Node Gain Adjust Target  SNR)")
        
        start_time = time.time()
        stable_count = 0
        required_stable = 3
        
        while time.time() - start_time < timeout:
            time.sleep(0.4)
            
            with self.lock:
                if not self.peers:
                    print("    Node ...")
                    continue
                
                print(f"\n    SNR Status  (Target : {target_snr} dB)")
                snr_diffs = []
                for peer_id in sorted(self.peers.keys()):
                    info = self.peers[peer_id]
                    if time.time() - info['last_seen'] <= self.cluster_timeout:
                        diff = abs(info['snr'] - target_snr)
                        snr_diffs.append(diff)
                        if diff <= self.snr_tolerance:
                            status = ""
                        elif diff <= self.snr_tolerance * 2:
                            status = ""
                        else:
                            status = ""
                        print(f"      Node  {peer_id}: {info['snr']:5.1f} dB ( {diff:+.1f}) {status}")
                
                if snr_diffs:
                    avg_diff = statistics.mean(snr_diffs)
                    if avg_diff <= self.snr_tolerance:
                        stable_count += 1
                        print(f"    {stable_count}/{required_stable} (Avg : {avg_diff:.1f} dB)")
                        if stable_count >= required_stable:
                            print(f" SNR Already ")
                            return True
                    else:
                        stable_count = 0
        
        print(f" SNR Timeout ")
        return False
    
    # ========================================================================
    # ========================================================================
    
    def run_experiment(self):
        """Run (p_node)"""
        self.experiment_running = True
        
        n = self.n
        snr = self.snr
        total_configs = len(self.p_node_levels)
        total_rounds = total_configs * self.rounds_per_config
        
        print("\n" + "=" * 70)
        print(" Start")
        print("=" * 70)
        print(f"\n :")
        print(f"    Target  SNR:       {snr} dB ()")
        print(f"    p_node :   {self.p_node_levels}")
        print(f"    Node  n:       {n} ()")
        print(f"    Test :  {self.rounds_per_config}")
        print(f"    Vote Time :  {self.vote_deadline}s")
        print(f"    Config :      {total_configs}  ({total_rounds} )")
        print("\n" + "=" * 70)
        
        self.print_cluster_status()
        
        self.target_snr = snr
        print(f"\n{'='*70}")
        print(f" Target  SNR: {snr} dB")
        print(f"{'='*70}")
        self.wait_for_snr_stable(snr, timeout=self.stabilize_time)
        
        config_idx = 0
        experiment_start = time.time()
        
        for p_node in self.p_node_levels:
            self.current_p_node = p_node
            self.current_n = n
            config_idx += 1
            
            print(f"\n     p_node = {p_node}")
            
            for _ in range(5):
                self.send_heartbeat()
                time.sleep(0.04)
            
            elapsed = time.time() - experiment_start
            if config_idx > 1:
                avg_time_per_config = elapsed / (config_idx - 1)
                remaining = avg_time_per_config * (total_configs - config_idx + 1)
                eta_str = f" {remaining/60:.1f} "
            else:
                eta_str = ""
            
            progress = config_idx / total_configs
            bar_len = 20
            filled = int(bar_len * progress)
            bar = "" * filled + "" * (bar_len - filled)
            
            print(f"\n   ")
            print(f"    [{config_idx}/{total_configs}] {bar} {progress*100:.0f}%  {eta_str}")
            print(f"    SNR={snr}dB, p_node={p_node}, n={n}")
            print(f"   ")
            print(f"    Start... ( {self.rounds_per_config} )")
            
            success_count = 0
            effective_scales = []
            config_start_time = time.time()
            
            for k in range(self.rounds_per_config):
                request_id = self.send_vote_request(f"DECISION_{config_idx}_{k}")
                
                resend_interval = 0.06
                elapsed = 0
                while elapsed < self.vote_deadline - resend_interval:
                    time.sleep(resend_interval)
                    elapsed += resend_interval
                    self._resend_vote_request(request_id)
                
                remaining = self.vote_deadline - elapsed
                if remaining > 0:
                    time.sleep(remaining)
                
                W_yes, W_total, consensus, vote_details = self.collect_weighted_votes_debug(request_id, n)
                
                yes, no, total = self.collect_votes(request_id, n)
                
                follower_count = n - 1
                self.stats['votes_expected_total'] += follower_count
                self.stats['votes_received_total'] += total
                
                effective_scales.append(total)
                
                if consensus:
                    success_count += 1
                
                if k < 5:
                    print(f"        {k+1}: {vote_details}")
                
                time.sleep(0.02)
                
                print_interval = min(10, max(1, self.rounds_per_config // 5))
                if (k + 1) % print_interval == 0 or k == self.rounds_per_config - 1:
                    p_sys_so_far = success_count / (k + 1)
                    avg_scale_so_far = statistics.mean(effective_scales)
                    curr_expected = follower_count * (k + 1)
                    curr_received = sum(effective_scales)
                    curr_loss = 1.0 - curr_received / curr_expected if curr_expected > 0 else 0
                    elapsed_config = time.time() - config_start_time
                    print(f"       {k+1:3d}/{self.rounds_per_config}: "
                          f"P_sys={p_sys_so_far:.2f} ={avg_scale_so_far:.1f} "
                          f"={curr_loss*100:.0f}% ({elapsed_config:.0f}s)")
            
            p_sys = success_count / self.rounds_per_config
            avg_effective_scale = statistics.mean(effective_scales)
            std_effective_scale = statistics.stdev(effective_scales) if len(effective_scales) > 1 else 0
            
            follower_count = n - 1
            config_expected = follower_count * self.rounds_per_config
            config_received = sum(effective_scales)
            config_loss = 1.0 - config_received / config_expected if config_expected > 0 else 0
            
            result = {
                'snr': snr,
                'p_node': p_node,
                'n': n,
                'p_sys': p_sys,
                'avg_effective_scale': avg_effective_scale,
                'std_effective_scale': std_effective_scale,
                'success_count': success_count,
                'total_rounds': self.rounds_per_config,
                'packet_loss_rate': config_loss,
                'raw_effective_scales': effective_scales
            }
            self.results.append(result)
            
            if p_sys >= 0.9:
                status = ""
            elif p_sys >= 0.7:
                status = ""
            else:
                status = ""
            print(f"   {status} P_sys={p_sys:.2f} ={avg_effective_scale:.1f}{std_effective_scale:.1f} ={config_loss*100:.0f}%")
        
        total_time = time.time() - experiment_start
        print(f"\n Time : {total_time/60:.1f} ")
        
        self.experiment_running = False
        self._print_final_results()
        self._save_results()
    
    def _print_final_results(self):
        """Result """
        print("\n" + "=" * 80)
        print(" Result ")
        print("=" * 80)
        
        print(f"\n--- SNR = {self.snr} dB, n = {self.n} ---")
        print(f"{'p_node':<8} {'P_sys':<8} {'Loss Rate ':<10} {'Valid ':<15}")
        print("-" * 50)
        
        for r in self.results:
            loss_rate = r.get('packet_loss_rate', 0.0)
            print(f"{r['p_node']:<8.2f} "
                  f"{r['p_sys']:<8.3f} "
                  f"{loss_rate*100:>5.1f}%    "
                  f"{r['avg_effective_scale']:.2f}{r['std_effective_scale']:.2f}")
        
        print("=" * 80)
    
    def _save_results(self):
        """Result  JSON """
        import os
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        param_folder = f"n{self.n}_snr{self.snr:.0f}"
        results_dir = os.path.join(script_dir, "..", "results", param_folder)
        
        os.makedirs(results_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"reliability_{timestamp}.json"
        filepath = os.path.join(results_dir, filename)
        
        data = {
            'start_time': datetime.now().isoformat(),
            'total_nodes': self.total_nodes,
            'snr': self.snr,
            'n': self.n,
            'p_node_levels': self.p_node_levels,
            'rounds_per_config': self.rounds_per_config,
            'vote_deadline': self.vote_deadline,
            'results': self.results
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"\n Result Already : {filepath}")
        except Exception as e:
            print(f" Fail : {e}")
    
    def recv_loop(self):
        """Receive """
        print(" Receive Start ")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = Message.from_json(data.decode('utf-8'))
                
                if msg and msg.sender_id != self.node_id:
                    if msg.type == "APPEND_RESPONSE":
                        self._handle_append_response(msg)
                        
            except Exception as e:
                if self.running:
                    print(f"Receive Error: {e}")
    
    def main_loop(self):
        """ (Heartbeat  + SNR )"""
        print(" Start ")
        last_heartbeat = time.time()
        last_snr_report = time.time()
        last_status = time.time()
        
        while self.running:
            now = time.time()
            
            if now - last_heartbeat >= self.heartbeat_interval:
                self.send_heartbeat()
                last_heartbeat = now
            
            if now - last_snr_report >= self.snr_report_interval:
                self.send_snr_report()
                last_snr_report = now
            
            if now - last_status >= self.status_interval:
                active = self.get_active_peer_count()
                expected = self.stats.get('votes_expected_total', 0)
                received = self.stats.get('votes_received_total', 0)
                if expected > 0:
                    loss_rate = 1.0 - received / expected
                    loss_str = f", Loss Rate ={loss_rate*100:.1f}%"
                else:
                    loss_str = ""
                print(f" :{active} | SNR={self.target_snr}dB | p={self.current_p_node}{loss_str}")
                last_status = now
            
            time.sleep(0.05)
    
    def stop(self):
        self.running = False
        self.sock.close()


# ============================================================================
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description=" Leader")
    parser.add_argument("--id", type=int, required=True, help="Node  ID")
    parser.add_argument("--total", type=int, default=6, help="Node ")
    parser.add_argument("--tx", type=int, required=True, help="TX Port ")
    parser.add_argument("--rx", type=int, required=True, help="RX Port ")
    parser.add_argument("--snr", type=float, required=True,
                        help="Target  SNR ()")
    parser.add_argument("--p-node-levels", type=str, default="0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90",
                        help="p_node  ( 1.0)")
    parser.add_argument("--n", type=int, required=True,
                        help="Current Node  ()")
    parser.add_argument("--rounds", type=int, default=30, help="Config Test ")
    parser.add_argument("--vote-deadline", type=float, default=0.4, help="Vote Time  (5)")
    parser.add_argument("--stabilize-time", type=float, default=2.0, 
                        help="SNR Time  (5)")
    args = parser.parse_args()
    
    node = LeaderReliability(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx
    )
    
    node.snr = args.snr
    node.target_snr = 16.0
    node.p_node_levels = [float(x) for x in args.p_node_levels.split(',')]
    node.n = args.n
    node.rounds_per_config = args.rounds
    node.vote_deadline = args.vote_deadline
    node.stabilize_time = args.stabilize_time
    
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    t_main = threading.Thread(target=node.main_loop, daemon=True)
    t_main.start()
    
    print("\n" + "=" * 60)
    print("")
    print(f" SNR: 16.0 dB | Target  SNR: {args.snr} dB")
    print("Waiting  Follower Node ...")
    print("=" * 60 + "\n")
    
    print(" Waiting Node ...")
    print("    3  count Status  Enter Start\n")
    
    import select
    import sys
    
    while True:
        node.print_cluster_status()
        
        readable, _, _ = select.select([sys.stdin], [], [], 3.0)
        if readable:
            sys.stdin.readline()
            break
    
    node.target_snr = args.snr
    
    print("\n" + "=" * 60)
    print(f" Target  SNR: {args.snr} dB")
    node.print_cluster_status()
    print("=" * 60)
    print("\n Start...")
    
    try:
        node.run_experiment()
    except KeyboardInterrupt:
        print("\n ")
        if node.results:
            node._print_final_results()
            node._save_results()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

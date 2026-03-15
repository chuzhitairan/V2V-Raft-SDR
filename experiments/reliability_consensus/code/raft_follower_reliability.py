#!/usr/bin/env python3
"""
 - Follower 
============================

 raft_follower_snr_experiment.py""
1.  Leader  p_node Param
2.  p_node  success=True
    (1-p_node)  success=False
3. "Loss""Node"

Usage:
    python3 raft_follower_reliability.py --id 2 --total 6 \
        --tx 10002 --rx 20002 --ctrl 9002

: V2V-Raft-SDR 
"""

import socket
import time
import random
import json
import argparse
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict

BROADCAST_IP = "127.0.0.1"


# ============================================================================
# 
# ============================================================================

@dataclass
class PhyState:
    """"""
    snr: float = 0.0


@dataclass
class LogEntry:
    """"""
    term: int
    index: int
    command: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Message:
    """ (Support)"""
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
    # : 
    p_node: float = 1.0          # NodeParam (0.0-1.0)
    vote_request_id: int = 0      #  ID ()

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
# Follower Node ()
# ============================================================================

class FollowerReliability:
    """
     Follower
    
    
    1.  Leader  p_node Param
    2.  (1-p_node)  success=False
    """
    
    def __init__(self, node_id: int, total_nodes: int, 
                 tx_port: int, rx_port: int, ctrl_port: int, leader_id: int = 1):
        self.node_id = node_id
        self.role = 'follower'
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.ctrl_port = ctrl_port
        self.leader_id = leader_id
        
        # Raft 
        self.current_term = 1
        self.log: List[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0
        
        #  ()
        self.current_tx_gain = 0.5
        self.min_gain = 0.1
        self.max_gain = 0.8
        self.target_snr = 20.0
        self.snr_tolerance = 0.5
        self.gain_step = 0.05
        self.last_observed_snr = 0.0
        self.gain_adjust_count = 0
        self.last_snr_report_time = time.time()  #  SNR Time
        self.snr_report_timeout = 1.0  # SNR  ()5.05
        self.reconnect_gain_boost = 0.1  # 
        
        # Param
        self.p_node = 1.0              # Node (Default)
        self.vote_stats = {
            'total_votes': 0,
            'yes_votes': 0,
            'no_votes': 0,
        }
        self.voted_requests = {}  # {request_id: vote_success} 
        self.max_voted_cache = 100  #  100  ID
        
        # 
        self.peers: Dict[int, dict] = {}
        
        # 
        self.snr_threshold = 0.0
        self.status_interval = 0.4  # 2.05
        
        # 
        self.stats = {
            'heartbeats_received': 0,
            'snr_reports_received': 0,
            'gain_adjustments': 0,
            'commands_committed': 0,
        }
        
        # 
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        #  socket
        self.ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl_sock.settimeout(0.2)  # 1.05
        
        print(f" [Node {node_id}] FOLLOWER ()")
        print(f"   TX:{tx_port} RX:{rx_port} Ctrl:{ctrl_port}")
        print(f"    p_node: {self.p_node}")

    def handle_append(self, msg: Message):
        """
         APPEND  - 
        
         ():
        1.  prev_log_index / prev_log_term ()
        2.  ()
        3.  p_node 
        4. last_log_index  index ()
        
        Loss
        """
        with self.lock:
            self.stats['heartbeats_received'] += 1
            
            #  p_node ( Leader )
            if hasattr(msg, 'p_node') and msg.p_node > 0:
                if abs(msg.p_node - self.p_node) > 0.001:
                    print(f" [] p_node: {self.p_node:.2f} -> {msg.p_node:.2f}")
                    self.p_node = msg.p_node
            
            #  SNR ()
            if hasattr(msg, 'target_snr') and msg.target_snr > 0:
                if abs(msg.target_snr - self.target_snr) > 0.1:
                    print(f" [SNR] {self.target_snr:.1f} -> {msg.target_snr:.1f} dB")
                    self.target_snr = msg.target_snr
            
            #  vote_request_id
            request_id = getattr(msg, 'vote_request_id', 0)
            
            # =====  =====
            if request_id > 0 and request_id in self.voted_requests:
                # Result ()
                vote_success = self.voted_requests[request_id]
            else:
                # =====  () =====
                #  APPEND  SNR Success
                #  p_node Result
                rand_val = random.random()
                if rand_val < self.p_node:
                    #  ->  (success=True)
                    vote_success = True
                    self.vote_stats['yes_votes'] += 1
                else:
                    #  ->  (success=False)
                    vote_success = False
                    self.vote_stats['no_votes'] += 1
                
                self.vote_stats['total_votes'] += 1
                
                # 
                if request_id > 0:
                    self.voted_requests[request_id] = vote_success
                    # 
                    if len(self.voted_requests) > self.max_voted_cache:
                        oldest = min(self.voted_requests.keys())
                        del self.voted_requests[oldest]
            
            #  index ()
            received_log_index = 0
            if msg.entries:
                received_log_index = msg.entries[-1].index
            
            # 
            # : last_log_index  index ()
            #  " N  / "
            reply = Message(
                type="APPEND_RESPONSE",
                term=self.current_term,
                sender_id=self.node_id,
                success=vote_success,
                last_log_index=received_log_index,  # !
                vote_request_id=msg.vote_request_id,
                phy_state=PhyState(snr=self.last_observed_snr)  #  SNR
            )
            
            #  ()
            #  ()
            if msg.entries:
                for entry in msg.entries:
                    # 
                    self.log.append(entry)
            
            #  commit ()
            if msg.leader_commit > self.commit_index:
                self.commit_index = msg.leader_commit
                self._apply_committed()
            
            #  
            time.sleep(random.uniform(0.01, 0.05))
            self._broadcast(reply)
    
    def handle_snr_report(self, msg: Message):
        """ SNR  ()"""
        self.stats['snr_reports_received'] += 1
        
        #  SNR
        if hasattr(msg, 'target_snr') and msg.target_snr > 0:
            if abs(msg.target_snr - self.target_snr) > 0.1:
                self.target_snr = msg.target_snr
        
        #  p_node
        if hasattr(msg, 'p_node') and msg.p_node > 0:
            if abs(msg.p_node - self.p_node) > 0.001:
                print(f" [] p_node: {self.p_node:.2f} -> {msg.p_node:.2f}")
                self.p_node = msg.p_node
        
        #  SNR
        my_snr = msg.snr_report.get(self.node_id, None)
        if my_snr is None:
            # Leader  SNR
            return
        
        #  SNR Time
        self.last_snr_report_time = time.time()
        self.last_observed_snr = my_snr
        
        # 
        snr_diff = my_snr - self.target_snr
        
        if abs(snr_diff) <= self.snr_tolerance:
            return
        
        adjust_factor = -snr_diff / 5.0
        gain_delta = self.gain_step * adjust_factor
        gain_delta = max(-0.15, min(0.15, gain_delta))
        
        new_gain = self.current_tx_gain + gain_delta
        new_gain = max(self.min_gain, min(self.max_gain, new_gain))
        
        if abs(new_gain - self.current_tx_gain) > 0.001:
            old_gain = self.current_tx_gain
            self.current_tx_gain = new_gain
            self.gain_adjust_count += 1
            self.stats['gain_adjustments'] += 1
            
            success = self._set_phy_tx_gain(new_gain)
            
            direction = "" if gain_delta > 0 else ""
            status = "" if success else ""
            print(f"{direction} [] SNR={my_snr:.1f}dB, "
                  f"TX: {old_gain:.3f} -> {new_gain:.3f} {status}")
    
    def _set_phy_tx_gain(self, gain: float) -> bool:
        """ PHY TX """
        try:
            cmd = json.dumps({"cmd": "set_tx_gain", "value": gain})
            self.ctrl_sock.sendto(cmd.encode(), (BROADCAST_IP, self.ctrl_port))
            
            try:
                response, _ = self.ctrl_sock.recvfrom(1024)
                result = json.loads(response.decode())
                return result.get('status') == 'ok'
            except socket.timeout:
                return False
        except Exception as e:
            print(f" Fail: {e}")
            return False
    
    def _apply_committed(self):
        """"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            # print(f" []  #{entry.index}: {entry.command}")
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """"""
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        self.peers[sender_id]['snr'] = phy_state.snr
        self.peers[sender_id]['last_seen'] = time.time()
        self.peers[sender_id]['count'] += 1
    
    def _broadcast(self, msg: Message):
        """"""
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f" Fail: {e}")

    def recv_loop(self):
        """"""
        print(" ")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = Message.from_json(data.decode('utf-8'))
                
                if msg and msg.sender_id != self.node_id:
                    self._update_peer(msg.sender_id, msg.phy_state)
                    
                    if msg.type == "APPEND" or msg.type == "HEARTBEAT":
                        self.handle_append(msg)
                    elif msg.type == "SNR_REPORT":
                        self.handle_snr_report(msg)
                        
            except Exception as e:
                if self.running:
                    print(f": {e}")
    
    def main_loop(self):
        """"""
        print(" ")
        last_status = time.time()
        last_reconnect_attempt = time.time()
        
        while self.running:
            now = time.time()
            
            #  SNR  ()
            time_since_snr = now - self.last_snr_report_time
            if time_since_snr > self.snr_report_timeout:
                # 
                if now - last_reconnect_attempt >= self.snr_report_timeout:
                    self._try_reconnect()
                    last_reconnect_attempt = now
            
            if now - last_status >= self.status_interval:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)
    
    def _try_reconnect(self):
        """ TX """
        with self.lock:
            old_gain = self.current_tx_gain
            new_gain = min(self.max_gain, self.current_tx_gain + self.reconnect_gain_boost)
            
            if new_gain > old_gain:
                self.current_tx_gain = new_gain
                success = self._set_phy_tx_gain(new_gain)
                status = "" if success else ""
                print(f" []  SNR : {old_gain:.3f} -> {new_gain:.3f} {status}")
            else:
                print(f" []  {self.max_gain:.3f} Leader ...")
    
    def _print_status(self):
        """"""
        with self.lock:
            snr_diff = self.last_observed_snr - self.target_snr
            if self.last_observed_snr > 0:
                if abs(snr_diff) <= self.snr_tolerance:
                    status = ""
                elif snr_diff < 0:
                    status = ""
                else:
                    status = ""
            else:
                status = ""
            
            total = self.vote_stats['total_votes']
            yes = self.vote_stats['yes_votes']
            no = self.vote_stats['no_votes']
            yes_rate = (yes / total * 100) if total > 0 else 0
            
            print(f"\n [Follower {self.node_id}] p_node={self.p_node:.2f}")
            print(f"   SNR: {self.last_observed_snr:.1f}dB ({self.target_snr}) {status}")
            print(f"   TX: {self.current_tx_gain:.3f}")
            print(f"   : {total} ({yes}/{yes_rate:.1f}%, {no})")
    
    def stop(self):
        self.running = False
        self.sock.close()
        self.ctrl_sock.close()


# ============================================================================
# 
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Follower Node ()")
    parser.add_argument("--id", type=int, required=True, help="Node ID")
    parser.add_argument("--role", type=str, default='follower', help="")
    parser.add_argument("--total", type=int, default=6, help="Node")
    parser.add_argument("--tx", type=int, required=True, help="TX ")
    parser.add_argument("--rx", type=int, required=True, help="RX ")
    parser.add_argument("--ctrl", type=int, required=True, help="PHY ")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader ID")
    parser.add_argument("--target-snr", type=float, default=20.0, help=" SNR")
    parser.add_argument("--snr-tolerance", type=float, default=2.0, help="SNR ")
    parser.add_argument("--init-gain", type=float, default=0.5, help=" TX ")
    parser.add_argument("--p-node", type=float, default=1.0, help="Node")
    parser.add_argument("--status-interval", type=float, default=0.4, help=" (5)")
    args = parser.parse_args()
    
    node = FollowerReliability(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx,
        ctrl_port=args.ctrl,
        leader_id=args.leader_id
    )
    node.target_snr = args.target_snr
    node.snr_tolerance = args.snr_tolerance
    node.current_tx_gain = args.init_gain
    node.p_node = args.p_node
    node.status_interval = args.status_interval
    
    # 
    node._set_phy_tx_gain(args.init_gain)
    
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    try:
        node.main_loop()
    except KeyboardInterrupt:
        print("\n ")
        node._print_status()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Gain Adjust  Follower Node 
==============================

 Raft Follower Receive  Leader Broadcast  SNR 
 SNR Adjust Gain  SNR Target 

Gain Adjust :
    - Target  SNR = 20 dB (Config )
    -  SNR < Target  - 2dB TX Gain 
    -  SNR > Target  + 2dB TX Gain 
    -  PID Adjust  Step 

:
    python3 raft_follower_gain_adjust.py --id 2 --role follower --total 6 \
        --tx 10002 --rx 20002 --ctrl 9002

: V2V-Raft-SDR 
"""

import socket
import time
import json
import argparse
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict

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
    """"""
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

class FollowerWithGainAdjust:
    """
    Gain Adjust  Follower
    
    Receive  Leader  SNR Adjust  TX Gain 
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
        
        # Raft Status 
        self.current_term = 1
        self.log: List[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0
        
        self.current_tx_gain = 0.7      # Current  TX Gain 
        self.min_gain = 0.1
        self.max_gain = 1.0
        self.target_snr = 20.0          # Target  SNR
        self.snr_tolerance = 2.0
        self.gain_step = 0.02
        self.last_observed_snr = 0.0
        self.gain_adjust_count = 0
        
        self.peers: Dict[int, dict] = {}
        
        # Config 
        self.snr_threshold = 0.0
        self.status_interval = 2.0
        
        # Stats 
        self.stats = {
            'heartbeats_received': 0,
            'snr_reports_received': 0,
            'gain_adjustments': 0,
            'commands_committed': 0,
        }
        
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        self.ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl_sock.settimeout(1.0)
        
        print(f" [Node  {node_id}] FOLLOWER (Gain Adjust )")
        print(f"   TX:{tx_port} RX:{rx_port} Ctrl:{ctrl_port}")
        print(f"   Target  SNR: {self.target_snr} dB  {self.snr_tolerance} dB")
        print(f"    TX Gain : {self.current_tx_gain}")

    def handle_append(self, msg: Message):
        """ APPEND """
        with self.lock:
            self.stats['heartbeats_received'] += 1
            
            reply = Message(
                type="APPEND_RESPONSE",
                term=self.current_term,
                sender_id=self.node_id,
                success=False,
                last_log_index=len(self.log)
            )
            
            if msg.prev_log_index > 0:
                if len(self.log) < msg.prev_log_index:
                    self._broadcast(reply)
                    return
                if self.log[msg.prev_log_index - 1].term != msg.prev_log_term:
                    self.log = self.log[:msg.prev_log_index - 1]
                    self._broadcast(reply)
                    return
            
            if msg.entries:
                new_entries = []
                for entry in msg.entries:
                    if entry.index > len(self.log):
                        new_entries.append(entry)
                    elif self.log[entry.index - 1].term != entry.term:
                        self.log = self.log[:entry.index - 1]
                        new_entries.append(entry)
                
                if new_entries:
                    self.log.extend(new_entries)
                    print(f" [] Received  {len(new_entries)} Log ")
            
            if msg.leader_commit > self.commit_index:
                self.commit_index = min(msg.leader_commit, len(self.log))
                self._apply_committed()
            
            reply.success = True
            reply.last_log_index = len(self.log)
            self._broadcast(reply)
    
    def handle_snr_report(self, msg: Message):
        """ SNR Adjust Gain """
        self.stats['snr_reports_received'] += 1
        
        my_snr = msg.snr_report.get(self.node_id, None)
        if my_snr is None:
            return
        
        self.last_observed_snr = my_snr
        
        snr_diff = my_snr - self.target_snr
        
        if abs(snr_diff) <= self.snr_tolerance:
            return
        
        adjust_factor = -snr_diff / 10.0
        gain_delta = self.gain_step * adjust_factor
        
        gain_delta = max(-0.1, min(0.1, gain_delta))
        
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
            print(f"{direction} [Gain Adjust  #{self.gain_adjust_count}] "
                  f"SNR={my_snr:.1f}dB (Target {self.target_snr}), "
                  f"TXGain : {old_gain:.3f} -> {new_gain:.3f} {status}")
    
    def _set_phy_tx_gain(self, gain: float) -> bool:
        """Port  PHY TX Gain """
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
            print(f" Gain Fail : {e}")
            return False
    
    def _apply_committed(self):
        """Already Log """
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            print(f" []  #{entry.index}: {entry.command}")
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """Status """
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        self.peers[sender_id]['snr'] = phy_state.snr
        self.peers[sender_id]['last_seen'] = time.time()
        self.peers[sender_id]['count'] += 1
    
    def _broadcast(self, msg: Message):
        """Send """
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f" Send Fail : {e}")

    def recv_loop(self):
        """Receive """
        print(" Receive Start ")
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
                    print(f"Receive Error: {e}")
    
    def main_loop(self):
        """"""
        print(" Start ")
        last_status = time.time()
        
        while self.running:
            now = time.time()
            
            if now - last_status >= self.status_interval:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)
    
    def _print_status(self):
        """Status """
        with self.lock:
            snr_diff = self.last_observed_snr - self.target_snr
            if self.last_observed_snr > 0:
                if abs(snr_diff) <= self.snr_tolerance:
                    status = " "
                elif snr_diff < 0:
                    status = " "
                else:
                    status = " "
            else:
                status = " "
            
            print(f"\n [Follower Status ] Node {self.node_id}")
            print(f"   Leader  SNR: {self.last_observed_snr:.1f} dB "
                  f"(Target  {self.target_snr} dB) {status}")
            print(f"   Current  TX Gain : {self.current_tx_gain:.3f}")
            print(f"   Log : {len(self.log)}, : {self.commit_index}")
            print(f"   Heartbeat : {self.stats['heartbeats_received']}, "
                  f"SNR: {self.stats['snr_reports_received']}, "
                  f"Gain Adjust : {self.stats['gain_adjustments']}")
    
    def stop(self):
        self.running = False
        self.sock.close()
        self.ctrl_sock.close()


# ============================================================================
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Follower Node  (Gain Adjust )")
    parser.add_argument("--id", type=int, required=True, help="Node  ID")
    parser.add_argument("--role", type=str, default='follower', help=" ( follower)")
    parser.add_argument("--total", type=int, default=6, help="Node ")
    parser.add_argument("--tx", type=int, required=True, help="TX Port ")
    parser.add_argument("--rx", type=int, required=True, help="RX Port ")
    parser.add_argument("--ctrl", type=int, required=True, help="PHY Port ")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader ID")
    parser.add_argument("--target-snr", type=float, default=20.0, help="Target  SNR (dB)")
    parser.add_argument("--snr-tolerance", type=float, default=2.0, help="SNR  (dB)")
    parser.add_argument("--init-gain", type=float, default=0.7, help=" TX Gain ")
    parser.add_argument("--status-interval", type=float, default=2.0, help="Status ")
    args = parser.parse_args()
    
    if args.role != 'follower':
        print("   follower ")
        return
    
    node = FollowerWithGainAdjust(
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
    node.status_interval = args.status_interval
    
    node._set_phy_tx_gain(args.init_gain)
    
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    try:
        node.main_loop()
    except KeyboardInterrupt:
        print("\n Stop ")
        node._print_status()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

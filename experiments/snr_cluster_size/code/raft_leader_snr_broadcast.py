#!/usr/bin/env python3
"""
 SNR Broadcast  Leader Node 
=========================

 Raft Leader Broadcast Node  SNR
 Follower Adjust Gain 

:
    - SNR_REPORT: Leader -> All,  {node_id: snr} 

:
    python3 raft_leader_snr_broadcast.py --id 1 --role leader --total 6 --tx 10001 --rx 20001

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
    """ ( SNR_REPORT)"""
    type: str           # APPEND, APPEND_RESPONSE, SNR_REPORT
    term: int
    sender_id: int
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0
    last_log_index: int = 0
    success: bool = False
    phy_state: PhyState = field(default_factory=PhyState)
    snr_report: Dict[int, float] = field(default_factory=dict)  # {node_id: snr}

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

class LeaderWithSNRBroadcast:
    """
     SNR Broadcast  Leader
    
    Broadcast Node  SNR
     Follower Adjust Gain 
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
        self.heartbeat_interval = 0.2
        self.snr_threshold = 0.0
        self.status_interval = 2.0
        self.snr_report_interval = 1.0
        self.target_snr = 20.0          # Target  SNR
        
        # Stats 
        self.stats = {
            'heartbeats_sent': 0,
            'snr_reports_sent': 0,
            'entries_replicated': 0,
            'commands_committed': 0,
        }
        
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f" [Node  {node_id}] LEADER (SNR Broadcast )")
        print(f"   TX:{tx_port} RX:{rx_port}")
        print(f"   Target  SNR: {self.target_snr} dB")

    def send_heartbeat(self):
        """Send Heartbeat """
        with self.lock:
            min_next = min(self.next_index.values()) if self.next_index else len(self.log) + 1
            prev_idx = min_next - 1
            prev_term = self.log[prev_idx - 1].term if prev_idx > 0 and prev_idx <= len(self.log) else 0
            entries = self.log[prev_idx:] if prev_idx < len(self.log) else []
            
            msg = Message(
                type="APPEND",
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=prev_idx,
                prev_log_term=prev_term,
                leader_commit=self.commit_index,
                entries=entries
            )
            self._broadcast(msg)
            self.stats['heartbeats_sent'] += 1
    
    def send_snr_report(self):
        """Broadcast  SNR """
        with self.lock:
            snr_data = {}
            for peer_id, info in self.peers.items():
                snr_data[peer_id] = round(info['snr'], 1)
            
            if not snr_data:
                return
            
            msg = Message(
                type="SNR_REPORT",
                term=self.current_term,
                sender_id=self.node_id,
                snr_report=snr_data
            )
            self._broadcast(msg)
            self.stats['snr_reports_sent'] += 1
    
    def propose_command(self, command: str) -> bool:
        """"""
        with self.lock:
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=command
            )
            self.log.append(entry)
            print(f" [] Log  #{entry.index}: {command}")
            self._replicate_log()
            return True
    
    def _replicate_log(self):
        """Log """
        with self.lock:
            min_next = min(self.next_index.values()) if self.next_index else len(self.log) + 1
            prev_idx = min_next - 1
            prev_term = self.log[prev_idx - 1].term if prev_idx > 0 and prev_idx <= len(self.log) else 0
            entries = self.log[prev_idx:] if prev_idx < len(self.log) else []
            
            if entries:
                msg = Message(
                    type="APPEND",
                    term=self.current_term,
                    sender_id=self.node_id,
                    prev_log_index=prev_idx,
                    prev_log_term=prev_term,
                    leader_commit=self.commit_index,
                    entries=entries
                )
                self._broadcast(msg)
                self.stats['entries_replicated'] += len(entries)
    
    def _handle_append_response(self, msg: Message):
        """"""
        peer_id = msg.sender_id
        with self.lock:
            if msg.success:
                self.next_index[peer_id] = msg.last_log_index + 1
                self.match_index[peer_id] = msg.last_log_index
                self._try_commit()
            else:
                self.next_index[peer_id] = max(1, self.next_index.get(peer_id, 1) - 1)
    
    def _try_commit(self):
        """"""
        old_commit = self.commit_index
        for n in range(len(self.log), self.commit_index, -1):
            count = 1
            for peer_id, match_idx in self.match_index.items():
                if match_idx >= n:
                    count += 1
            if count > self.total_nodes / 2:
                self.commit_index = n
                self._apply_committed()
                break
        if self.commit_index > old_commit:
            self.send_heartbeat()
    
    def _apply_committed(self):
        """Already Log """
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            print(f" []  #{entry.index}: {entry.command}")
    
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

    def recv_loop(self):
        """Receive """
        print(" Receive Start ")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = Message.from_json(data.decode('utf-8'))
                
                if msg and msg.sender_id != self.node_id:
                    self._update_peer(msg.sender_id, msg.phy_state)
                    
                    if msg.type == "APPEND_RESPONSE":
                        self._handle_append_response(msg)
                        
            except Exception as e:
                if self.running:
                    print(f"Receive Error: {e}")
    
    def main_loop(self):
        """"""
        print(" Start ")
        last_heartbeat = time.time()
        last_status = time.time()
        last_snr_report = time.time()
        
        while self.running:
            now = time.time()
            
            # Send Heartbeat 
            if now - last_heartbeat >= self.heartbeat_interval:
                self.send_heartbeat()
                last_heartbeat = now
            
            if now - last_snr_report >= self.snr_report_interval:
                self.send_snr_report()
                last_snr_report = now
            
            if now - last_status >= self.status_interval:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)
    
    def _print_status(self):
        """Status """
        with self.lock:
            print(f"\n [Leader SNR ] Target : {self.target_snr} dB")
            for peer_id in sorted(self.peers.keys()):
                info = self.peers[peer_id]
                snr = info['snr']
                diff = snr - self.target_snr
                if abs(diff) <= 2:
                    status = ""
                elif diff < -2:
                    status = " Gain "
                else:
                    status = " Gain "
                print(f"   Node {peer_id}: {snr:5.1f} dB ({diff:+.1f}) {status}")
            
            print(f"   Heartbeat : {self.stats['heartbeats_sent']}, SNR: {self.stats['snr_reports_sent']}")
    
    def input_loop(self):
        """"""
        print("   (Send '')")
        while self.running:
            try:
                cmd = input().strip()
                if not cmd:
                    cmd = ""
                self.propose_command(cmd)
            except EOFError:
                break
    
    def stop(self):
        self.running = False
        self.sock.close()


# ============================================================================
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Leader Node  ( SNR Broadcast )")
    parser.add_argument("--id", type=int, required=True, help="Node  ID")
    parser.add_argument("--role", type=str, default='leader', help=" ( leader)")
    parser.add_argument("--total", type=int, default=6, help="Node ")
    parser.add_argument("--tx", type=int, required=True, help="TX Port ")
    parser.add_argument("--rx", type=int, required=True, help="RX Port ")
    parser.add_argument("--target-snr", type=float, default=20.0, help="Target  SNR (dB)")
    parser.add_argument("--snr-report-interval", type=float, default=1.0, help="SNR  ()")
    parser.add_argument("--status-interval", type=float, default=2.0, help="Status  ()")
    args = parser.parse_args()
    
    if args.role != 'leader':
        print("   leader ")
        return
    
    node = LeaderWithSNRBroadcast(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx
    )
    node.target_snr = args.target_snr
    node.snr_report_interval = args.snr_report_interval
    node.status_interval = args.status_interval
    
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    t_input = threading.Thread(target=node.input_loop, daemon=True)
    t_input.start()
    
    try:
        node.main_loop()
    except KeyboardInterrupt:
        print("\n Stop ")
        node._print_status()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

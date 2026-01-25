#!/usr/bin/env python3
"""
带 SNR 广播的 Leader 节点
=========================

在固定领导者 Raft 基础上，Leader 周期性广播它观测到的各节点 SNR，
让 Follower 可以据此调整发射增益，实现自动功率控制。

新增消息类型:
    - SNR_REPORT: Leader -> All, 携带 {node_id: snr} 字典

使用方法:
    python3 raft_leader_snr_broadcast.py --id 1 --role leader --total 6 --tx 10001 --rx 20001

作者: V2V-Raft-SDR 项目
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
# 数据结构
# ============================================================================

@dataclass
class PhyState:
    """物理层状态"""
    snr: float = 0.0


@dataclass
class LogEntry:
    """日志条目"""
    term: int
    index: int
    command: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Message:
    """消息结构 (扩展版，支持 SNR_REPORT)"""
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
    # 新增: SNR 报告字段
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
            # snr_report 的 key 需要转回 int
            if 'snr_report' in data and data['snr_report']:
                data['snr_report'] = {int(k): v for k, v in data['snr_report'].items()}
            return Message(**data)
        except:
            return None


# ============================================================================
# Leader 节点 (带 SNR 广播)
# ============================================================================

class LeaderWithSNRBroadcast:
    """
    带 SNR 广播功能的 Leader
    
    在原有功能基础上，周期性广播观测到的各节点 SNR，
    让 Follower 可以据此调整发射增益。
    """
    
    def __init__(self, node_id: int, total_nodes: int, 
                 tx_port: int, rx_port: int):
        self.node_id = node_id
        self.role = 'leader'
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.leader_id = node_id
        
        # Raft 状态
        self.current_term = 1
        self.log: List[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0
        
        # Leader 状态
        self.next_index: Dict[int, int] = {}
        self.match_index: Dict[int, int] = {}
        for i in range(1, total_nodes + 1):
            if i != node_id:
                self.next_index[i] = 1
                self.match_index[i] = 0
        
        # 邻居 SNR 记录
        self.peers: Dict[int, dict] = {}
        
        # 配置
        self.heartbeat_interval = 0.2
        self.snr_threshold = 0.0        # Leader 不过滤
        self.status_interval = 2.0
        self.snr_report_interval = 1.0  # SNR 报告间隔
        self.target_snr = 20.0          # 目标 SNR
        
        # 统计
        self.stats = {
            'heartbeats_sent': 0,
            'snr_reports_sent': 0,
            'entries_replicated': 0,
            'commands_committed': 0,
        }
        
        # 网络
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f"👑 [节点 {node_id}] LEADER (SNR 广播版)")
        print(f"   TX:{tx_port} RX:{rx_port}")
        print(f"   目标 SNR: {self.target_snr} dB")

    def send_heartbeat(self):
        """发送心跳"""
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
        """广播 SNR 报告"""
        with self.lock:
            # 收集当前各节点 SNR
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
        """提交命令"""
        with self.lock:
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=command
            )
            self.log.append(entry)
            print(f"📝 [提交] 日志 #{entry.index}: {command}")
            self._replicate_log()
            return True
    
    def _replicate_log(self):
        """复制日志"""
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
        """处理复制响应"""
        peer_id = msg.sender_id
        with self.lock:
            if msg.success:
                self.next_index[peer_id] = msg.last_log_index + 1
                self.match_index[peer_id] = msg.last_log_index
                self._try_commit()
            else:
                self.next_index[peer_id] = max(1, self.next_index.get(peer_id, 1) - 1)
    
    def _try_commit(self):
        """尝试提交"""
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
        """应用已提交日志"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            print(f"✨ [共识] 执行命令 #{entry.index}: {entry.command}")
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """更新邻居 SNR"""
        now = time.time()
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        
        # 使用指数移动平均平滑 SNR
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
        """广播消息"""
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"❌ 发送失败: {e}")

    def recv_loop(self):
        """接收线程"""
        print("🔵 接收线程启动")
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
                    print(f"接收错误: {e}")
    
    def main_loop(self):
        """主循环"""
        print("🟢 主循环启动")
        last_heartbeat = time.time()
        last_status = time.time()
        last_snr_report = time.time()
        
        while self.running:
            now = time.time()
            
            # 发送心跳
            if now - last_heartbeat >= self.heartbeat_interval:
                self.send_heartbeat()
                last_heartbeat = now
            
            # 发送 SNR 报告
            if now - last_snr_report >= self.snr_report_interval:
                self.send_snr_report()
                last_snr_report = now
            
            # 打印状态
            if now - last_status >= self.status_interval:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)
    
    def _print_status(self):
        """打印状态"""
        with self.lock:
            print(f"\n📊 [Leader SNR 观测] 目标: {self.target_snr} dB")
            for peer_id in sorted(self.peers.keys()):
                info = self.peers[peer_id]
                snr = info['snr']
                diff = snr - self.target_snr
                if abs(diff) <= 2:
                    status = "✅"
                elif diff < -2:
                    status = "📉 需增加增益"
                else:
                    status = "📈 需降低增益"
                print(f"   Node {peer_id}: {snr:5.1f} dB ({diff:+.1f}) {status}")
            
            print(f"   心跳: {self.stats['heartbeats_sent']}, SNR报告: {self.stats['snr_reports_sent']}")
    
    def input_loop(self):
        """输入线程"""
        print("⌨️  输入命令 (直接回车发送'向左变道')")
        while self.running:
            try:
                cmd = input().strip()
                if not cmd:
                    cmd = "向左变道"
                self.propose_command(cmd)
            except EOFError:
                break
    
    def stop(self):
        self.running = False
        self.sock.close()


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Leader 节点 (带 SNR 广播)")
    parser.add_argument("--id", type=int, required=True, help="节点 ID")
    parser.add_argument("--role", type=str, default='leader', help="角色 (仅支持 leader)")
    parser.add_argument("--total", type=int, default=6, help="总节点数")
    parser.add_argument("--tx", type=int, required=True, help="TX 端口")
    parser.add_argument("--rx", type=int, required=True, help="RX 端口")
    parser.add_argument("--target-snr", type=float, default=20.0, help="目标 SNR (dB)")
    parser.add_argument("--snr-report-interval", type=float, default=1.0, help="SNR 报告间隔 (秒)")
    parser.add_argument("--status-interval", type=float, default=2.0, help="状态打印间隔 (秒)")
    args = parser.parse_args()
    
    if args.role != 'leader':
        print("⚠️  此脚本仅支持 leader 角色")
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
        print("\n🛑 停止")
        node._print_status()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

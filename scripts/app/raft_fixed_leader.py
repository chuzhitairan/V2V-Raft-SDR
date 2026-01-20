#!/usr/bin/env python3
"""
固定领导者 Raft 节点
====================
简化版 Raft，跳过选举过程，直接指定 Leader。
专注于共识决策（日志复制）过程的实验。

使用方法:
    # Leader (节点 1)
    python3 raft_fixed_leader.py --id 1 --role leader --total 6 --tx 10001 --rx 20001

    # Follower (节点 2-6)
    python3 raft_fixed_leader.py --id 2 --role follower --leader-id 1 --total 6 --tx 10002 --rx 20002
"""

import socket
import time
import json
import argparse
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict

BROADCAST_IP = "127.0.0.1"

# ==========================================
# 数据结构
# ==========================================

@dataclass
class PhyState:
    """信道状态"""
    snr: float = 0.0

@dataclass
class LogEntry:
    term: int
    index: int
    command: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class Message:
    """简化的消息结构"""
    type: str           # HEARTBEAT, APPEND, APPEND_RESPONSE
    term: int
    sender_id: int
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0
    last_log_index: int = 0
    success: bool = False
    phy_state: PhyState = field(default_factory=PhyState)

    def to_json(self):
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(json_str):
        try:
            data = json.loads(json_str)
            if 'phy_state' in data:
                data['phy_state'] = PhyState(**data['phy_state'])
            if 'entries' in data:
                data['entries'] = [LogEntry(**e) for e in data['entries']]
            return Message(**data)
        except:
            return None

# ==========================================
# 固定领导者节点
# ==========================================

class FixedLeaderNode:
    def __init__(self, node_id: int, role: str, total_nodes: int, 
                 tx_port: int, rx_port: int, leader_id: int = 1):
        self.node_id = node_id
        self.role = role  # 'leader' or 'follower'
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.leader_id = leader_id
        
        # 固定 term = 1 (不再选举)
        self.current_term = 1
        
        # 日志
        self.log: List[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0
        
        # Leader 状态
        if self.role == 'leader':
            self.next_index: Dict[int, int] = {}
            self.match_index: Dict[int, int] = {}
            for i in range(1, total_nodes + 1):
                if i != node_id:
                    self.next_index[i] = 1
                    self.match_index[i] = 0
        
        # 统计
        self.stats = {
            'heartbeats_sent': 0,
            'heartbeats_received': 0,
            'entries_replicated': 0,
            'commands_committed': 0,
            'messages_filtered': 0,
        }
        
        # 邻居 SNR 记录
        self.peers: Dict[int, dict] = {}
        
        # 参数
        self.heartbeat_interval = 0.2   # 心跳间隔 (秒)
        self.snr_threshold = 5.0        # SNR 过滤阈值
        
        # 网络
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        role_emoji = "👑" if role == 'leader' else "👥"
        print(f"{role_emoji} [节点 {node_id}] {role.upper()} | TX:{tx_port} RX:{rx_port}")
        if role == 'follower':
            print(f"   Leader: 节点 {leader_id}")

    # ==========================================
    # Leader 功能
    # ==========================================
    
    def send_heartbeat(self):
        """Leader 发送心跳 (同时携带未同步的日志，实现重传)"""
        if self.role != 'leader':
            return
        
        with self.lock:
            # 找出需要发送的日志 (从最小的 next_index 开始)
            min_next = min(self.next_index.values()) if self.next_index else len(self.log) + 1
            prev_idx = min_next - 1
            prev_term = self.log[prev_idx - 1].term if prev_idx > 0 and prev_idx <= len(self.log) else 0
            
            # 如果有未同步的日志，心跳也带上 (实现自动重传)
            entries = self.log[prev_idx:] if prev_idx < len(self.log) else []
            
            # 使用 APPEND 类型 (标准 Raft: 心跳就是空的 AppendEntries)
            msg = Message(
                type="APPEND",  # 改为 APPEND，统一处理
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=prev_idx,
                prev_log_term=prev_term,
                leader_commit=self.commit_index,
                entries=entries
            )
            self._broadcast(msg)
            self.stats['heartbeats_sent'] += 1
    
    def propose_command(self, command: str) -> bool:
        """Leader 提交新命令"""
        if self.role != 'leader':
            print(f"❌ 只有 Leader 可以提交命令")
            return False
        
        with self.lock:
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=command
            )
            self.log.append(entry)
            print(f"📝 [提交] 日志 #{entry.index}: {command}")
            
            # 立即复制
            self._replicate_log()
            return True
    
    def _replicate_log(self):
        """Leader 复制日志到 Follower"""
        with self.lock:
            # 找最小的 next_index
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
        """Leader 处理复制响应"""
        if self.role != 'leader':
            return
        
        peer_id = msg.sender_id
        with self.lock:
            if msg.success:
                self.next_index[peer_id] = msg.last_log_index + 1
                self.match_index[peer_id] = msg.last_log_index
                self._try_commit()
            else:
                # 回退重试
                self.next_index[peer_id] = max(1, self.next_index.get(peer_id, 1) - 1)
    
    def _try_commit(self):
        """检查并提交多数派已复制的日志"""
        old_commit = self.commit_index
        
        for n in range(len(self.log), self.commit_index, -1):
            # 计算已复制节点数 (包括自己)
            count = 1
            for peer_id, match_idx in self.match_index.items():
                if match_idx >= n:
                    count += 1
            
            if count > self.total_nodes / 2:
                self.commit_index = n
                self._apply_committed()
                break
        
        # 如果 commit_index 更新了，立即发送心跳通知 Follower
        if self.commit_index > old_commit:
            self.send_heartbeat()
    
    # ==========================================
    # Follower 功能
    # ==========================================
    
    def handle_append(self, msg: Message):
        """Follower 处理日志追加 (心跳也是空的 APPEND)"""
        if self.role != 'follower':
            return
        
        with self.lock:
            self.stats['heartbeats_received'] += 1  # 统计心跳/APPEND 次数
            
            reply = Message(
                type="APPEND_RESPONSE",
                term=self.current_term,
                sender_id=self.node_id,
                success=False,
                last_log_index=len(self.log)
            )
            
            # 日志一致性检查
            if msg.prev_log_index > 0:
                if len(self.log) < msg.prev_log_index:
                    self._broadcast(reply)
                    return
                if self.log[msg.prev_log_index - 1].term != msg.prev_log_term:
                    self.log = self.log[:msg.prev_log_index - 1]
                    self._broadcast(reply)
                    return
            
            # 追加日志 (检查是否已经有这些日志，避免重复处理)
            if msg.entries:
                new_entries = []
                for entry in msg.entries:
                    # 检查是否已存在
                    if entry.index > len(self.log):
                        new_entries.append(entry)
                    elif self.log[entry.index - 1].term != entry.term:
                        # term 冲突，截断后追加
                        self.log = self.log[:entry.index - 1]
                        new_entries.append(entry)
                
                if new_entries:
                    self.log.extend(new_entries)
                    print(f"📥 [复制] 收到 {len(new_entries)} 条新日志，当前长度: {len(self.log)}")
            
            reply.success = True
            reply.last_log_index = len(self.log)
            
            # 更新 commit
            if msg.leader_commit > self.commit_index:
                self.commit_index = min(msg.leader_commit, len(self.log))
                self._apply_committed()
            
            self._broadcast(reply)
    
    # ==========================================
    # 通用功能
    # ==========================================
    
    def _apply_committed(self):
        """应用已提交的日志"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            print(f"✨ [共识] 执行命令 #{entry.index}: {entry.command}")
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """记录邻居 SNR"""
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        self.peers[sender_id]['snr'] = phy_state.snr
        self.peers[sender_id]['last_seen'] = time.time()
        self.peers[sender_id]['count'] += 1
    
    def _broadcast(self, msg: Message):
        """广播消息"""
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"❌ 发送失败: {e}")
    
    # ==========================================
    # 主循环
    # ==========================================
    
    def recv_loop(self):
        """接收线程"""
        print("🔵 接收线程启动")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = Message.from_json(data.decode('utf-8'))
                
                if msg and msg.sender_id != self.node_id:
                    # SNR 过滤
                    if msg.phy_state.snr < self.snr_threshold:
                        self.stats['messages_filtered'] += 1
                        continue
                    
                    # 记录邻居
                    self._update_peer(msg.sender_id, msg.phy_state)
                    
                    # 处理消息 (HEARTBEAT 和 APPEND 统一用 handle_append 处理)
                    if msg.type == "HEARTBEAT":
                        # 兼容旧格式，但现在心跳用 APPEND 类型
                        self.handle_append(msg)
                    elif msg.type == "APPEND":
                        self.handle_append(msg)
                    elif msg.type == "APPEND_RESPONSE":
                        self._handle_append_response(msg)
                        
            except Exception as e:
                if self.running:
                    print(f"接收错误: {e}")
    
    def main_loop(self):
        """主循环"""
        print("🟢 主循环启动")
        last_heartbeat = time.time()
        last_status = time.time()
        
        while self.running:
            now = time.time()
            
            # Leader 发心跳
            if self.role == 'leader':
                if now - last_heartbeat >= self.heartbeat_interval:
                    self.send_heartbeat()
                    last_heartbeat = now
            
            # 定期打印状态 (每 10 秒)
            if now - last_status >= 10.0:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)
    
    def _print_status(self):
        """打印状态"""
        with self.lock:
            peers_str = ", ".join([f"N{p}:{d['snr']:.1f}dB" for p, d in sorted(self.peers.items())])
            print(f"📊 [状态] 日志:{len(self.log)} 提交:{self.commit_index} 执行:{self.last_applied} | 邻居: {peers_str or '无'}")
            if self.role == 'leader':
                # 显示 match_index 帮助调试
                match_str = ", ".join([f"N{p}:{idx}" for p, idx in sorted(self.match_index.items())])
                print(f"   心跳: {self.stats['heartbeats_sent']}, 复制: {self.stats['entries_replicated']} | match: {match_str or '无'}")
            else:
                print(f"   心跳接收: {self.stats['heartbeats_received']}, 过滤: {self.stats['messages_filtered']}")
    
    def input_loop(self):
        """用户输入 (仅 Leader)"""
        if self.role != 'leader':
            return
        
        print("⌨️  输入线程启动 (输入命令后按回车提交，或直接回车发送'向左变道')")
        while self.running:
            try:
                cmd = input().strip()
                if not cmd:
                    cmd = "向左变道"
                self.propose_command(cmd)
            except EOFError:
                break
    
    def stop(self):
        """停止节点"""
        self.running = False
        self.sock.close()

# ==========================================
# 主程序
# ==========================================

def main():
    parser = argparse.ArgumentParser(description="固定领导者 Raft 节点")
    parser.add_argument("--id", type=int, required=True, help="节点 ID")
    parser.add_argument("--role", type=str, required=True, choices=['leader', 'follower'],
                       help="节点角色: leader 或 follower")
    parser.add_argument("--total", type=int, default=6, help="总节点数 [default: 6]")
    parser.add_argument("--tx", type=int, required=True, help="TX 端口 (发给 PHY)")
    parser.add_argument("--rx", type=int, required=True, help="RX 端口 (从 PHY 收)")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader 节点 ID [default: 1]")
    parser.add_argument("--snr-threshold", type=float, default=5.0, help="SNR 过滤阈值 [default: 5.0]")
    args = parser.parse_args()
    
    # 验证
    if args.role == 'leader' and args.id != args.leader_id:
        print(f"⚠️  警告: 角色为 leader 但 ID({args.id}) != leader-id({args.leader_id})")
    
    node = FixedLeaderNode(
        node_id=args.id,
        role=args.role,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx,
        leader_id=args.leader_id
    )
    node.snr_threshold = args.snr_threshold
    print(f"📡 SNR 过滤阈值: {node.snr_threshold} dB")
    
    # 启动线程
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    if args.role == 'leader':
        t_input = threading.Thread(target=node.input_loop, daemon=True)
        t_input.start()
    
    try:
        node.main_loop()
    except KeyboardInterrupt:
        print("\n🛑 停止运行")
        node._print_status()
    finally:
        node.stop()

if __name__ == "__main__":
    main()

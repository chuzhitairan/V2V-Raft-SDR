#!/usr/bin/env python3
"""
固定领导者 Raft 节点 (Fixed Leader Raft Node)
=============================================

简化版 Raft 共识协议实现，跳过选举过程，启动时直接指定 Leader。
专注于共识决策（日志复制）过程的实验验证。

与标准 Raft 的区别:
    - 无选举: Leader 在启动时通过 --role 参数指定，不会发生选举
    - 固定 Term: current_term 始终为 1，不会递增
    - 心跳即 APPEND: 使用统一的 APPEND 消息类型，空的 APPEND 就是心跳

核心流程:
    1. Leader 周期性发送心跳 (APPEND 消息，可携带未同步的日志)
    2. Follower 收到 APPEND 后追加日志，回复 APPEND_RESPONSE
    3. Leader 统计多数派确认后更新 commit_index
    4. 所有节点应用已提交的日志

消息流:
    Leader  ──APPEND──>  Follower
    Leader <──APPEND_RESPONSE──  Follower

使用方法:
    # 启动 Leader (节点 1)
    python3 raft_fixed_leader.py --id 1 --role leader --total 6 --tx 10001 --rx 20001

    # 启动 Follower (节点 2-6)
    python3 raft_fixed_leader.py --id 2 --role follower --leader-id 1 --total 6 --tx 10002 --rx 20002

作者: V2V-Raft-SDR 项目
"""

import socket
import time
import json
import argparse
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict

# ============================================================================
# 常量配置
# ============================================================================

BROADCAST_IP = "127.0.0.1"  # 本地回环地址，通过 PHY 层转发实现无线广播


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class PhyState:
    """
    物理层状态信息
    
    由 PHY 层在接收消息时附加，表示接收到该消息时的信道质量。
    用于 SNR 过滤，只接受信号质量足够好的消息。
    
    Attributes:
        snr: 信噪比 (Signal-to-Noise Ratio)，单位 dB。
             值越高表示信号质量越好，典型值 10-30 dB。
    """
    snr: float = 0.0


@dataclass
class LogEntry:
    """
    Raft 日志条目
    
    日志是 Raft 共识的核心数据结构。每个命令被封装为一个日志条目，
    Leader 将日志复制到 Follower，多数派确认后提交执行。
    
    Attributes:
        term:      创建该条目时的任期号 (本实现固定为 1)
        index:     日志索引，从 1 开始递增，全局唯一
        command:   要执行的命令字符串，如 "向左变道"
        timestamp: 创建时间戳，用于调试和统计
    """
    term: int                                    # 任期号
    index: int                                   # 日志索引 (1-based)
    command: str                                 # 命令内容
    timestamp: float = field(default_factory=time.time)  # 创建时间


@dataclass
class Message:
    """
    Raft 协议消息
    
    所有节点间通信都使用此消息格式。通过 type 字段区分消息类型。
    
    消息类型:
        - APPEND:          Leader -> Follower, 心跳 + 日志复制
        - APPEND_RESPONSE: Follower -> Leader, 确认日志复制结果
    
    Attributes:
        type:           消息类型 ("APPEND" 或 "APPEND_RESPONSE")
        term:           发送者的任期号 (固定为 1)
        sender_id:      发送者节点 ID
        prev_log_index: APPEND 消息专用，新日志之前的日志索引
        prev_log_term:  APPEND 消息专用，新日志之前的日志任期
        entries:        APPEND 消息专用，要复制的日志条目列表
        leader_commit:  APPEND 消息专用，Leader 的 commit_index
        last_log_index: APPEND_RESPONSE 专用，Follower 的最后日志索引
        success:        APPEND_RESPONSE 专用，是否成功追加日志
        phy_state:      物理层状态，由 PHY 层在接收时附加
    """
    type: str                                           # 消息类型
    term: int                                           # 任期号
    sender_id: int                                      # 发送者 ID
    prev_log_index: int = 0                             # 前一条日志的索引
    prev_log_term: int = 0                              # 前一条日志的任期
    entries: List[LogEntry] = field(default_factory=list)  # 日志条目列表
    leader_commit: int = 0                              # Leader 的提交索引
    last_log_index: int = 0                             # 响应者的最后日志索引
    success: bool = False                               # 是否成功
    phy_state: PhyState = field(default_factory=PhyState)  # 物理层状态

    def to_json(self) -> str:
        """序列化为 JSON 字符串，用于网络传输"""
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(json_str: str) -> 'Message':
        """
        从 JSON 字符串反序列化
        
        Args:
            json_str: JSON 格式的消息字符串
            
        Returns:
            Message 对象，解析失败返回 None
        """
        try:
            data = json.loads(json_str)
            # 嵌套对象需要手动转换
            if 'phy_state' in data:
                data['phy_state'] = PhyState(**data['phy_state'])
            if 'entries' in data:
                data['entries'] = [LogEntry(**e) for e in data['entries']]
            return Message(**data)
        except:
            return None


# ============================================================================
# 固定领导者节点实现
# ============================================================================

class FixedLeaderNode:
    """
    固定领导者 Raft 节点
    
    实现简化版 Raft 协议，跳过选举阶段，专注于日志复制和多数派提交。
    
    核心状态 (所有节点):
        - current_term:  当前任期 (固定为 1)
        - log:           日志条目列表
        - commit_index:  已提交的最大日志索引
        - last_applied:  已应用到状态机的最大日志索引
    
    Leader 额外状态:
        - next_index[]:  每个 Follower 下次要发送的日志索引
        - match_index[]: 每个 Follower 已确认复制的最大日志索引
    
    线程模型:
        - recv_loop:  接收线程，处理所有收到的消息
        - main_loop:  主线程，Leader 定时发送心跳
        - input_loop: 输入线程 (仅 Leader)，接收用户命令
    """
    
    def __init__(self, node_id: int, role: str, total_nodes: int, 
                 tx_port: int, rx_port: int, leader_id: int = 1):
        """
        初始化节点
        
        Args:
            node_id:     本节点 ID (1, 2, 3, ...)
            role:        角色 ('leader' 或 'follower')
            total_nodes: 集群总节点数
            tx_port:     发送端口 (发给 PHY 层)
            rx_port:     接收端口 (从 PHY 层收)
            leader_id:   Leader 节点的 ID
        """
        # ----- 基本信息 -----
        self.node_id = node_id
        self.role = role              # 'leader' 或 'follower'
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.leader_id = leader_id
        
        # ----- Raft 核心状态 -----
        # 固定 term = 1 (不再选举，简化实现)
        self.current_term = 1
        
        # 日志相关
        self.log: List[LogEntry] = []  # 日志条目列表，索引从 0 开始存储
        self.commit_index = 0          # 已知已提交的最大日志索引
        self.last_applied = 0          # 已应用到状态机的最大日志索引
        
        # ----- Leader 专用状态 -----
        # next_index[i]:  发给节点 i 的下一条日志索引 (初始化为 1)
        # match_index[i]: 节点 i 已确认复制的最大日志索引 (初始化为 0)
        if self.role == 'leader':
            self.next_index: Dict[int, int] = {}
            self.match_index: Dict[int, int] = {}
            for i in range(1, total_nodes + 1):
                if i != node_id:
                    self.next_index[i] = 1   # 从第 1 条日志开始
                    self.match_index[i] = 0  # 尚未确认任何日志
        
        # ----- 统计信息 -----
        self.stats = {
            'heartbeats_sent': 0,      # 发送的心跳数 (Leader)
            'heartbeats_received': 0,  # 接收的心跳数 (Follower)
            'entries_replicated': 0,   # 复制的日志条目数
            'commands_committed': 0,   # 已提交的命令数
            'messages_filtered': 0,    # 被 SNR 过滤的消息数
        }
        
        # ----- 邻居状态 -----
        # 记录每个邻居的 SNR 和最后通信时间，用于网络状态监控
        self.peers: Dict[int, dict] = {}
        
        # ----- 配置参数 -----
        self.heartbeat_interval = 0.2  # 心跳发送间隔 (秒)
        self.snr_threshold = 5.0       # SNR 过滤阈值 (dB)
        self.status_interval = 10.0    # 状态打印间隔 (秒)
        
        # ----- 网络通信 -----
        self.lock = threading.RLock()  # 可重入锁，保护共享状态
        self.running = True            # 运行标志
        
        # 创建 UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        # ----- 启动信息 -----
        role_emoji = "👑" if role == 'leader' else "👥"
        print(f"{role_emoji} [节点 {node_id}] {role.upper()} | TX:{tx_port} RX:{rx_port}")
        if role == 'follower':
            print(f"   Leader: 节点 {leader_id}")

    # ========================================================================
    # Leader 功能
    # ========================================================================
    
    def send_heartbeat(self):
        """
        Leader 发送心跳
        
        在 Raft 中，心跳是空的 AppendEntries RPC。本实现中，心跳同时
        携带未同步的日志，实现自动重传，提高可靠性。
        
        工作流程:
            1. 找出所有 Follower 中最小的 next_index
            2. 从该位置开始获取未同步的日志
            3. 构造 APPEND 消息广播
        
        注意: 只有 Leader 会调用此方法
        """
        if self.role != 'leader':
            return
        
        with self.lock:
            # Step 1: 确定要发送的日志范围
            # 使用最小的 next_index，确保落后最多的 Follower 也能收到
            min_next = min(self.next_index.values()) if self.next_index else len(self.log) + 1
            prev_idx = min_next - 1
            
            # 获取 prev_log_term (用于一致性检查)
            prev_term = 0
            if prev_idx > 0 and prev_idx <= len(self.log):
                prev_term = self.log[prev_idx - 1].term
            
            # Step 2: 获取需要发送的日志条目
            # 如果有未同步的日志，心跳也带上 (实现自动重传)
            entries = self.log[prev_idx:] if prev_idx < len(self.log) else []
            
            # Step 3: 构造并广播 APPEND 消息
            # 标准 Raft: 心跳就是空的 AppendEntries
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
    
    def propose_command(self, command: str) -> bool:
        """
        Leader 提交新命令 (客户端请求入口)
        
        Raft 中只有 Leader 可以接收客户端请求。命令首先被追加到本地日志，
        然后通过日志复制发送给 Follower，多数派确认后提交执行。
        
        Args:
            command: 要执行的命令字符串
            
        Returns:
            True 表示命令已追加到日志，False 表示失败
            
        注意: 返回 True 不代表命令已提交，提交需要等待多数派确认
        """
        if self.role != 'leader':
            print(f"❌ 只有 Leader 可以提交命令")
            return False
        
        with self.lock:
            # 创建新的日志条目
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,  # 日志索引从 1 开始
                command=command
            )
            self.log.append(entry)
            print(f"📝 [提交] 日志 #{entry.index}: {command}")
            
            # 立即尝试复制到 Follower
            self._replicate_log()
            return True
    
    def _replicate_log(self):
        """
        Leader 复制日志到 Follower
        
        遍历所有 Follower，发送它们缺失的日志条目。
        使用最小 next_index 策略，一次广播覆盖所有 Follower。
        """
        with self.lock:
            # 找最小的 next_index，确定发送起点
            min_next = min(self.next_index.values()) if self.next_index else len(self.log) + 1
            prev_idx = min_next - 1
            
            # 获取 prev_log_term
            prev_term = 0
            if prev_idx > 0 and prev_idx <= len(self.log):
                prev_term = self.log[prev_idx - 1].term
            
            # 获取要发送的日志条目
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
        """
        Leader 处理 Follower 的日志复制响应
        
        根据响应结果更新 next_index 和 match_index，并检查是否可以提交。
        
        Args:
            msg: APPEND_RESPONSE 消息
            
        处理逻辑:
            - success=True:  更新 next_index 和 match_index，尝试提交
            - success=False: 回退 next_index，下次心跳会自动重发
        """
        if self.role != 'leader':
            return
        
        peer_id = msg.sender_id
        with self.lock:
            if msg.success:
                # 复制成功，更新该 Follower 的进度
                self.next_index[peer_id] = msg.last_log_index + 1
                self.match_index[peer_id] = msg.last_log_index
                
                # 尝试提交新的日志
                self._try_commit()
            else:
                # 复制失败 (日志不一致)，回退 next_index 重试
                # 下次心跳会携带更早的日志
                self.next_index[peer_id] = max(1, self.next_index.get(peer_id, 1) - 1)
    
    def _try_commit(self):
        """
        检查并提交多数派已复制的日志
        
        Raft 提交规则: 如果某条日志已被复制到多数派节点，则可以提交。
        从最新的日志开始检查，找到第一个满足多数派的索引。
        
        提交后会立即发送心跳，通知 Follower 更新 commit_index。
        """
        old_commit = self.commit_index
        
        # 从最新日志向前检查
        for n in range(len(self.log), self.commit_index, -1):
            # 统计已复制到该索引的节点数 (包括自己)
            count = 1  # Leader 自己
            for peer_id, match_idx in self.match_index.items():
                if match_idx >= n:
                    count += 1
            
            # 检查是否达到多数派 (> N/2)
            if count > self.total_nodes / 2:
                self.commit_index = n
                self._apply_committed()  # 应用已提交的日志
                break
        
        # 如果 commit_index 更新了，立即发送心跳通知 Follower
        # 这样 Follower 可以更快地知道日志已提交
        if self.commit_index > old_commit:
            self.send_heartbeat()

    # ========================================================================
    # Follower 功能
    # ========================================================================
    
    def handle_append(self, msg: Message):
        """
        Follower 处理 APPEND 消息 (心跳 + 日志复制)
        
        这是 Follower 最重要的方法，处理来自 Leader 的所有 APPEND 请求。
        
        Args:
            msg: APPEND 消息
            
        处理流程:
            1. 日志一致性检查 (prev_log_index, prev_log_term)
            2. 追加新的日志条目 (去重处理)
            3. 更新 commit_index 并应用已提交日志
            4. 回复 APPEND_RESPONSE
        """
        if self.role != 'follower':
            return
        
        with self.lock:
            self.stats['heartbeats_received'] += 1
            
            # 构造响应消息 (默认失败)
            reply = Message(
                type="APPEND_RESPONSE",
                term=self.current_term,
                sender_id=self.node_id,
                success=False,
                last_log_index=len(self.log)
            )
            
            # ----- Step 1: 日志一致性检查 -----
            # Raft 要求日志是连续的，prev_log 必须匹配
            if msg.prev_log_index > 0:
                # 检查本地日志是否足够长
                if len(self.log) < msg.prev_log_index:
                    # 缺失日志，返回失败让 Leader 回退
                    self._broadcast(reply)
                    return
                
                # 检查 prev_log_term 是否匹配
                if self.log[msg.prev_log_index - 1].term != msg.prev_log_term:
                    # term 不匹配，截断冲突的日志
                    self.log = self.log[:msg.prev_log_index - 1]
                    self._broadcast(reply)
                    return
            
            # ----- Step 2: 追加新日志 (去重处理) -----
            if msg.entries:
                new_entries = []
                for entry in msg.entries:
                    if entry.index > len(self.log):
                        # 新条目，追加
                        new_entries.append(entry)
                    elif self.log[entry.index - 1].term != entry.term:
                        # term 冲突，截断后追加
                        self.log = self.log[:entry.index - 1]
                        new_entries.append(entry)
                    # else: 已存在且匹配，跳过
                
                if new_entries:
                    self.log.extend(new_entries)
                    print(f"📥 [复制] 收到 {len(new_entries)} 条新日志，当前长度: {len(self.log)}")
            
            # ----- Step 3: 更新 commit_index -----
            # Follower 的 commit_index = min(leader_commit, len(log))
            if msg.leader_commit > self.commit_index:
                self.commit_index = min(msg.leader_commit, len(self.log))
                self._apply_committed()
            
            # ----- Step 4: 回复成功 -----
            reply.success = True
            reply.last_log_index = len(self.log)
            self._broadcast(reply)

    # ========================================================================
    # 通用功能
    # ========================================================================
    
    def _apply_committed(self):
        """
        应用已提交的日志到状态机
        
        遍历 [last_applied + 1, commit_index] 范围内的日志，依次执行。
        在实际系统中，这里会调用真正的状态机执行命令。
        """
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            print(f"✨ [共识] 执行命令 #{entry.index}: {entry.command}")
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """
        更新邻居节点的状态信息
        
        记录每个邻居的 SNR 和最后通信时间，用于:
            - 网络状态监控
            - Leader 选择最佳转发路径 (扩展功能)
        
        Args:
            sender_id: 发送者节点 ID
            phy_state: 物理层状态
        """
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        self.peers[sender_id]['snr'] = phy_state.snr
        self.peers[sender_id]['last_seen'] = time.time()
        self.peers[sender_id]['count'] += 1
    
    def _broadcast(self, msg: Message):
        """
        广播消息 (通过 PHY 层)
        
        消息发送到本地 TX 端口，由 PHY 层通过 SDR 进行无线广播。
        
        Args:
            msg: 要发送的消息
        """
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"❌ 发送失败: {e}")

    # ========================================================================
    # 主循环
    # ========================================================================
    
    def recv_loop(self):
        """
        接收线程 - 处理所有收到的消息
        
        持续监听 RX 端口，解析消息并分发到相应的处理函数。
        
        处理流程:
            1. 接收 UDP 数据包
            2. 解析 JSON 消息
            3. SNR 过滤 (丢弃信号质量差的消息)
            4. 更新邻居状态
            5. 根据消息类型分发处理
        """
        print("🔵 接收线程启动")
        
        while self.running:
            try:
                # 接收数据 (阻塞)
                data, _ = self.sock.recvfrom(4096)
                msg = Message.from_json(data.decode('utf-8'))
                
                if msg and msg.sender_id != self.node_id:
                    # ----- SNR 过滤 -----
                    # 信号质量低于阈值的消息直接丢弃
                    if msg.phy_state.snr < self.snr_threshold:
                        self.stats['messages_filtered'] += 1
                        continue
                    
                    # ----- 更新邻居状态 -----
                    self._update_peer(msg.sender_id, msg.phy_state)
                    
                    # ----- 消息分发 -----
                    if msg.type == "HEARTBEAT":
                        # 兼容旧格式 (现在心跳统一用 APPEND 类型)
                        self.handle_append(msg)
                    elif msg.type == "APPEND":
                        self.handle_append(msg)
                    elif msg.type == "APPEND_RESPONSE":
                        self._handle_append_response(msg)
                        
            except Exception as e:
                if self.running:
                    print(f"接收错误: {e}")
    
    def main_loop(self):
        """
        主循环 - Leader 定时发送心跳，所有节点定时打印状态
        
        职责:
            - Leader: 周期性发送心跳
            - 所有节点: 定期打印运行状态
        """
        print("🟢 主循环启动")
        last_heartbeat = time.time()
        last_status = time.time()
        
        while self.running:
            now = time.time()
            
            # Leader 定时发送心跳
            if self.role == 'leader':
                if now - last_heartbeat >= self.heartbeat_interval:
                    self.send_heartbeat()
                    last_heartbeat = now
            
            # 定期打印状态
            if now - last_status >= self.status_interval:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)  # 避免 CPU 空转
    
    def _print_status(self):
        """
        打印当前状态 (调试用)
        
        输出内容:
            - 日志数量、commit_index、last_applied
            - 邻居 SNR 信息
            - Leader: 心跳数、复制数、match_index
            - Follower: 心跳接收数、过滤数
        """
        with self.lock:
            # 邻居信息
            peers_str = ", ".join([
                f"N{p}:{d['snr']:.1f}dB" 
                for p, d in sorted(self.peers.items())
            ])
            
            print(f"📊 [状态] 日志:{len(self.log)} 提交:{self.commit_index} "
                  f"执行:{self.last_applied} | 邻居: {peers_str or '无'}")
            
            if self.role == 'leader':
                # Leader 额外显示 match_index
                match_str = ", ".join([
                    f"N{p}:{idx}" 
                    for p, idx in sorted(self.match_index.items())
                ])
                print(f"   心跳: {self.stats['heartbeats_sent']}, "
                      f"复制: {self.stats['entries_replicated']} | match: {match_str or '无'}")
            else:
                print(f"   心跳接收: {self.stats['heartbeats_received']}, "
                      f"过滤: {self.stats['messages_filtered']}")
    
    def input_loop(self):
        """
        用户输入线程 (仅 Leader)
        
        接收用户从终端输入的命令，调用 propose_command 提交到 Raft。
        直接按回车会发送默认命令 "向左变道"。
        """
        if self.role != 'leader':
            return
        
        print("⌨️  输入线程启动 (输入命令后按回车提交，或直接回车发送'向左变道')")
        
        while self.running:
            try:
                cmd = input().strip()
                if not cmd:
                    cmd = "向左变道"  # 默认命令
                self.propose_command(cmd)
            except EOFError:
                break
    
    def stop(self):
        """停止节点，释放资源"""
        self.running = False
        self.sock.close()


# ============================================================================
# 主程序入口
# ============================================================================

def main():
    """
    命令行入口
    
    参数说明:
        --id:           节点 ID (必须，1-N)
        --role:         角色 (必须，leader 或 follower)
        --total:        总节点数 (默认 6)
        --tx:           TX 端口 (必须，发给 PHY 层)
        --rx:           RX 端口 (必须，从 PHY 层收)
        --leader-id:    Leader 节点 ID (默认 1)
        --snr-threshold: SNR 过滤阈值 (默认 5.0 dB)
    """
    parser = argparse.ArgumentParser(
        description="固定领导者 Raft 节点",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 启动 Leader
    python3 raft_fixed_leader.py --id 1 --role leader --total 6 --tx 10001 --rx 20001

    # 启动 Follower  
    python3 raft_fixed_leader.py --id 2 --role follower --total 6 --tx 10002 --rx 20002
        """
    )
    parser.add_argument("--id", type=int, required=True, 
                        help="节点 ID (1, 2, 3, ...)")
    parser.add_argument("--role", type=str, required=True, 
                        choices=['leader', 'follower'],
                        help="节点角色: leader 或 follower")
    parser.add_argument("--total", type=int, default=6, 
                        help="总节点数 [default: 6]")
    parser.add_argument("--tx", type=int, required=True, 
                        help="TX 端口 (发给 PHY 层)")
    parser.add_argument("--rx", type=int, required=True, 
                        help="RX 端口 (从 PHY 层收)")
    parser.add_argument("--leader-id", type=int, default=1, 
                        help="Leader 节点 ID [default: 1]")
    parser.add_argument("--snr-threshold", type=float, default=5.0, 
                        help="SNR 过滤阈值 (dB) [default: 5.0]")
    parser.add_argument("--status-interval", type=float, default=2.0, 
                        help="状态打印间隔 (秒) [default: 2.0]")
    args = parser.parse_args()
    
    # 参数验证
    if args.role == 'leader' and args.id != args.leader_id:
        print(f"⚠️  警告: 角色为 leader 但 ID({args.id}) != leader-id({args.leader_id})")
    
    # 创建节点
    node = FixedLeaderNode(
        node_id=args.id,
        role=args.role,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx,
        leader_id=args.leader_id
    )
    node.snr_threshold = args.snr_threshold
    node.status_interval = args.status_interval
    print(f"📡 SNR 过滤阈值: {node.snr_threshold} dB")
    print(f"📊 状态打印间隔: {node.status_interval} 秒")
    
    # 启动接收线程
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    # Leader 启动输入线程
    if args.role == 'leader':
        t_input = threading.Thread(target=node.input_loop, daemon=True)
        t_input.start()
    
    # 主循环 (阻塞)
    try:
        node.main_loop()
    except KeyboardInterrupt:
        print("\n🛑 停止运行")
        node._print_status()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

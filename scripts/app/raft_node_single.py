import socket
import time
import random
import json
import argparse
import threading
import math
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from collections import deque

# --- 全局配置 ---
BROADCAST_IP = "127.0.0.1"

# ==========================================
# 1. 数据结构定义
# ==========================================

@dataclass
class PhyState:
    """车辆物理状态 & 信道状态"""
    pos: List[float] = field(default_factory=lambda: [0.0, 0.0])
    vel: List[float] = field(default_factory=lambda: [0.0, 0.0])
    snr: float = 0.0  # 接收方看到的发送方信号质量

@dataclass
class LogEntry:
    term: int
    index: int
    command: str
    is_emergency: bool = False # RUBICONe: 紧急消息标记
    timestamp: float = field(default_factory=time.time)

@dataclass
class RaftMessage:
    """标准 Raft 消息结构 (融合 RUBICONe 扩展)"""
    type: str  # "RequestVote", "VoteResponse", "AppendEntries", "AppendEntriesResponse"
    term: int
    sender_id: int
    
    # 日志复制相关 (Standard Raft)
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0
    
    # 投票相关
    last_log_index: int = 0
    last_log_term: int = 0
    
    # 响应字段
    success: bool = False
    vote_granted: bool = False
    
    # RUBICONe 扩展: 携带物理层状态
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
            return RaftMessage(**data)
        except Exception as e:
            return None

# ==========================================
# 2. 核心功能模块: 节点逻辑
# ==========================================

class RaftNode:
    STATE_FOLLOWER = "Follower"
    STATE_CANDIDATE = "Candidate"
    STATE_LEADER = "Leader"

    def __init__(self, node_id, total_nodes, tx_port, rx_port):
        self.node_id = node_id
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        
        # --- 1. 持久性状态 (需要落盘，此处简化为内存) ---
        self.current_term = 0
        self.voted_for = None
        self.log: List[LogEntry] = []  # 日志条目
        
        # --- 2. 易失性状态 ---
        self.commit_index = 0
        self.last_applied = 0
        self.state = self.STATE_FOLLOWER
        
        # --- 3. Leader 专属状态 ---
        self.next_index = {}   # 发给每个 Follower 的下一条日志索引
        self.match_index = {}  # 每个 Follower 已复制的最高索引
        
        # --- 4. RUBICONe 扩展状态 ---
        # 邻居表: {node_id: {'snr_history': deque, 'last_seen': time}}
        self.peers = {} 
        self.snr_window_size = 5 # 滑动窗口平滑 SNR
        
        # --- 5. 系统控制 ---
        self.lock = threading.RLock()
        self.last_heartbeat_rx = time.time()
        self.running = True
        
        # 参数配置
        self.T_base = 3.0       # 基础超时时间 (秒)
        self.alpha = 50.0       # RUBICONe 权重因子
        self.heartbeat_interval = 1.0
        
        # 网络初始化
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f"🚗 [节点 {self.node_id}] 初始化完成 | 端口: {self.rx_port}")

    # ----------------------------------------------------------------
    #  RUBICONe 核心: 基于物理层的自适应逻辑
    # ----------------------------------------------------------------
    
    def _update_peer_state(self, sender_id, phy_state):
        """更新邻居状态并记录 SNR"""
        with self.lock:
            if sender_id not in self.peers:
                self.peers[sender_id] = {
                    'snr_history': deque(maxlen=self.snr_window_size),
                    'last_seen': time.time()
                }
            
            # 记录 SNR (从底层注入的)
            # 注意：这里的 snr 是对方发包时被我方接收到的信噪比
            if phy_state.snr != 0: 
                self.peers[sender_id]['snr_history'].append(phy_state.snr)
            self.peers[sender_id]['last_seen'] = time.time()

    def _calculate_election_timeout(self):
        """
        [论文公式 (2)] 自适应超时计算
        T = (1 + alpha / sum(gamma)) * T_base
        """
        with self.lock:
            # 1. 计算所有活跃邻居的平均 SNR 总和 (Gamma)
            total_gamma = 0.0
            active_peers = 0
            now = time.time()
            
            for pid, info in self.peers.items():
                # 剔除 10秒没消息的死节点
                if now - info['last_seen'] < 10.0 and len(info['snr_history']) > 0:
                    avg_snr = sum(info['snr_history']) / len(info['snr_history'])
                    total_gamma += avg_snr
                    active_peers += 1
            
            # --- [修复] 孤立节点快速启动 ---
            if active_peers == 0:
                # 如果没有邻居，退回标准 Raft 逻辑 (Factor=1)，而不是惩罚
                factor = 1.0 
                # [可选] 也可以稍微设大一点点，让有连接的节点优先
                # factor = 1.2 
            else:
                # 避免除零
                if total_gamma < 1.0: total_gamma = 1.0
                
                # SNR 越高，Timeout 越短 -> 越容易成为 Leader
                factor = 1.0 + (self.alpha / total_gamma)
            
            # 增加随机抖动 (10% ~ 20%)
            jitter = random.uniform(0.1, 0.2) * self.T_base
            timeout = (factor * self.T_base) + jitter
            
            # 打印调试信息，让你知道它在等多久 (调试完可注释)
            # print(f"[Timer] Peers={active_peers} | Gamma={total_gamma:.1f} | Timeout={timeout:.2f}s")
            return timeout

    # ----------------------------------------------------------------
    #  标准 Raft 核心逻辑 (Safety & Consistency)
    # ----------------------------------------------------------------

    def _get_last_log_index_and_term(self):
        if len(self.log) > 0:
            return len(self.log), self.log[-1].term
        return 0, 0

    def start_election(self):
        with self.lock:
            self.state = self.STATE_CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            votes_received = 1
            self.last_heartbeat_rx = time.time()
            
            last_idx, last_term = self._get_last_log_index_and_term()
            
            print(f"🔥 [选举] 发起 Term {self.current_term}")
            
            # 构造 RequestVote 消息
            msg = RaftMessage(
                type="RequestVote",
                term=self.current_term,
                sender_id=self.node_id,
                last_log_index=last_idx,
                last_log_term=last_term,
                phy_state=PhyState(snr=0) # 发送时不带 SNR，由接收方注入
            )
            self._broadcast(msg)
            
            # 快速检查单节点情况
            if votes_received > self.total_nodes / 2:
                self.become_leader()

    def handle_request_vote(self, msg: RaftMessage):
        """处理投票请求 (包含安全性检查)"""
        with self.lock:
            reply = RaftMessage(
                type="VoteResponse",
                term=self.current_term,
                sender_id=self.node_id,
                vote_granted=False
            )

            # 1. Term 检查
            if msg.term < self.current_term:
                self._send(reply)
                return

            if msg.term > self.current_term:
                self.current_term = msg.term
                self.state = self.STATE_FOLLOWER
                self.voted_for = None
            
            # 2. Log Freshness Check (Raft Safety 核心)
            # 只有当候选人的日志至少和自己一样新时，才投票
            my_last_idx, my_last_term = self._get_last_log_index_and_term()
            log_is_ok = (msg.last_log_term > my_last_term) or \
                        (msg.last_log_term == my_last_term and msg.last_log_index >= my_last_idx)

            if (self.voted_for is None or self.voted_for == msg.sender_id) and log_is_ok:
                self.voted_for = msg.sender_id
                self.last_heartbeat_rx = time.time() # 重置超时
                reply.vote_granted = True
                reply.term = self.current_term # 更新回包 Term
                print(f"✅ [投票] 投给 -> {msg.sender_id}")
            
            self._send(reply)

    def handle_append_entries(self, msg: RaftMessage):
        """处理心跳与日志复制"""
        with self.lock:
            reply = RaftMessage(
                type="AppendEntriesResponse",
                term=self.current_term,
                sender_id=self.node_id,
                success=False
            )
            
            # 1. Term 检查
            if msg.term < self.current_term:
                self._send(reply)
                return
            
            # 认可 Leader
            self.state = self.STATE_FOLLOWER
            self.current_term = msg.term
            self.last_heartbeat_rx = time.time()
            
            # 2. Log Consistency Check (此处简化，仅作为心跳处理)
            # 实际 Raft 需检查 prev_log_index 是否匹配
            
            # 3. 处理日志条目 (TODO: 实现日志追加)
            if msg.entries:
                print(f"📥 [日志] 收到 {len(msg.entries)} 条指令")
                # 简单追加
                self.log.extend(msg.entries)
                reply.success = True
            else:
                # 纯心跳
                reply.success = True
                # [调试]
                # print(f"❤️ [心跳] 来自 Leader {msg.sender_id} | SNR: {msg.phy_state.snr:.2f}")

            # 4. 更新 Commit Index
            if msg.leader_commit > self.commit_index:
                self.commit_index = min(msg.leader_commit, len(self.log))
            
            self._send(reply)

    def become_leader(self):
        with self.lock:
            if self.state != self.STATE_LEADER:
                self.state = self.STATE_LEADER
                print(f"👑 [当选] 成为 Leader (Term {self.current_term})")
                # 初始化 Leader 状态
                for i in range(1, self.total_nodes + 1):
                    if i != self.node_id:
                        self.next_index[i] = len(self.log) + 1
                        self.match_index[i] = 0
                self._send_heartbeat()

    def _send_heartbeat(self):
        # 构造 AppendEntries (空日志即为心跳)
        last_idx, last_term = self._get_last_log_index_and_term()
        msg = RaftMessage(
            type="AppendEntries",
            term=self.current_term,
            sender_id=self.node_id,
            prev_log_index=last_idx,
            prev_log_term=last_term,
            leader_commit=self.commit_index,
            entries=[] 
        )

        # [新增] 打印心跳发送日志
        print(f"❤️ [Leader] 发送心跳 (Term {self.current_term}) -> 广播") # 加这一行

        self._broadcast(msg)

    # ----------------------------------------------------------------
    #  网络层
    # ----------------------------------------------------------------

    def _broadcast(self, msg: RaftMessage):
        """发送给 SDR 的 TX 端口 (由 SDR 广播出去)"""
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"❌ 发送失败: {e}")

    def _send(self, msg: RaftMessage):
        """
        在无线广播环境下，单播其实也是广播。
        这里为了简化，所有消息都通过 _broadcast 发出，
        接收端根据逻辑决定是否处理。
        """
        self._broadcast(msg)

    def recv_loop(self):
        """独立的网络接收线程"""
        print("🔵 网络接收线程启动...")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg_str = data.decode('utf-8')
                msg = RaftMessage.from_json(msg_str)
                
                # 务必确保这里允许处理自己的包 (方案三/单机调试必须打开)
                if msg: 
                    # 1. 注入 SNR 到邻居表
                    self._update_peer_state(msg.sender_id, msg.phy_state)
                    
                    # =========== [新增] 实时计算并打印 Gamma ===========
                    with self.lock:
                        # 偷懒复用一下计算逻辑，算一下当前的平均 Gamma
                        current_gamma = 0.0
                        count = 0
                        for info in self.peers.values():
                            if len(info['snr_history']) > 0:
                                current_gamma += sum(info['snr_history']) / len(info['snr_history'])
                                count += 1
                        
                        # 打印当前收到的包的 SNR 和 平均 Gamma
                        # 这里的 msg.phy_state.snr 是瞬时值
                        # current_gamma 是平滑后的值 (算法真正用的值)
                        print(f"📡 [RX] 来自:{msg.sender_id} | 瞬时SNR:{msg.phy_state.snr:.1f} | 平均Gamma:{current_gamma:.1f}")
                    # =================================================
                    
                    # 2. 状态机处理
                    if msg.sender_id != self.node_id:  # <--- 加回这个判断
                        with self.lock:
                            if msg.type == "RequestVote":
                                self.handle_request_vote(msg)
                            elif msg.type == "VoteResponse":
                                if self.state == self.STATE_CANDIDATE and msg.vote_granted:
                                    self.become_leader()
                            elif msg.type == "AppendEntries":
                                self.handle_append_entries(msg)
                            
            except Exception as e:
                print(f"数据包错误: {e}")

    def run_loop(self):
        """主循环: 处理定时器"""
        print("🟢 主状态机启动...")
        while self.running:
            with self.lock:
                now = time.time()
                
                # Leader 逻辑: 定时发心跳
                if self.state == self.STATE_LEADER:
                    if now - self.last_heartbeat_rx >= self.heartbeat_interval: # 复用变量做间隔控制
                        self._send_heartbeat()
                        self.last_heartbeat_rx = now # 更新发送时间
                
                # Follower/Candidate 逻辑: 检查选举超时
                else:
                    # 动态计算超时时间 (RUBICONe)
                    timeout = self._calculate_election_timeout()
                    if now - self.last_heartbeat_rx >= timeout:
                        self.start_election()
            
            time.sleep(0.05)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="Node ID")
    parser.add_argument("--total", type=int, default=3, help="Total Nodes")
    parser.add_argument("--tx", type=int, required=True, help="TX Port")
    parser.add_argument("--rx", type=int, required=True, help="RX Port")
    args = parser.parse_args()
    
    node = RaftNode(args.id, args.total, args.tx, args.rx)
    
    # 启动网络线程
    t_net = threading.Thread(target=node.recv_loop)
    t_net.daemon = True
    t_net.start()
    
    # 启动主循环
    try:
        node.run_loop()
    except KeyboardInterrupt:
        print("\n🛑 停止运行")
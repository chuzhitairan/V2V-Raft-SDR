import socket
import time
import random
import json
import argparse
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

# --- 全局配置 ---
# 注意：在真实多机组网时，如果使用广播，通常设为 '<broadcast>' 或组播地址
# 但由于我们是用 SDR 的 P2P/广播 链路，SDR 脚本会帮我们广播
# 所以这里发给本地 SDR 监听端口 (127.0.0.1) 是对的
BROADCAST_IP = "127.0.0.1"

# ==========================================
# 1. 数据结构定义
# ==========================================

@dataclass
class PhyState:
    """信道状态（为未来加权投票做准备）"""
    snr: float = 0.0

@dataclass
class LogEntry:
    term: int
    index: int
    command: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class RaftMessage:
    type: str 
    term: int
    sender_id: int
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0
    last_log_index: int = 0
    last_log_term: int = 0
    success: bool = False
    vote_granted: bool = False
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
        except Exception:
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
        
        # Raft Persistent State (应持久化，目前仅内存)
        self.current_term = 0
        self.voted_for = None
        self.log: List[LogEntry] = []
        
        # Raft Volatile State
        self.commit_index = 0
        self.last_applied = 0
        self.state = self.STATE_FOLLOWER
        self.votes_received = 0  # 🔧 初始化，避免 AttributeError
        self.current_leader = None
        
        # Leader Volatile State (仅 Leader 使用)
        self.next_index = {}   # 每个节点的下一条日志索引
        self.match_index = {}  # 每个节点已复制的最高日志索引
        
        # System
        self.lock = threading.RLock()
        self.last_heartbeat_time = time.time()
        self.last_heartbeat_sent = time.time()
        self.running = True
        
        # 邻居状态表（被动记录 SNR，为未来加权投票做准备）
        self.peers: Dict[int, dict] = {}
        
        # 基础 Raft 参数 (固定超时 + 随机抖动)
        self.election_timeout_min = 1.5   # 选举超时下限 (秒)
        self.election_timeout_max = 3.0   # 选举超时上限 (秒)
        self.heartbeat_interval = 0.15    # 心跳间隔 (秒)
        
        # 邻居筛选参数 (SNR 过滤)
        self.snr_threshold = 5.0          # SNR 阈值 (dB)，低于此值的消息被丢弃
        self.filtered_count = 0           # 被过滤的消息计数
        
        # Network
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f"🚗 [节点 {self.node_id}] 就绪 | 监听: {self.rx_port} -> 发送: {self.tx_port}")

    def _update_peer_state(self, sender_id: int, phy_state: PhyState):
        """被动记录邻居 SNR（不影响 Raft 决策，仅用于观测）"""
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0}
        self.peers[sender_id]['snr'] = phy_state.snr
        self.peers[sender_id]['last_seen'] = time.time()

    def _calculate_election_timeout(self):
        """基础 Raft 选举超时: 固定范围 + 随机抖动"""
        return random.uniform(self.election_timeout_min, self.election_timeout_max)

    def _get_last_log_index_and_term(self):
        if len(self.log) > 0:
            return len(self.log), self.log[-1].term
        return 0, 0

    def _step_down(self, new_term):
        """发现更高 term 时降级为 Follower"""
        self.current_term = new_term
        self.state = self.STATE_FOLLOWER
        self.voted_for = None
        self.votes_received = 0
        self.current_leader = None

    def start_election(self):
        with self.lock:
            self.state = self.STATE_CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.votes_received = 1  # 投给自己
            self.current_leader = None
            self.last_heartbeat_time = time.time()
            
            last_idx, last_term = self._get_last_log_index_and_term()
            print(f"🔥 [选举] 发起 Term {self.current_term} (Timeout={self._calculate_election_timeout():.2f}s)")
            
            msg = RaftMessage(
                type="RequestVote",
                term=self.current_term,
                sender_id=self.node_id,
                last_log_index=last_idx,
                last_log_term=last_term
            )
            self._broadcast(msg)
            
            # 单节点集群可直接当选
            if self.votes_received > self.total_nodes / 2:
                self.become_leader()

    def handle_request_vote(self, msg: RaftMessage):
        with self.lock:
            reply = RaftMessage(
                type="VoteResponse",
                term=self.current_term,
                sender_id=self.node_id,
                vote_granted=False
            )

            # 旧 term 的请求直接拒绝
            if msg.term < self.current_term:
                self._send(reply)
                return

            # 发现更高 term，降级
            if msg.term > self.current_term:
                self._step_down(msg.term)
            
            # 日志完整性检查
            my_last_idx, my_last_term = self._get_last_log_index_and_term()
            log_is_ok = (msg.last_log_term > my_last_term) or \
                        (msg.last_log_term == my_last_term and msg.last_log_index >= my_last_idx)

            if (self.voted_for is None or self.voted_for == msg.sender_id) and log_is_ok:
                self.voted_for = msg.sender_id
                self.last_heartbeat_time = time.time()  # 重置选举超时
                reply.vote_granted = True
                reply.term = self.current_term
                print(f"✅ [投票] 同意 -> 节点 {msg.sender_id}")
            
            self._send(reply)

    def handle_append_entries(self, msg: RaftMessage):
        with self.lock:
            reply = RaftMessage(
                type="AppendEntriesResponse",
                term=self.current_term,
                sender_id=self.node_id,
                success=False,
                last_log_index=len(self.log)  # 告知 Leader 当前日志长度
            )
            
            # 旧 term 的请求直接拒绝
            if msg.term < self.current_term:
                self._send(reply)
                return
            
            # 发现合法 Leader，更新状态
            if self.state != self.STATE_FOLLOWER:
                print(f"⬇️ [降级] 发现 Leader {msg.sender_id}，转为 Follower")
            
            self._step_down(msg.term) if msg.term > self.current_term else None
            self.state = self.STATE_FOLLOWER
            self.current_term = msg.term
            self.current_leader = msg.sender_id
            self.last_heartbeat_time = time.time()
            
            # 🔧 日志一致性检查
            if msg.prev_log_index > 0:
                if len(self.log) < msg.prev_log_index:
                    # 日志太短，无法匹配
                    self._send(reply)
                    return
                if msg.prev_log_index > 0 and self.log[msg.prev_log_index - 1].term != msg.prev_log_term:
                    # term 不匹配，删除冲突条目
                    self.log = self.log[:msg.prev_log_index - 1]
                    self._send(reply)
                    return
            
            # 追加新日志
            if msg.entries:
                # 删除冲突的旧条目，追加新条目
                self.log = self.log[:msg.prev_log_index] + msg.entries
                print(f"📥 [日志] 收到 {len(msg.entries)} 条指令，当前日志长度: {len(self.log)}")
            
            reply.success = True
            reply.last_log_index = len(self.log)

            # 更新 commit_index
            if msg.leader_commit > self.commit_index:
                self.commit_index = min(msg.leader_commit, len(self.log))
                self._apply_committed_entries()
            
            self._send(reply)
    
    def _apply_committed_entries(self):
        """应用已提交的日志到状态机"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            print(f"✨ [执行] 共识达成! 执行操作: {entry.command}")

    def become_leader(self):
        with self.lock:
            if self.state != self.STATE_LEADER:
                self.state = self.STATE_LEADER
                self.current_leader = self.node_id
                
                # 初始化 Leader 状态 (Raft 论文要求)
                last_log_idx = len(self.log)
                for i in range(1, self.total_nodes + 1):
                    if i != self.node_id:
                        self.next_index[i] = last_log_idx + 1
                        self.match_index[i] = 0
                
                print(f"👑 [当选] 成为 Leader (Term {self.current_term})")
                self._send_heartbeat()
    
    def propose_command(self, command: str):
        """🔧 新增: Leader 提交新命令"""
        with self.lock:
            if self.state != self.STATE_LEADER:
                print(f"❌ [拒绝] 非 Leader 无法提交命令，当前 Leader: {self.current_leader}")
                return False
            
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=command
            )
            self.log.append(entry)
            print(f"📝 [提交] 新日志 #{entry.index}: {command}")
            
            # 立即发送 AppendEntries 复制日志
            self._replicate_log()
            return True
    
    def _replicate_log(self):
        """Leader 向所有 Follower 复制日志 (广播模式: 只发一次)"""
        # 🔧 修复: 广播模式下只需发送一次，不要对每个 peer 都广播
        last_idx, last_term = self._get_last_log_index_and_term()
        
        # 计算需要发送的日志条目 (从最小的 next_index 开始)
        min_next = min(self.next_index.values()) if self.next_index else len(self.log) + 1
        prev_idx = min_next - 1
        prev_term = self.log[prev_idx - 1].term if prev_idx > 0 and prev_idx <= len(self.log) else 0
        entries = self.log[prev_idx:] if prev_idx < len(self.log) else []
        
        msg = RaftMessage(
            type="AppendEntries",
            term=self.current_term,
            sender_id=self.node_id,
            prev_log_index=prev_idx,
            prev_log_term=prev_term,
            leader_commit=self.commit_index,
            entries=entries
        )
        self._broadcast(msg)
    
    def _send_append_entries_to(self, peer_id):
        """向特定节点发送 AppendEntries (保留用于单播场景)"""
        next_idx = self.next_index.get(peer_id, len(self.log) + 1)
        prev_idx = next_idx - 1
        prev_term = self.log[prev_idx - 1].term if prev_idx > 0 and prev_idx <= len(self.log) else 0
        
        # 获取需要发送的日志条目
        entries = self.log[prev_idx:] if prev_idx < len(self.log) else []
        
        msg = RaftMessage(
            type="AppendEntries",
            term=self.current_term,
            sender_id=self.node_id,
            prev_log_index=prev_idx,
            prev_log_term=prev_term,
            leader_commit=self.commit_index,
            entries=entries
        )
        self._broadcast(msg)  # 广播模式下无法单播，仍用广播

    def _send_heartbeat(self):
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
        # 移除刷屏日志
        self._broadcast(msg)

    def _broadcast(self, msg: RaftMessage):
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"❌ 发送失败: {e}")

    def _send(self, msg: RaftMessage):
        # 🔧 增加随机抖动，避免多个 Follower 同时回复导致冲突
        if msg.type in ["VoteResponse", "AppendEntriesResponse"]:
            time.sleep(random.uniform(0.01, 0.05))
        self._broadcast(msg)

    def recv_loop(self):
        """网络接收线程"""
        print("🔵 网络接收线程启动...")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg_str = data.decode('utf-8')
                msg = RaftMessage.from_json(msg_str)
                
                if msg and msg.sender_id != self.node_id:
                    # 邻居筛选: 信号太差直接丢弃 (模拟物理层屏蔽)
                    if msg.phy_state.snr < self.snr_threshold:
                        self.filtered_count += 1
                        if self.filtered_count % 100 == 1:  # 每 100 次打印一次
                            print(f"🚫 [过滤] 节点 {msg.sender_id} SNR={msg.phy_state.snr:.1f}dB < {self.snr_threshold}dB (累计过滤: {self.filtered_count})")
                        continue
                    
                    with self.lock:
                        # 被动记录邻居 SNR（不影响决策，仅用于观测）
                        self._update_peer_state(msg.sender_id, msg.phy_state)
                        
                        # 🔧 统一处理更高 term
                        if msg.term > self.current_term:
                            print(f"📡 发现更高 Term {msg.term}，降级为 Follower")
                            self._step_down(msg.term)
                        
                        if msg.type == "RequestVote":
                            self.handle_request_vote(msg)
                            
                        elif msg.type == "VoteResponse":
                            # 🔧 只在当前 term 且为 Candidate 时处理
                            if self.state == self.STATE_CANDIDATE and msg.term == self.current_term:
                                if msg.vote_granted:
                                    self.votes_received += 1
                                    print(f"🗳️ [得票] 来自节点 {msg.sender_id}，当前票数: {self.votes_received}/{self.total_nodes}")
                                    if self.votes_received > self.total_nodes / 2:
                                        self.become_leader()
                                        
                        elif msg.type == "AppendEntries":
                            self.handle_append_entries(msg)
                            
                        elif msg.type == "AppendEntriesResponse":
                            # 🔧 新增: Leader 处理复制响应
                            if self.state == self.STATE_LEADER and msg.term == self.current_term:
                                self._handle_append_response(msg)
                            
            except Exception as e:
                print(f"数据包错误: {e}")
    
    def _handle_append_response(self, msg: RaftMessage):
        """Leader 处理 AppendEntries 响应"""
        peer_id = msg.sender_id
        if msg.success:
            # 更新 nextIndex 和 matchIndex
            self.next_index[peer_id] = msg.last_log_index + 1
            self.match_index[peer_id] = msg.last_log_index
            
            # 检查是否可以提交更多日志
            self._try_commit()
        else:
            # 日志不一致，回退 nextIndex 重试
            self.next_index[peer_id] = max(1, self.next_index.get(peer_id, 1) - 1)
    
    def _try_commit(self):
        """Leader 检查并提交多数派已复制的日志"""
        for n in range(len(self.log), self.commit_index, -1):
            if self.log[n - 1].term != self.current_term:
                continue  # 只能提交当前 term 的日志
            
            # 计算已复制该条目的节点数 (包括自己)
            count = 1
            for peer_id, match_idx in self.match_index.items():
                if match_idx >= n:
                    count += 1
            
            if count > self.total_nodes / 2:
                self.commit_index = n
                self._apply_committed_entries()
                break

    def run_loop(self):
        print("🟢 主状态机启动...")
        while self.running:
            with self.lock:
                now = time.time()
                if self.state == self.STATE_LEADER:
                    # 🔧 使用专门的 last_heartbeat_sent 控制发送间隔
                    if now - self.last_heartbeat_sent >= self.heartbeat_interval:
                        self._send_heartbeat()
                        self.last_heartbeat_sent = now
                else:
                    # Follower/Candidate 检查选举超时
                    timeout = self._calculate_election_timeout()
                    if now - self.last_heartbeat_time >= timeout:
                        self.start_election()
            time.sleep(0.05)
    
    def input_loop(self):
        """🔧 新增: 用户输入线程，用于提交命令"""
        print("⌨️  输入线程启动... (按回车提交变道指令)")
        while self.running:
            try:
                input()  # 等待用户按回车
                self.propose_command("向左变道")
            except EOFError:
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="Node ID")
    parser.add_argument("--total", type=int, default=3, help="Total Nodes")
    parser.add_argument("--tx", type=int, required=True, help="TX Port")
    parser.add_argument("--rx", type=int, required=True, help="RX Port")
    parser.add_argument("--snr-threshold", type=float, default=5.0, help="SNR threshold for neighbor filtering (dB)")
    args = parser.parse_args()
    
    node = RaftNode(args.id, args.total, args.tx, args.rx)
    node.snr_threshold = args.snr_threshold
    print(f"📡 邻居筛选阈值: {node.snr_threshold} dB")
    
    # 网络接收线程
    t_net = threading.Thread(target=node.recv_loop)
    t_net.daemon = True
    t_net.start()
    
    # 🔧 用户输入线程 (允许 Leader 提交命令)
    t_input = threading.Thread(target=node.input_loop)
    t_input.daemon = True
    t_input.start()
    
    try:
        node.run_loop()
    except KeyboardInterrupt:
        print("\n🛑 停止运行")
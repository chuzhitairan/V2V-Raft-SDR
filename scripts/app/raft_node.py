import socket
import time
import random
import json
import argparse
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

# --- 全局配置 ---
BROADCAST_IP = "127.0.0.1"

# ==========================================
# 1. 数据结构定义 (对应 RUBICONe 论文协议)
# ==========================================

@dataclass
class PhyState:
    """
    车辆物理状态 (论文核心: State Initialization)
    包含: 位置(pos), 速度(vel), 信道质量(snr)
    """
    pos: List[float] = field(default_factory=lambda: [0.0, 0.0]) # [x, y]
    vel: List[float] = field(default_factory=lambda: [0.0, 0.0]) # [vx, vy]
    snr: float = 0.0 # 信噪比/信号强度 (用于公式计算)

@dataclass
class LogEntry:
    term: int
    command: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class RaftMessage:
    """Raft 消息协议封装"""
    type: str       # "RequestVote", "VoteResponse", "Heartbeat"
    term: int
    sender_id: int
    phy_state: PhyState  # [扩展] 携带物理层状态
    
    # 标准 Raft 字段
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0
    
    # 投票专用
    vote_granted: bool = False

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
            print(f"[解析错误] {e}")
            return None

# ==========================================
# 2. 核心功能模块
# ==========================================

class NodeState:
    """管理本车状态"""
    def __init__(self, node_id):
        self.node_id = node_id
        # 模拟初始状态 (实际应接入 GPS/IMU 传感器)
        self.phy = PhyState(pos=[node_id * 10.0, 0.0], vel=[15.0, 0.0]) 

    def update_simulation(self):
        """模拟车辆移动"""
        dt = 0.01
        self.phy.pos[0] += self.phy.vel[0] * dt
        # 这里预留接口：从 SDR 接收端读取真实的 SNR 值填入 self.phy.snr

    def get_state(self):
        return self.phy

class PeerManager:
    """邻居管理表 (用于计算网络密度和动态超时)"""
    def __init__(self):
        # 结构: {node_id: {'last_seen': time, 'phy_state': PhyState}}
        self.peers: Dict[int, Dict] = {} 
        self.cleanup_timeout = 10.0 # 10秒没消息视为掉线

    def update_peer(self, node_id, phy_state):
        self.peers[node_id] = {
            'last_seen': time.time(),
            'phy_state': phy_state
        }

    def get_active_count(self):
        self._cleanup()
        return len(self.peers)

    def get_avg_snr(self):
        """获取平均信道质量 (对应论文公式中的 gamma)"""
        if not self.peers:
            return 1.0 # 默认值
        # 这里暂时用对方发来的 SNR 代替链路质量
        total = sum(p['phy_state'].snr for p in self.peers.values())
        return total / len(self.peers) if len(self.peers) > 0 else 1.0

    def _cleanup(self):
        now = time.time()
        # 移除超时的邻居
        expired = [nid for nid, info in self.peers.items() if now - info['last_seen'] > self.cleanup_timeout]
        for nid in expired:
            del self.peers[nid]

# ==========================================
# 3. Raft 主逻辑类
# ==========================================

class RaftNode:
    STATE_FOLLOWER = "Follower"
    STATE_CANDIDATE = "Candidate"
    STATE_LEADER = "Leader"

    def __init__(self, node_id, total_nodes, tx_port, rx_port):
        self.node_id = node_id
        self.total_nodes = total_nodes # 用于判断多数派
        self.tx_port = tx_port
        self.rx_port = rx_port
        
        # 模块初始化
        self.vehicle = NodeState(node_id)
        self.peers = PeerManager()
        
        # 网络初始化 (非阻塞 UDP)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        self.sock.setblocking(False)

        # Raft 核心数据
        self.state = self.STATE_FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.votes_received = set()
        
        # 计时器
        self.last_heartbeat_rx = time.time()
        self.last_heartbeat_tx = time.time()
        
        # RUBICONe 参数
        self.T_base = 3.0
        self.alpha = 0.5
        self.election_timeout = self._calc_adaptive_timeout()
        self.heartbeat_interval = 1.0

        print(f"🚗 [节点 {self.node_id}] 启动! 监听: {self.rx_port} -> 发送: {self.tx_port}")

    def _calc_adaptive_timeout(self):
        """
        [论文核心] 自适应超时计算
        公式 (2): T = (1 + alpha / sum(gamma)) * T_base
        """
        # 1. 获取邻居信号质量总和 (目前用平均值模拟)
        # 实际部署时，这里需要从物理层获取真实的 RSSI/SNR
        gamma = self.peers.get_avg_snr() * max(1, self.peers.get_active_count())
        
        if gamma <= 0.1: gamma = 0.1 # 防止除零
        
        # 2. 计算动态因子
        factor = 1.0 + (self.alpha / gamma)
        
        # 3. 增加随机抖动防止选票瓜分
        timeout = (factor * self.T_base) + random.uniform(0.0, 1.0)
        return timeout

    def send_packet(self, msg: RaftMessage):
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"发送错误: {e}")

    # --- 状态转换 ---

    def start_election(self):
        print(f"🔥 [超时] 发起选举 (Term {self.current_term + 1}, Timeout={self.election_timeout:.2f}s)")
        self.state = self.STATE_CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = {self.node_id}
        self.last_heartbeat_rx = time.time()


        # =========== [关键修复] 开始 ===========
        # 给自己投完票后，立即检查是否已经赢得选举
        # 对于 total=1 的情况，1 > 0.5 成立，立即当选
        if len(self.votes_received) > self.total_nodes / 2:
            self.become_leader()
        # =========== [关键修复] 结束 ===========
        
        # 构造并广播 RequestVote
        msg = RaftMessage(
            type="RequestVote",
            term=self.current_term,
            sender_id=self.node_id,
            phy_state=self.vehicle.get_state()
        )
        self.send_packet(msg)
        
        # 重置超时 (应用动态算法)
        self.election_timeout = self._calc_adaptive_timeout()

    def become_leader(self):
        if self.state != self.STATE_LEADER:
            print(f"👑 [当选] 我是 Leader (Term {self.current_term})")
            self.state = self.STATE_LEADER
            self.send_heartbeat()

    def send_heartbeat(self):
        msg = RaftMessage(
            type="Heartbeat",
            term=self.current_term,
            sender_id=self.node_id,
            phy_state=self.vehicle.get_state()
        )
        self.send_packet(msg)
        self.last_heartbeat_tx = time.time()

    # --- 消息处理 ---

    def handle_message(self, msg: RaftMessage):
        # 1. 更新邻居信息 (用于计算网络拓扑)
        self.peers.update_peer(msg.sender_id, msg.phy_state)

        # 2. Term 更新机制
        if msg.term > self.current_term:
            print(f"   [Term更新] {self.current_term} -> {msg.term} (Follower)")
            self.current_term = msg.term
            self.state = self.STATE_FOLLOWER
            self.voted_for = None
        
        # 3. 消息分发
        if msg.type == "RequestVote":
            self._on_request_vote(msg)
        elif msg.type == "VoteResponse":
            self._on_vote_response(msg)
        elif msg.type == "Heartbeat":
            self._on_heartbeat(msg)

    def _on_request_vote(self, msg: RaftMessage):
        if msg.term >= self.current_term and (self.voted_for is None or self.voted_for == msg.sender_id):
            self.voted_for = msg.sender_id
            self.last_heartbeat_rx = time.time()
            
            # 同意投票
            reply = RaftMessage(
                type="VoteResponse",
                term=self.current_term,
                sender_id=self.node_id,
                phy_state=self.vehicle.get_state(),
                vote_granted=True
            )
            self.send_packet(reply)
            print(f"   [投票] 投给 -> 节点 {msg.sender_id}")

    def _on_vote_response(self, msg: RaftMessage):
        if self.state == self.STATE_CANDIDATE and msg.vote_granted:
            self.votes_received.add(msg.sender_id)
            print(f"   [得票] +1 (当前 {len(self.votes_received)}/{self.total_nodes})")
            if len(self.votes_received) > self.total_nodes / 2:
                self.become_leader()

    def _on_heartbeat(self, msg: RaftMessage):
        if msg.term >= self.current_term:
            self.state = self.STATE_FOLLOWER
            self.last_heartbeat_rx = time.time()
            # print(f"   [心跳] 来自 Leader {msg.sender_id}")

    # --- 主循环 ---

    def run_loop(self):
        while True:
            # 1. 接收网络数据 (非阻塞)
            try:
                data, _ = self.sock.recvfrom(4096)
                msg_str = data.decode('utf-8')
                
                # =========== [修改这里] ===========
                # 解析一下 JSON，专门看看 SNR 是多少
                try:
                    debug_msg = json.loads(msg_str)
                    # 提取 SNR，如果没有这个字段显示 N/A
                    snr_val = debug_msg.get('phy_state', {}).get('snr', 'N/A')
                    print(f"[物理层调试] 收到心跳 | 来自: {debug_msg.get('sender_id')} | SNR: {snr_val}")
                except:
                    # 如果解析失败，打印完整原始数据看看发生了什么
                    print(f"[物理层调试] 原始数据: {msg_str}")
                # ================================

                msg = RaftMessage.from_json(msg_str)
                if msg and msg.sender_id != self.node_id:
                    self.handle_message(msg)
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"数据错误: {e}")

            # 2. 状态机超时检查
            now = time.time()
            
            if self.state == self.STATE_LEADER:
                if now - self.last_heartbeat_tx >= self.heartbeat_interval:
                    self.send_heartbeat()
            else:
                if now - self.last_heartbeat_rx >= self.election_timeout:
                    self.start_election()

            # 3. 模拟车辆移动
            self.vehicle.update_simulation()
            
            time.sleep(0.01)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="Node ID")
    parser.add_argument("--total", type=int, default=3, help="Total Nodes")
    parser.add_argument("--tx", type=int, required=True, help="Port to send TO SDR")
    parser.add_argument("--rx", type=int, required=True, help="Port to listen FROM SDR")
    args = parser.parse_args()
    
    node = RaftNode(args.id, args.total, args.tx, args.rx)
    try:
        node.run_loop()
    except KeyboardInterrupt:
        print("停止运行")
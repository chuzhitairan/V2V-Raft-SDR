import socket
import threading
import time
import random
import json
import argparse

# --- 配置参数 ---
GR_IP = "127.0.0.1"
GR_PORT = 50000  # 发送给 GNU Radio (Air)

# Raft 状态定义
STATE_FOLLOWER = "Follower"
STATE_CANDIDATE = "Candidate"
STATE_LEADER = "Leader"

class RaftNode:
    def __init__(self, node_id, total_nodes):
        self.node_id = node_id
        self.total_nodes = total_nodes
        self.listen_port = 50000 + node_id  # 比如节点1监听 50001
        
        # Raft 核心数据
        self.state = STATE_FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.votes_received = set()
        
        # 定时器相关
        self.election_timeout = random.uniform(3.0, 5.0) # 随机超时，避免同时选举
        self.last_heartbeat_time = time.time()
        self.heartbeat_interval = 1.0  # Leader 发心跳的间隔
        
        # 网络初始化
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", self.listen_port))
        print(f"🚗 [节点 {self.node_id}] 启动! 监听端口: {self.listen_port}")

    def send_packet(self, message):
        """将消息打包发给 GNU Radio (广播)"""
        # 消息格式: JSON
        msg_bytes = json.dumps(message).encode('utf-8')
        try:
            self.sock.sendto(msg_bytes, (GR_IP, GR_PORT))
        except Exception as e:
            print(f"发送错误: {e}")

    def handle_message(self, msg):
        """处理收到的消息 (Raft 核心逻辑)"""
        msg_type = msg.get("type")
        term = msg.get("term")
        sender = msg.get("sender")

        # 1. 如果收到更高任期的消息，立刻变为 Follower
        if term > self.current_term:
            print(f"   [Term更新] 发现更高任期 {term} (来自节点{sender})，变回 Follower")
            self.current_term = term
            self.state = STATE_FOLLOWER
            self.voted_for = None

        # 2. 处理 RequestVote (拉票请求)
        if msg_type == "RequestVote":
            # 如果我还没投过票，且对方任期够新
            if term >= self.current_term and (self.voted_for is None or self.voted_for == sender):
                self.voted_for = sender
                self.last_heartbeat_time = time.time() # 重置超时
                print(f"   [投票] 投给了 -> 节点 {sender}")
                # 回复赞成票
                reply = {
                    "type": "VoteResponse",
                    "term": self.current_term,
                    "sender": self.node_id,
                    "vote_granted": True
                }
                self.send_packet(reply)

        # 3. 处理 VoteResponse (收到选票)
        elif msg_type == "VoteResponse":
            if self.state == STATE_CANDIDATE and msg.get("vote_granted"):
                self.votes_received.add(sender)
                print(f"   [得票] 收到节点 {sender} 的票 (当前 {len(self.votes_received)}/{self.total_nodes})")
                # 检查是否过半
                if len(self.votes_received) > self.total_nodes / 2:
                    self.become_leader()

        # 4. 处理 AppendEntries (心跳)
        elif msg_type == "Heartbeat":
            if term >= self.current_term:
                self.state = STATE_FOLLOWER
                self.last_heartbeat_time = time.time() # 喂狗，不超时
                # print(f"   [心跳] 收到 Leader {sender} 心跳")

    def start_election(self):
        """发起选举"""
        print(f"🔥 [超时] 发起选举! (Term {self.current_term + 1})")
        self.state = STATE_CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = {self.node_id} # 先给自己投一票
        self.last_heartbeat_time = time.time()
        
        # 广播拉票请求
        req = {
            "type": "RequestVote",
            "term": self.current_term,
            "sender": self.node_id
        }
        self.send_packet(req)

    def become_leader(self):
        """当选 Leader"""
        if self.state != STATE_LEADER:
            print(f"👑 [当选] 我是 Leader! (Term {self.current_term})")
            self.state = STATE_LEADER
            self.send_heartbeat()

    def send_heartbeat(self):
        """发送心跳"""
        msg = {
            "type": "Heartbeat",
            "term": self.current_term,
            "sender": self.node_id
        }
        self.send_packet(msg)

    def run_loop(self):
        """主循环"""
        while True:
            # --- 1. 接收消息 (非阻塞) ---
            self.sock.settimeout(0.1)
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                # 过滤自己发的消息 (回声消除)
                if msg.get("sender") != self.node_id:
                    self.handle_message(msg)
            except socket.timeout:
                pass
            except Exception as e:
                print(f"数据解析错误: {e}")

            # --- 2. 定时任务 ---
            current_time = time.time()
            
            if self.state == STATE_LEADER:
                # Leader 定时发心跳
                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    self.send_heartbeat()
                    self.last_heartbeat_time = current_time
                    print("   [Leader] 发送心跳...")
            else:
                # Follower/Candidate 检查超时
                if current_time - self.last_heartbeat_time >= self.election_timeout:
                    self.start_election()
                    # 重置超时时间 (随机化，防止瓜分选票)
                    self.election_timeout = random.uniform(3.0, 5.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="节点ID (1-5)")
    args = parser.parse_args()
    
    node = RaftNode(node_id=args.id, total_nodes=5)
    node.run_loop()
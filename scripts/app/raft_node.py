import socket
import threading
import time
import random
import json
import argparse

# Raft 状态定义
STATE_FOLLOWER = "Follower"
STATE_CANDIDATE = "Candidate"
STATE_LEADER = "Leader"

class RaftNode:
    def __init__(self, node_id, total_nodes, target_port, listen_port):
        self.node_id = node_id
        self.total_nodes = total_nodes
        self.listen_port = listen_port  # 我监听的端口 (从 SDR 接收)
        self.target_port = target_port  # 我发送的端口 (发给 SDR)
        
        # Raft 核心数据
        self.state = STATE_FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.votes_received = set()
        
        self.election_timeout = random.uniform(3.0, 5.0)
        self.last_heartbeat_time = time.time()
        self.heartbeat_interval = 1.0 
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", self.listen_port))
        print(f"🚗 [节点 {self.node_id}] 启动! 监听: {self.listen_port} | 发送目标: {self.target_port}")

    def send_packet(self, message):
        """发送消息给 SDR 基站"""
        msg_bytes = json.dumps(message).encode('utf-8')
        try:
            # 发送给指定的 SDR 入口端口
            self.sock.sendto(msg_bytes, ("127.0.0.1", self.target_port))
        except Exception as e:
            print(f"发送错误: {e}")

    def handle_message(self, msg):
        msg_type = msg.get("type")
        term = msg.get("term")
        sender = msg.get("sender")

        if term > self.current_term:
            print(f"   [Term更新] 发现更高任期 {term} (来自节点{sender})")
            self.current_term = term
            self.state = STATE_FOLLOWER
            self.voted_for = None

        if msg_type == "RequestVote":
            if term >= self.current_term and (self.voted_for is None or self.voted_for == sender):
                self.voted_for = sender
                self.last_heartbeat_time = time.time()
                print(f"   [投票] 投给了 -> 节点 {sender}")
                reply = {"type": "VoteResponse", "term": self.current_term, "sender": self.node_id, "vote_granted": True}
                self.send_packet(reply)

        elif msg_type == "VoteResponse":
            if self.state == STATE_CANDIDATE and msg.get("vote_granted"):
                self.votes_received.add(sender)
                print(f"   [得票] 收到节点 {sender} 的票 (当前 {len(self.votes_received)}/{self.total_nodes})")
                if len(self.votes_received) > self.total_nodes / 2:
                    self.become_leader()

        elif msg_type == "Heartbeat":
            if term >= self.current_term:
                self.state = STATE_FOLLOWER
                self.last_heartbeat_time = time.time()
                print(f"   [心跳] 收到 Leader {sender} 心跳")

    def start_election(self):
        print(f"🔥 [超时] 发起选举! (Term {self.current_term + 1})")
        self.state = STATE_CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = {self.node_id}
        self.last_heartbeat_time = time.time()
        
        req = {"type": "RequestVote", "term": self.current_term, "sender": self.node_id}
        self.send_packet(req)

    def become_leader(self):
        if self.state != STATE_LEADER:
            print(f"👑 [当选] 我是 Leader! (Term {self.current_term})")
            self.state = STATE_LEADER
            self.send_heartbeat()

    def send_heartbeat(self):
        msg = {"type": "Heartbeat", "term": self.current_term, "sender": self.node_id}
        self.send_packet(msg)

    def run_loop(self):
        while True:
            # 接收
            self.sock.settimeout(0.1)
            try:
                data, _ = self.sock.recvfrom(4096)
                # 打印原始数据以调试
                print(f"   [Debug] 收到数据: {data.decode('utf-8')}")
                msg = json.loads(data.decode('utf-8'))
                if msg.get("sender") != self.node_id:
                    self.handle_message(msg)
            except socket.timeout:
                pass
            except Exception as e:
                print(f"解析错误: {e}")

            # 定时
            current_time = time.time()
            if self.state == STATE_LEADER:
                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    self.send_heartbeat()
                    self.last_heartbeat_time = current_time
            else:
                if current_time - self.last_heartbeat_time >= self.election_timeout:
                    self.start_election()
                    self.election_timeout = random.uniform(3.0, 5.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="Node ID")
    parser.add_argument("--target-port", type=int, required=True, help="Port to send TO SDR")
    parser.add_argument("--listen-port", type=int, required=True, help="Port to listen FROM SDR")
    args = parser.parse_args()
    
    node = RaftNode(args.id, 2, args.target_port, args.listen_port)
    node.run_loop()
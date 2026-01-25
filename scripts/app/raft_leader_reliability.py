#!/usr/bin/env python3
"""
可靠性共识实验 - Leader 端 (综合性能评估)
=========================================

三层循环实验：
1. 外层循环：SNR (信道质量)
2. 中层循环：p_node (节点可信度)
3. 内层循环：n (系统规模)

每组参数下执行 K 轮测试，统计：
- 有效系统规模 (Effective Scale)
- 系统整体可信度 (P_sys)

使用方法:
    python3 raft_leader_reliability.py --id 1 --total 6 --tx 10001 --rx 20001

作者: V2V-Raft-SDR 项目
"""

import socket
import time
import random
import json
import argparse
import threading
import statistics
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple
from datetime import datetime

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
    """消息结构 (扩展版，支持可靠性实验)"""
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
    target_snr: float = 0.0
    # 新增: 可靠性实验字段
    p_node: float = 1.0
    vote_request_id: int = 0

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
# Leader 节点 (可靠性实验版)
# ============================================================================

class LeaderReliability:
    """
    可靠性实验版 Leader
    
    功能：
    1. 三层循环实验控制 (SNR -> p_node -> n)
    2. 广播 p_node 参数通知 Follower
    3. 投票统计与判决
    4. 结果记录与保存
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
        self.heartbeat_interval = 0.5
        self.snr_report_interval = 1.0
        self.status_interval = 5.0
        
        # 当前参数
        self.target_snr = 20.0
        self.current_p_node = 1.0
        self.current_n = 6
        
        # 实验参数
        self.snr_levels = [20.0, 8.0]           # 两个 SNR 等级
        self.p_node_levels = [0.6, 0.7, 0.8, 0.9, 1.0]  # 可信度范围
        self.n_levels = [1, 2, 3, 4, 5, 6]      # 系统规模
        self.rounds_per_config = 50             # 每组配置的测试轮数
        self.vote_deadline = 0.5                # 投票截止时间 (秒)
        self.stabilize_time = 10.0              # SNR 切换后的稳定时间
        self.snr_tolerance = 3.0
        self.cluster_timeout = 2.0
        
        # 投票收集
        self.vote_request_id = 0
        self.votes_received: Dict[int, bool] = {}  # {node_id: success}
        self.votes_lock = threading.Lock()
        
        # 实验结果
        self.results: List[dict] = []
        self.experiment_running = False
        
        # 统计
        self.stats = {
            'heartbeats_sent': 0,
            'snr_reports_sent': 0,
        }
        
        # 网络
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f"🔬 [节点 {node_id}] 可靠性实验 LEADER")
        print(f"   TX:{tx_port} RX:{rx_port}")

    def send_heartbeat(self):
        """发送心跳 - 携带 target_snr 和 p_node"""
        with self.lock:
            msg = Message(
                type="APPEND",
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=0,
                prev_log_term=0,
                leader_commit=self.commit_index,
                entries=[],
                target_snr=self.target_snr,
                p_node=self.current_p_node,
                vote_request_id=0  # 心跳不带投票 ID
            )
            self._broadcast(msg)
            self.stats['heartbeats_sent'] += 1
    
    def send_vote_request(self, command: str = "DECISION") -> int:
        """发送投票请求，返回请求 ID"""
        with self.lock:
            self.vote_request_id += 1
            request_id = self.vote_request_id
            
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=command
            )
            
            msg = Message(
                type="APPEND",
                term=self.current_term,
                sender_id=self.node_id,
                prev_log_index=len(self.log),
                prev_log_term=self.log[-1].term if self.log else 0,
                leader_commit=self.commit_index,
                entries=[entry],
                target_snr=self.target_snr,
                p_node=self.current_p_node,
                vote_request_id=request_id
            )
            
            # 清空投票记录
            with self.votes_lock:
                self.votes_received = {}
            
            self._broadcast(msg)
            return request_id
    
    def send_snr_report(self):
        """广播 SNR 报告 - 携带 p_node"""
        with self.lock:
            snr_data = {}
            for peer_id, info in self.peers.items():
                if time.time() - info['last_seen'] <= self.cluster_timeout:
                    snr_data[peer_id] = info['snr']
            
            if not snr_data:
                return
            
            msg = Message(
                type="SNR_REPORT",
                term=self.current_term,
                sender_id=self.node_id,
                snr_report=snr_data,
                target_snr=self.target_snr,
                p_node=self.current_p_node
            )
            self._broadcast(msg)
            self.stats['snr_reports_sent'] += 1
    
    def collect_votes(self, request_id: int, n: int) -> Tuple[int, int, int]:
        """
        收集投票结果 (简单计数版，保留兼容)
        
        Args:
            request_id: 投票请求 ID
            n: 当前系统规模 (只统计 ID <= n 的节点)
        
        Returns:
            (yes_votes, no_votes, total_votes)
        """
        with self.votes_lock:
            yes_votes = 0
            no_votes = 0
            
            for node_id, success in self.votes_received.items():
                # 软件屏蔽：只统计 ID <= n 的节点
                if node_id <= n:
                    if success:
                        yes_votes += 1
                    else:
                        no_votes += 1
            
            total_votes = yes_votes + no_votes
            return yes_votes, no_votes, total_votes
    
    def collect_weighted_votes(self, request_id: int, n: int) -> Tuple[float, float, bool]:
        """
        收集加权投票结果 (基于 SNR 的微小权重差异)
        
        用于解决偶数节点平票僵局：
        - 权重公式: w_i = 1 + 0.001 * (SNR_i - SNR_min) / (SNR_max - SNR_min)
        - Leader 虚拟 SNR = max(Follower SNR) + 2.0 dB
        - 判决标准: W_yes > W_total / 2
        
        Args:
            request_id: 投票请求 ID
            n: 当前系统规模 (只统计 ID <= n 的节点)
        
        Returns:
            (W_yes, W_total, consensus_reached)
        """
        with self.votes_lock:
            # 1. 收集所有参与投票节点的 (node_id, success, snr)
            voters = []
            for node_id, success in self.votes_received.items():
                # 软件屏蔽：只统计 ID <= n 的节点
                if node_id <= n:
                    # 获取该节点的 SNR (从 peers 表)
                    snr = 0.0
                    if node_id in self.peers:
                        snr = self.peers[node_id].get('snr', 0.0)
                    voters.append({'id': node_id, 'success': success, 'snr': snr})
            
            # 2. Leader 虚拟投票 (Leader 作为发起者，默认赞成)
            # 注意：Leader 必须先 append 进去，然后再判断是否为空
            # Leader 虚拟 SNR = 当前最高 Follower SNR + 2.0 dB (若无 Follower 则用目标 SNR)
            max_follower_snr = max((v['snr'] for v in voters), default=self.target_snr)
            leader_virtual_snr = max_follower_snr + 2.0
            voters.append({'id': self.node_id, 'success': True, 'snr': leader_virtual_snr})
            
            # 现在 voters 至少包含 Leader，不会为空
            
            # 3. 归一化计算权重
            snr_values = [v['snr'] for v in voters]
            snr_min = min(snr_values)
            snr_max = max(snr_values)
            snr_range = snr_max - snr_min if snr_max > snr_min else 1.0  # 避免除零
            
            # 权重公式: w = 1 + 0.001 * (SNR - SNR_min) / (SNR_max - SNR_min)
            # 结果: 信号最差的节点权重 = 1.0, 信号最好的 = 1.001
            for v in voters:
                v['weight'] = 1.0 + 0.001 * (v['snr'] - snr_min) / snr_range
            
            # 4. 计算权重之和
            W_total = sum(v['weight'] for v in voters)
            W_yes = sum(v['weight'] for v in voters if v['success'])
            
            # 5. 判决: W_yes > W_total / 2
            consensus_reached = W_yes > W_total / 2
            
            return W_yes, W_total, consensus_reached
    
    def _handle_append_response(self, msg: Message):
        """处理投票响应"""
        # 更新邻居 SNR
        self._update_peer(msg.sender_id, msg.phy_state)
        
        # 记录投票 (只记录带有效 request_id 的响应)
        if hasattr(msg, 'vote_request_id') and msg.vote_request_id > 0:
            with self.votes_lock:
                # 只记录最新一轮的投票
                if msg.vote_request_id == self.vote_request_id:
                    self.votes_received[msg.sender_id] = msg.success
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """更新邻居 SNR"""
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
        """广播消息"""
        try:
            data = msg.to_json().encode('utf-8')
            self.sock.sendto(data, (BROADCAST_IP, self.tx_port))
        except Exception as e:
            print(f"❌ 发送失败: {e}")

    def get_active_peer_count(self) -> int:
        """获取当前活跃节点数"""
        now = time.time()
        count = 1  # Leader 自己
        with self.lock:
            for peer_id, info in self.peers.items():
                if now - info['last_seen'] <= self.cluster_timeout:
                    count += 1
        return count
    
    def wait_for_snr_stable(self, target_snr: float, timeout: float = 30.0) -> bool:
        """等待 SNR 稳定"""
        print(f"\n⏳ 等待 SNR 稳定到 {target_snr} dB...")
        
        start_time = time.time()
        stable_count = 0
        required_stable = 3
        
        while time.time() - start_time < timeout:
            time.sleep(2.0)
            
            with self.lock:
                if not self.peers:
                    continue
                
                snr_diffs = []
                for peer_id, info in self.peers.items():
                    if time.time() - info['last_seen'] <= self.cluster_timeout:
                        diff = abs(info['snr'] - target_snr)
                        snr_diffs.append(diff)
                
                if snr_diffs:
                    avg_diff = statistics.mean(snr_diffs)
                    if avg_diff <= self.snr_tolerance:
                        stable_count += 1
                        print(f"   稳定检测 {stable_count}/{required_stable} (平均偏差: {avg_diff:.1f} dB)")
                        if stable_count >= required_stable:
                            print(f"✅ SNR 已稳定")
                            return True
                    else:
                        stable_count = 0
        
        print(f"⚠️ SNR 稳定超时，继续实验")
        return False
    
    # ========================================================================
    # 实验主循环
    # ========================================================================
    
    def run_experiment(self):
        """运行三层循环实验"""
        self.experiment_running = True
        
        print("\n" + "=" * 70)
        print("🔬 可靠性共识实验开始")
        print("=" * 70)
        print(f"   SNR 等级: {self.snr_levels}")
        print(f"   p_node 等级: {self.p_node_levels}")
        print(f"   系统规模 n: {self.n_levels}")
        print(f"   每组测试轮数: {self.rounds_per_config}")
        print(f"   投票截止时间: {self.vote_deadline}s")
        print("=" * 70)
        
        total_configs = len(self.snr_levels) * len(self.p_node_levels) * len(self.n_levels)
        config_idx = 0
        
        for snr in self.snr_levels:
            # ===== 外层循环：SNR =====
            self.target_snr = snr
            print(f"\n{'='*70}")
            print(f"📡 切换 SNR 到 {snr} dB")
            print(f"{'='*70}")
            
            # 广播新的 target_snr，等待稳定
            self.wait_for_snr_stable(snr, timeout=self.stabilize_time)
            
            for p_node in self.p_node_levels:
                # ===== 中层循环：p_node =====
                self.current_p_node = p_node
                print(f"\n   🎲 设置 p_node = {p_node}")
                
                # 广播新的 p_node，让 Follower 更新
                for _ in range(5):
                    self.send_heartbeat()
                    time.sleep(0.2)
                
                for n in self.n_levels:
                    # ===== 内层循环：n =====
                    self.current_n = n
                    config_idx += 1
                    
                    print(f"\n      [{config_idx}/{total_configs}] "
                          f"SNR={snr}dB, p={p_node}, n={n}")
                    
                    # 执行 K 轮测试
                    success_count = 0
                    effective_scales = []
                    
                    for k in range(self.rounds_per_config):
                        # a. 发送投票请求
                        request_id = self.send_vote_request(f"DECISION_{config_idx}_{k}")
                        
                        # b. 等待 Deadline
                        time.sleep(self.vote_deadline)
                        
                        # c. 收集加权投票 (使用 SNR 打破偶数节点平票)
                        W_yes, W_total, consensus = self.collect_weighted_votes(request_id, n)
                        
                        # 同时获取简单计数用于记录有效规模
                        yes, no, total = self.collect_votes(request_id, n)
                        
                        # d. 记录有效系统规模 (不含 Leader 的虚拟投票)
                        effective_scales.append(total)
                        
                        # e. 判定系统是否正确 (使用加权投票结果)
                        # 加权版：W_yes > W_total / 2
                        if consensus:
                            success_count += 1
                        
                        # f. 冷却时间：让网络"静一静"，减少 UDP 缓冲区溢出风险
                        time.sleep(0.1)
                        
                        # 每 10 轮打印一次进度
                        if (k + 1) % 10 == 0:
                            p_sys_so_far = success_count / (k + 1)
                            avg_scale_so_far = statistics.mean(effective_scales)
                            print(f"         轮次 {k+1}/{self.rounds_per_config}: "
                                  f"P_sys={p_sys_so_far:.2f}, 有效规模={avg_scale_so_far:.2f}")
                    
                    # 计算统计结果
                    p_sys = success_count / self.rounds_per_config
                    avg_effective_scale = statistics.mean(effective_scales)
                    std_effective_scale = statistics.stdev(effective_scales) if len(effective_scales) > 1 else 0
                    
                    result = {
                        'snr': snr,
                        'p_node': p_node,
                        'n': n,
                        'p_sys': p_sys,
                        'avg_effective_scale': avg_effective_scale,
                        'std_effective_scale': std_effective_scale,
                        'success_count': success_count,
                        'total_rounds': self.rounds_per_config,
                        'raw_effective_scales': effective_scales
                    }
                    self.results.append(result)
                    
                    print(f"      ✅ 结果: P_sys={p_sys:.3f}, "
                          f"有效规模={avg_effective_scale:.2f}±{std_effective_scale:.2f}")
        
        self.experiment_running = False
        self._print_final_results()
        self._save_results()
    
    def _print_final_results(self):
        """打印最终结果"""
        print("\n" + "=" * 80)
        print("📊 实验结果汇总")
        print("=" * 80)
        
        for snr in self.snr_levels:
            print(f"\n--- SNR = {snr} dB ---")
            print(f"{'p_node':<10} {'n':<5} {'P_sys':<10} {'有效规模':<15}")
            print("-" * 45)
            
            for r in self.results:
                if r['snr'] == snr:
                    print(f"{r['p_node']:<10.2f} {r['n']:<5} "
                          f"{r['p_sys']:<10.3f} "
                          f"{r['avg_effective_scale']:.2f}±{r['std_effective_scale']:.2f}")
        
        print("=" * 80)
    
    def _save_results(self):
        """保存结果到 JSON 文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"reliability_experiment_results_{timestamp}.json"
        
        data = {
            'start_time': datetime.now().isoformat(),
            'total_nodes': self.total_nodes,
            'snr_levels': self.snr_levels,
            'p_node_levels': self.p_node_levels,
            'n_levels': self.n_levels,
            'rounds_per_config': self.rounds_per_config,
            'vote_deadline': self.vote_deadline,
            'results': self.results
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"\n💾 结果已保存到: {filename}")
        except Exception as e:
            print(f"❌ 保存失败: {e}")
    
    def recv_loop(self):
        """接收线程"""
        print("🔵 接收线程启动")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = Message.from_json(data.decode('utf-8'))
                
                if msg and msg.sender_id != self.node_id:
                    if msg.type == "APPEND_RESPONSE":
                        self._handle_append_response(msg)
                        
            except Exception as e:
                if self.running:
                    print(f"接收错误: {e}")
    
    def main_loop(self):
        """主循环 (心跳 + SNR 报告)"""
        print("🟢 主循环启动")
        last_heartbeat = time.time()
        last_snr_report = time.time()
        last_status = time.time()
        
        while self.running:
            now = time.time()
            
            if now - last_heartbeat >= self.heartbeat_interval:
                self.send_heartbeat()
                last_heartbeat = now
            
            if now - last_snr_report >= self.snr_report_interval:
                self.send_snr_report()
                last_snr_report = now
            
            if now - last_status >= self.status_interval:
                active = self.get_active_peer_count()
                print(f"📊 [状态] 活跃节点: {active}, "
                      f"SNR={self.target_snr}dB, p_node={self.current_p_node}")
                last_status = now
            
            time.sleep(0.05)
    
    def stop(self):
        self.running = False
        self.sock.close()


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="可靠性实验 Leader")
    parser.add_argument("--id", type=int, required=True, help="节点 ID")
    parser.add_argument("--total", type=int, default=6, help="总节点数")
    parser.add_argument("--tx", type=int, required=True, help="TX 端口")
    parser.add_argument("--rx", type=int, required=True, help="RX 端口")
    # 实验参数
    parser.add_argument("--snr-levels", type=str, default="20.0,8.0", 
                        help="SNR 等级 (逗号分隔)")
    parser.add_argument("--p-node-levels", type=str, default="0.6,0.7,0.8,0.9,1.0",
                        help="p_node 等级 (逗号分隔)")
    parser.add_argument("--n-levels", type=str, default="1,2,3,4,5,6",
                        help="系统规模 n (逗号分隔)")
    parser.add_argument("--rounds", type=int, default=50, help="每组配置测试轮数")
    parser.add_argument("--vote-deadline", type=float, default=0.5, help="投票截止时间")
    parser.add_argument("--stabilize-time", type=float, default=10.0, 
                        help="SNR 切换后稳定时间")
    args = parser.parse_args()
    
    node = LeaderReliability(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx
    )
    
    # 解析实验参数
    node.snr_levels = [float(x) for x in args.snr_levels.split(',')]
    node.p_node_levels = [float(x) for x in args.p_node_levels.split(',')]
    node.n_levels = [int(x) for x in args.n_levels.split(',')]
    node.rounds_per_config = args.rounds
    node.vote_deadline = args.vote_deadline
    node.stabilize_time = args.stabilize_time
    
    # 启动接收线程
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    # 启动主循环线程
    t_main = threading.Thread(target=node.main_loop, daemon=True)
    t_main.start()
    
    print("\n" + "=" * 60)
    print("准备就绪！")
    print("等待 Follower 节点加入...")
    print("按 Enter 开始实验，或 Ctrl+C 退出")
    print("=" * 60 + "\n")
    
    try:
        input()  # 等待用户确认
        node.run_experiment()
    except KeyboardInterrupt:
        print("\n🛑 实验中断")
        if node.results:
            node._print_final_results()
            node._save_results()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

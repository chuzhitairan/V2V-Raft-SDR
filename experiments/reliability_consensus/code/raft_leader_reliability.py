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
        self.heartbeat_interval = 0.1   # 原0.5，5倍加速
        self.snr_report_interval = 0.2   # 原1.0，5倍加速
        self.status_interval = 1.0       # 原5.0，5倍加速
        
        # 当前参数
        self.target_snr = 16.0  # 初始值设为第一个 SNR 等级
        self.current_p_node = 1.0
        self.current_n = 6
        self.current_p_node = 1.0  # 当前 p_node (循环中会更新)
        
        # 实验参数
        self.snr = 16.0                         # 目标 SNR (命令行传入)
        self.p_node_levels = [0.6, 0.7, 0.8, 0.9]  # 可信度范围 (不含 1.0)
        self.n = 4                              # 当前节点数 (命令行传入)
        self.rounds_per_config = 30             # 每组配置的测试轮数
        self.vote_deadline = 0.4                # 投票截止时间 (秒)，原2.0，5倍加速
        self.stabilize_time = 2.0               # SNR 切换后的稳定时间，原10.0，5倍加速
        self.snr_tolerance = 3.0
        self.cluster_timeout = 0.4  # 原2.0，5倍加速
        
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
            'vote_requests_sent': 0,
            'votes_received_total': 0,
            'votes_expected_total': 0,
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
            self.stats['vote_requests_sent'] += 1
            return request_id
    
    def _resend_vote_request(self, request_id: int):
        """重发投票请求 (相同 request_id，不清空已收到的投票)"""
        with self.lock:
            entry = LogEntry(
                term=self.current_term,
                index=len(self.log) + 1,
                command=f"RESEND_{request_id}"
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
                vote_request_id=request_id  # 使用相同的 request_id
            )
            
            self._broadcast(msg)
    
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
        
        注意：这里只统计 Follower 的投票（用于计算有效规模）
              Follower ID 是 1~n 中排除 Leader 的节点
        
        Args:
            request_id: 投票请求 ID
            n: 当前系统规模 (只统计 Follower ID 的节点)
        
        Returns:
            (yes_votes, no_votes, total_votes) - 只包含 Follower 投票
        """
        with self.votes_lock:
            yes_votes = 0
            no_votes = 0
            
            # n 表示总节点数，Follower ID 是 1~n 中排除 Leader 的节点
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            
            for node_id, success in self.votes_received.items():
                # 只统计 Follower ID 的节点
                if node_id in follower_ids:
                    if success:
                        yes_votes += 1
                    else:
                        no_votes += 1
            
            total_votes = yes_votes + no_votes
            return yes_votes, no_votes, total_votes
    
    def collect_weighted_votes(self, request_id: int, n: int) -> Tuple[float, float, bool]:
        """
        收集加权投票结果 (基于 SNR 的微小权重差异)
        
        算法设计：
        1. 收集所有 Follower 的投票 (伯努利试验结果)
        2. Leader 也做伯努利试验投票
        3. 共识判定：在收到的投票中，加权赞成 > 加权反对
           (注意：不是要求超过系统总节点数的一半，而是在参与者中多数)
        4. 平票时用 SNR 权重打破僵局
        
        Args:
            request_id: 投票请求 ID
            n: 当前系统规模 (只统计 ID <= n 的节点)
        
        Returns:
            (W_yes, W_total, consensus_reached)
        """
        with self.votes_lock:
            # 1. 收集 Follower 的投票
            # n 表示总节点数，Follower ID 是 1~n 中排除 Leader 的节点
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            voters = []
            for node_id, success in self.votes_received.items():
                if node_id in follower_ids:
                    snr = 0.0
                    if node_id in self.peers:
                        snr = self.peers[node_id].get('snr', 0.0)
                    voters.append({'id': node_id, 'success': success, 'snr': snr})
            
            # 2. Leader 投票 (也做伯努利试验)
            # 使用特殊 ID = -1 以避免与 Follower ID 冲突
            max_follower_snr = max((v['snr'] for v in voters), default=self.target_snr)
            leader_virtual_snr = max_follower_snr + 2.0
            leader_vote = random.random() < self.current_p_node
            voters.append({'id': -1, 'success': leader_vote, 'snr': leader_virtual_snr, 'is_leader': True})
            
            # 3. 计算 SNR 权重 (用于平票决胜)
            snr_values = [v['snr'] for v in voters]
            snr_min = min(snr_values)
            snr_max = max(snr_values)
            snr_range = snr_max - snr_min if snr_max > snr_min else 1.0
            
            for v in voters:
                v['weight'] = 1.0 + 0.001 * (v['snr'] - snr_min) / snr_range
            
            # 4. 统计加权投票
            W_yes = sum(v['weight'] for v in voters if v['success'])
            W_no = sum(v['weight'] for v in voters if not v['success'])
            W_total = W_yes + W_no
            
            # 5. 判定：加权赞成 > 加权反对 (在参与者中多数)
            consensus_reached = W_yes > W_no
            
            return W_yes, W_total, consensus_reached
    
    def collect_weighted_votes_debug(self, request_id: int, n: int) -> Tuple[float, float, bool, str]:
        """
        收集加权投票结果 (调试版，带详细信息)
        
        算法设计：
        1. 收集所有 Follower 的投票 + Leader 伯努利投票
        2. 共识判定：加权赞成 > 加权反对 (在参与者中多数)
        3. 平票时 SNR 权重自动打破僵局
        
        Returns:
            (W_yes, W_total, consensus_reached, details_str)
        """
        with self.votes_lock:
            # 1. 收集 Follower 的投票
            # n 表示总节点数，Follower ID 是 1~n 中排除 Leader 的节点
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            voters = []
            for node_id, success in self.votes_received.items():
                if node_id in follower_ids:
                    snr = 0.0
                    if node_id in self.peers:
                        snr = self.peers[node_id].get('snr', 0.0)
                    voters.append({'id': node_id, 'success': success, 'snr': snr})
            
            # 2. Leader 投票 (也做伯努利试验)
            # 使用特殊 ID = -1 以避免与 Follower ID 冲突
            max_follower_snr = max((v['snr'] for v in voters), default=self.target_snr)
            leader_virtual_snr = max_follower_snr + 2.0
            leader_vote = random.random() < self.current_p_node
            voters.append({'id': -1, 'success': leader_vote, 'snr': leader_virtual_snr, 'is_leader': True})
            
            # 3. 计算 SNR 权重
            snr_values = [v['snr'] for v in voters]
            snr_min = min(snr_values)
            snr_max = max(snr_values)
            snr_range = snr_max - snr_min if snr_max > snr_min else 1.0
            
            for v in voters:
                v['weight'] = 1.0 + 0.001 * (v['snr'] - snr_min) / snr_range
            
            # 4. 统计加权投票
            W_yes = sum(v['weight'] for v in voters if v['success'])
            W_no = sum(v['weight'] for v in voters if not v['success'])
            W_total = W_yes + W_no
            
            # 5. 判定：加权赞成 > 加权反对
            consensus_reached = W_yes > W_no
            
            # 6. 生成详细信息字符串
            # n 表示总节点数，Follower ID 是 1~n 中排除 Leader 的节点
            follower_ids = [i for i in range(1, n + 1) if i != self.node_id]
            follower_count = len([v for v in voters if v.get('id', 0) in follower_ids])
            no_reply = len(follower_ids) - follower_count
            
            # Leader 投票状态
            leader_icon = "✓" if leader_vote else "✗"
            
            # Follower 投票状态 (只显示实际存在的 Follower)
            follower_vote_strs = []
            for fid in follower_ids:
                v = next((x for x in voters if x.get('id') == fid and not x.get('is_leader')), None)
                if v is None:
                    follower_vote_strs.append(f"F{fid}:-")
                elif v['success']:
                    follower_vote_strs.append(f"F{fid}:✓")
                else:
                    follower_vote_strs.append(f"F{fid}:✗")
            
            yes_count = sum(1 for v in voters if v['success'])
            no_count = sum(1 for v in voters if not v['success'])
            
            result_icon = "✓共识" if consensus_reached else "✗未达"
            
            # 调试：打印权重分配
            # leader_w = next((v['weight'] for v in voters if v.get('is_leader')), 1.0)
            # print(f"        [DEBUG] Leader权重={leader_w:.4f}, snr_range={snr_range:.2f}")
            
            details = (f"赞成:{yes_count} 反对:{no_count} 未回复:{no_reply} | "
                      f"L:{leader_icon} {' '.join(follower_vote_strs)} | "
                      f"W_yes={W_yes:.3f}>W_no={W_no:.3f}? {result_icon}")
            
            return W_yes, W_total, consensus_reached, details
    
    def _handle_append_response(self, msg: Message):
        """处理投票响应"""
        # 更新邻居 SNR
        self._update_peer(msg.sender_id, msg.phy_state)
        
        # 记录投票 (只记录带有效 request_id 的响应)
        if hasattr(msg, 'vote_request_id') and msg.vote_request_id > 0:
            with self.votes_lock:
                # 只记录最新一轮的投票
                if msg.vote_request_id == self.vote_request_id:
                    # 记录投票（不在这里打印，在轮次结束时统一显示）
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
    
    def print_cluster_status(self):
        """打印详细的集群状态"""
        now = time.time()
        print("\n" + "─" * 60)
        print("📡 集群状态")
        print("─" * 60)
        print(f"   节点 {self.node_id:2d} (Leader)    SNR: ---- (本机)    ✅ 在线")
        
        with self.lock:
            for peer_id in sorted(self.peers.keys()):
                info = self.peers[peer_id]
                age = now - info['last_seen']
                if age <= self.cluster_timeout:
                    status = "✅ 在线"
                    snr_str = f"{info['snr']:5.1f}dB"
                else:
                    status = "❌ 离线"
                    snr_str = "-----"
                print(f"   节点 {peer_id:2d} (Follower)  SNR: {snr_str}      {status}  ({age:.1f}s前)")
        
        active = self.get_active_peer_count()
        print(f"\n   活跃节点数: {active}/{self.total_nodes}")
        print("─" * 60)
    
    def wait_for_snr_stable(self, target_snr: float, timeout: float = 30.0) -> bool:
        """等待 SNR 稳定"""
        print(f"\n⏳ 等待 SNR 稳定到 {target_snr} dB...")
        print("   (节点将通过增益调整逼近目标 SNR)")
        
        start_time = time.time()
        stable_count = 0
        required_stable = 3
        
        while time.time() - start_time < timeout:
            time.sleep(0.4)  # 原2.0，5倍加速
            
            with self.lock:
                if not self.peers:
                    print("   ⚠️ 暂无节点响应...")
                    continue
                
                # 打印各节点 SNR 状态
                print(f"\n   📊 SNR 状态 (目标: {target_snr} dB)")
                snr_diffs = []
                for peer_id in sorted(self.peers.keys()):
                    info = self.peers[peer_id]
                    if time.time() - info['last_seen'] <= self.cluster_timeout:
                        diff = abs(info['snr'] - target_snr)
                        snr_diffs.append(diff)
                        if diff <= self.snr_tolerance:
                            status = "✅"
                        elif diff <= self.snr_tolerance * 2:
                            status = "⚠️"
                        else:
                            status = "❌"
                        print(f"      节点 {peer_id}: {info['snr']:5.1f} dB (偏差 {diff:+.1f}) {status}")
                
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
        """运行单层循环实验 (p_node)"""
        self.experiment_running = True
        
        n = self.n  # 固定节点数
        snr = self.snr  # 固定 SNR
        total_configs = len(self.p_node_levels)
        total_rounds = total_configs * self.rounds_per_config
        
        print("\n" + "=" * 70)
        print("🔬 可靠性共识实验开始")
        print("=" * 70)
        print(f"\n📋 实验参数:")
        print(f"   ├─ 目标 SNR:       {snr} dB (固定)")
        print(f"   ├─ p_node 等级:   {self.p_node_levels}")
        print(f"   ├─ 节点数 n:       {n} (固定)")
        print(f"   ├─ 每组测试轮数:  {self.rounds_per_config}")
        print(f"   ├─ 投票截止时间:  {self.vote_deadline}s")
        print(f"   └─ 总配置数:      {total_configs} 组 ({total_rounds} 轮)")
        print("\n" + "=" * 70)
        
        # 打印实验开始时的集群状态
        self.print_cluster_status()
        
        # 设置目标 SNR 并等待稳定
        self.target_snr = snr
        print(f"\n{'='*70}")
        print(f"📡 目标 SNR: {snr} dB")
        print(f"{'='*70}")
        self.wait_for_snr_stable(snr, timeout=self.stabilize_time)
        
        config_idx = 0
        experiment_start = time.time()
        
        for p_node in self.p_node_levels:
            # ===== 循环：p_node =====
            self.current_p_node = p_node
            self.current_n = n
            config_idx += 1
            
            print(f"\n   🎲 设置 p_node = {p_node}")
            
            # 广播新的 p_node，让 Follower 更新
            for _ in range(5):
                self.send_heartbeat()
                time.sleep(0.04)  # 原0.2，5倍加速
            
            # 计算预估剩余时间
            elapsed = time.time() - experiment_start
            if config_idx > 1:
                avg_time_per_config = elapsed / (config_idx - 1)
                remaining = avg_time_per_config * (total_configs - config_idx + 1)
                eta_str = f"预计剩余 {remaining/60:.1f} 分钟"
            else:
                eta_str = ""
            
            # 进度条
            progress = config_idx / total_configs
            bar_len = 20
            filled = int(bar_len * progress)
            bar = "█" * filled + "░" * (bar_len - filled)
            
            print(f"\n   ┌─────────────────────────────────────────────────────")
            print(f"   │ [{config_idx}/{total_configs}] {bar} {progress*100:.0f}%  {eta_str}")
            print(f"   │ SNR={snr}dB, p_node={p_node}, n={n}")
            print(f"   └─────────────────────────────────────────────────────")
            print(f"   🔴 开始数据记录... (共 {self.rounds_per_config} 轮)")
            
            # 执行 K 轮测试
            success_count = 0
            effective_scales = []
            config_start_time = time.time()
            
            for k in range(self.rounds_per_config):
                # a. 发送投票请求
                request_id = self.send_vote_request(f"DECISION_{config_idx}_{k}")
                
                # b. 在 deadline 内多次重发投票请求 (提高可靠性)
                resend_interval = 0.06  # 每 0.06s 重发一次 (原0.3，5倍加速)
                elapsed = 0
                while elapsed < self.vote_deadline - resend_interval:
                    time.sleep(resend_interval)
                    elapsed += resend_interval
                    # 重发相同的投票请求 (相同 request_id)
                    self._resend_vote_request(request_id)
                
                # 等待最后一段时间让回复到达
                remaining = self.vote_deadline - elapsed
                if remaining > 0:
                    time.sleep(remaining)
                
                # c. 收集加权投票 (使用 SNR 打破偶数节点平票)
                W_yes, W_total, consensus, vote_details = self.collect_weighted_votes_debug(request_id, n)
                
                # 同时获取简单计数用于记录有效规模
                yes, no, total = self.collect_votes(request_id, n)
                
                # 更新丢包率统计
                # n 表示总节点数，Follower 有 n-1 个
                follower_count = n - 1
                self.stats['votes_expected_total'] += follower_count
                self.stats['votes_received_total'] += total
                
                # d. 记录有效系统规模 (不含 Leader 的虚拟投票)
                effective_scales.append(total)
                
                # e. 判定系统是否正确 (使用加权投票结果)
                # 加权版：W_yes > W_total / 2
                if consensus:
                    success_count += 1
                
                # 详细日志：前 5 轮打印投票详情
                if k < 5:
                    print(f"      🗳️ 轮 {k+1}: {vote_details}")
                
                # f. 冷却时间：让网络"静一静"，减少 UDP 缓冲区溢出风险
                time.sleep(0.02)  # 原0.1，5倍加速
                
                # 每 10 轮打印一次进度
                print_interval = min(10, max(1, self.rounds_per_config // 5))
                if (k + 1) % print_interval == 0 or k == self.rounds_per_config - 1:
                    p_sys_so_far = success_count / (k + 1)
                    avg_scale_so_far = statistics.mean(effective_scales)
                    # 计算当前配置的丢包率
                    curr_expected = follower_count * (k + 1)
                    curr_received = sum(effective_scales)
                    curr_loss = 1.0 - curr_received / curr_expected if curr_expected > 0 else 0
                    elapsed_config = time.time() - config_start_time
                    print(f"      📈 {k+1:3d}/{self.rounds_per_config}: "
                          f"P_sys={p_sys_so_far:.2f} 规模={avg_scale_so_far:.1f} "
                          f"丢包={curr_loss*100:.0f}% ({elapsed_config:.0f}s)")
            
            # 计算统计结果
            p_sys = success_count / self.rounds_per_config
            avg_effective_scale = statistics.mean(effective_scales)
            std_effective_scale = statistics.stdev(effective_scales) if len(effective_scales) > 1 else 0
            
            # 计算本轮丢包率
            # n 表示总节点数，Follower 有 n-1 个
            follower_count = n - 1
            config_expected = follower_count * self.rounds_per_config
            config_received = sum(effective_scales)
            config_loss = 1.0 - config_received / config_expected if config_expected > 0 else 0
            
            result = {
                'snr': snr,
                'p_node': p_node,
                'n': n,
                'p_sys': p_sys,
                'avg_effective_scale': avg_effective_scale,
                'std_effective_scale': std_effective_scale,
                'success_count': success_count,
                'total_rounds': self.rounds_per_config,
                'packet_loss_rate': config_loss,
                'raw_effective_scales': effective_scales
            }
            self.results.append(result)
            
            # 结果显示
            if p_sys >= 0.9:
                status = "🟢"
            elif p_sys >= 0.7:
                status = "🟡"
            else:
                status = "🔴"
            print(f"   {status} P_sys={p_sys:.2f} 规模={avg_effective_scale:.1f}±{std_effective_scale:.1f} 丢包={config_loss*100:.0f}%")
        
        # 计算总耗时
        total_time = time.time() - experiment_start
        print(f"\n⏱️ 实验总耗时: {total_time/60:.1f} 分钟")
        
        self.experiment_running = False
        self._print_final_results()
        self._save_results()
    
    def _print_final_results(self):
        """打印最终结果"""
        print("\n" + "=" * 80)
        print("📊 实验结果汇总")
        print("=" * 80)
        
        print(f"\n--- SNR = {self.snr} dB, n = {self.n} ---")
        print(f"{'p_node':<8} {'P_sys':<8} {'丢包率':<10} {'有效规模':<15}")
        print("-" * 50)
        
        for r in self.results:
            loss_rate = r.get('packet_loss_rate', 0.0)
            print(f"{r['p_node']:<8.2f} "
                  f"{r['p_sys']:<8.3f} "
                  f"{loss_rate*100:>5.1f}%    "
                  f"{r['avg_effective_scale']:.2f}±{r['std_effective_scale']:.2f}")
        
        print("=" * 80)
    
    def _save_results(self):
        """保存结果到 JSON 文件"""
        import os
        
        # 获取脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 按参数分类：results/n{节点数}_snr{信噪比}/
        param_folder = f"n{self.n}_snr{self.snr:.0f}"
        results_dir = os.path.join(script_dir, "..", "results", param_folder)
        
        # 确保目录存在
        os.makedirs(results_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"reliability_{timestamp}.json"
        filepath = os.path.join(results_dir, filename)
        
        data = {
            'start_time': datetime.now().isoformat(),
            'total_nodes': self.total_nodes,
            'snr': self.snr,
            'n': self.n,
            'p_node_levels': self.p_node_levels,
            'rounds_per_config': self.rounds_per_config,
            'vote_deadline': self.vote_deadline,
            'results': self.results
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"\n💾 结果已保存到: {filepath}")
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
                # 计算丢包率
                expected = self.stats.get('votes_expected_total', 0)
                received = self.stats.get('votes_received_total', 0)
                if expected > 0:
                    loss_rate = 1.0 - received / expected
                    loss_str = f", 丢包率={loss_rate*100:.1f}%"
                else:
                    loss_str = ""
                print(f"📊 活跃:{active} | SNR={self.target_snr}dB | p={self.current_p_node}{loss_str}")
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
    parser.add_argument("--snr", type=float, required=True,
                        help="目标 SNR (手动指定，不再循环枚举)")
    parser.add_argument("--p-node-levels", type=str, default="0.6,0.7,0.8,0.9",
                        help="p_node 等级 (逗号分隔，不含 1.0)")
    parser.add_argument("--n", type=int, required=True,
                        help="当前节点数 (手动指定，不再循环枚举)")
    parser.add_argument("--rounds", type=int, default=30, help="每组配置测试轮数")
    parser.add_argument("--vote-deadline", type=float, default=0.4, help="投票截止时间 (5倍加速)")
    parser.add_argument("--stabilize-time", type=float, default=2.0, 
                        help="SNR 切换后稳定时间 (5倍加速)")
    args = parser.parse_args()
    
    node = LeaderReliability(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx
    )
    
    # 解析实验参数
    node.snr = args.snr  # 实验目标 SNR（按下回车后使用）
    node.target_snr = 16.0  # 预热阶段固定 16.0 dB
    node.p_node_levels = [float(x) for x in args.p_node_levels.split(',')]
    node.n = args.n  # 固定节点数
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
    print(f"预热阶段 SNR: 16.0 dB | 实验目标 SNR: {args.snr} dB")
    print("等待 Follower 节点加入...")
    print("=" * 60 + "\n")
    
    # 预热阶段：显示节点连接状态
    print("🔄 预热阶段：等待节点加入...")
    print("   每 3 秒刷新一次状态，按 Enter 开始实验\n")
    
    import select
    import sys
    
    while True:
        node.print_cluster_status()
        
        # 非阻塞检查 stdin
        readable, _, _ = select.select([sys.stdin], [], [], 3.0)
        if readable:
            sys.stdin.readline()  # 消费输入
            break
    
    # 按下回车后，切换到实验目标 SNR
    node.target_snr = args.snr
    
    # 最终确认
    print("\n" + "=" * 60)
    print(f"🎯 切换到实验目标 SNR: {args.snr} dB")
    node.print_cluster_status()
    print("=" * 60)
    print("\n🚀 开始实验...")
    
    try:
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

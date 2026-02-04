#!/usr/bin/env python3
"""
SNR-集群规模关系实验 - Leader 端
==============================

基于 raft_leader_snr_broadcast.py，添加实验功能：
1. 从高 SNR 开始逐步降低目标 SNR
2. 在每个 SNR 等级测量多次集群规模
3. 记录并保存实验结果

使用方法:
    python3 raft_leader_snr_experiment.py --id 1 --total 6 --tx 10001 --rx 20001 \\
        --start-snr 20.0 --snr-step 2.0 --measurements 100

作者: V2V-Raft-SDR 项目
"""

import socket
import time
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
    target_snr: float = 0.0  # 目标 SNR

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
        self.heartbeat_interval = 0.5   # 增大心跳间隔，减少广播风暴
        self.snr_threshold = 0.0        # Leader 不过滤
        self.status_interval = 2.0
        self.snr_report_interval = 1.0  # SNR 报告间隔
        self.target_snr = 20.0          # 当前目标 SNR
        
        # 实验参数
        self.start_snr = 20.0           # 起始目标 SNR
        self.snr_step = 2.0             # SNR 递减步长
        self.min_snr = 0.0              # 最小 SNR
        self.measurements_per_snr = 100  # 每个 SNR 测量次数
        self.measurement_interval = 0.5  # 测量间隔 (秒)
        self.stabilize_time = 30.0       # 最大稳定等待时间 (秒)
        self.cluster_timeout = 2.0       # 判断节点在线的超时时间 (秒)
        self.snr_stable_tolerance = 3.0  # SNR 稳定容差 (dB)
        self.snr_stable_count_required = 3  # 需要连续稳定的次数
        self.min_active_peers = 1        # 最少需要的活跃节点数
        self.snr_check_interval = 2.0    # 稳定性检测间隔 (秒)
        
        # 实验结果
        self.results: List[dict] = []  # 每个 SNR 的完整结果
        self.experiment_running = False
        
        # 统计
        self.stats = {
            'heartbeats_sent': 0,
            'snr_reports_sent': 0,
            'entries_replicated': 0,
            'commands_committed': 0,
        }
        
        # 丢包率统计 (每个测量周期)
        self.packet_stats = {}  # {peer_id: {'sent': 0, 'received': 0}}
        
        # 网络
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        print(f"🔬 [节点 {node_id}] 实验 LEADER")
        print(f"   TX:{tx_port} RX:{rx_port}")
        print(f"   起始 SNR: {self.start_snr} dB, 步长: {self.snr_step} dB")

    def send_heartbeat(self):
        """发送心跳 - 携带目标 SNR"""
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
                entries=entries,
                target_snr=self.target_snr  # 携带目标 SNR
            )
            self._broadcast(msg)
            self.stats['heartbeats_sent'] += 1
            
            # 记录心跳发送 (用于丢包率统计)
            if self.experiment_running:
                self.record_heartbeat_sent()
    
    def send_snr_report(self):
        """广播 SNR 报告 - 携带目标 SNR"""
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
                snr_report=snr_data,
                target_snr=self.target_snr  # 携带目标 SNR
            )
            self._broadcast(msg)
            self.stats['snr_reports_sent'] += 1
    
    # ========================================================================
    # 实验相关方法
    # ========================================================================
    
    def get_cluster_size(self) -> int:
        """获取当前集群规模 (在线节点数 + Leader 自己)"""
        now = time.time()
        with self.lock:
            active_count = 1  # Leader 自己
            for peer_id, info in self.peers.items():
                if now - info['last_seen'] <= self.cluster_timeout:
                    active_count += 1
            return active_count
    
    def get_active_peers(self) -> List[int]:
        """获取活跃的 Follower 列表"""
        now = time.time()
        with self.lock:
            active = []
            for peer_id, info in self.peers.items():
                if now - info['last_seen'] <= self.cluster_timeout:
                    active.append(peer_id)
            return sorted(active)
    
    def reset_packet_stats(self):
        """重置丢包统计 (在每个 SNR 测量开始前调用)"""
        with self.lock:
            self.packet_stats = {}
            for peer_id in self.peers.keys():
                self.packet_stats[peer_id] = {'sent': 0, 'received': 0}
    
    def record_heartbeat_sent(self):
        """记录发送了一次心跳"""
        with self.lock:
            for peer_id in self.packet_stats:
                self.packet_stats[peer_id]['sent'] += 1
    
    def record_response_received(self, peer_id: int):
        """记录收到某节点的响应"""
        with self.lock:
            if peer_id in self.packet_stats:
                self.packet_stats[peer_id]['received'] += 1
    
    def get_packet_loss_rates(self) -> Dict[int, float]:
        """获取各节点的丢包率"""
        with self.lock:
            loss_rates = {}
            for peer_id, stats in self.packet_stats.items():
                sent = stats['sent']
                received = stats['received']
                if sent > 0:
                    loss_rates[peer_id] = 1.0 - (received / sent)
                else:
                    loss_rates[peer_id] = 0.0
            return loss_rates
    
    def get_average_packet_loss(self) -> float:
        """获取平均丢包率"""
        loss_rates = self.get_packet_loss_rates()
        if loss_rates:
            return statistics.mean(loss_rates.values())
        return 0.0
    
    def check_snr_stable(self) -> Tuple[bool, Dict[int, float]]:
        """检查所有活跃节点的 SNR 是否稳定在目标值附近"""
        active_peers = self.get_active_peers()
        
        if len(active_peers) < self.min_active_peers:
            return False, {}
        
        snr_dict = {}
        all_stable = True
        
        with self.lock:
            for peer_id in active_peers:
                info = self.peers.get(peer_id, {})
                snr = info.get('snr', 0.0)
                snr_dict[peer_id] = snr
                
                diff = abs(snr - self.target_snr)
                if diff > self.snr_stable_tolerance:
                    all_stable = False
        
        return all_stable, snr_dict
    
    def wait_for_snr_stable(self, infinite_wait: bool = False, timeout: float = None) -> bool:
        """等待所有活跃节点的 SNR 稳定
        
        Args:
            infinite_wait: 如果为 True，则无限等待（用于调试/验证连接）
            timeout: 超时时间 (秒)，如果为 None 则使用默认值 self.stabilize_time
        """
        stable_count = 0
        wait_start = time.time()
        check_count = 0
        
        effective_timeout = timeout if timeout is not None else self.stabilize_time
        
        print(f"   ⏳ 等待 SNR 稳定 (目标: {self.target_snr}±{self.snr_stable_tolerance} dB, 超时: {effective_timeout}s)...")
        if infinite_wait:
            print(f"   💡 调试模式：无限等待，按 Ctrl+C 退出")
        
        while self.running:
            # 检查超时（非无限等待模式）
            if not infinite_wait and time.time() - wait_start >= effective_timeout:
                print(f"   ⚠️ 等待超时，使用当前状态继续")
                return True
            
            time.sleep(self.snr_check_interval)
            check_count += 1
            
            is_stable, snr_dict = self.check_snr_stable()
            active_peers = self.get_active_peers()
            
            # 显示所有已知节点的 SNR（包括不活跃的）
            all_peers_status = []
            with self.lock:
                for peer_id in sorted(self.peers.keys()):
                    info = self.peers[peer_id]
                    snr = info.get('snr', 0)
                    age = time.time() - info.get('last_seen', 0)
                    if age <= self.cluster_timeout:
                        all_peers_status.append(f"N{peer_id}:{snr:.1f}✓")
                    else:
                        all_peers_status.append(f"N{peer_id}:{snr:.1f}(超时{age:.0f}s)")
            
            status_str = ", ".join(all_peers_status) if all_peers_status else "无节点"
            
            if len(active_peers) == 0:
                print(f"      [{check_count}] ❌ 无活跃节点 | 已知: [{status_str}]")
            elif is_stable:
                stable_count += 1
                print(f"      [{check_count}] ✓ 稳定 {stable_count}/{self.snr_stable_count_required}: "
                      f"活跃{len(active_peers)}个 [{status_str}]")
                
                if not infinite_wait and stable_count >= self.snr_stable_count_required:
                    print(f"   ✅ SNR 已稳定！活跃节点: {len(active_peers)} 个")
                    return True
            else:
                if stable_count > 0:
                    print(f"      [{check_count}] ✗ 不稳定，重置: 活跃{len(active_peers)}个 [{status_str}]")
                else:
                    print(f"      [{check_count}] … 等待: 活跃{len(active_peers)}个 [{status_str}]")
                stable_count = 0
        
        return False
    
    def run_experiment(self):
        """运行实验"""
        self.experiment_running = True
        self.target_snr = self.start_snr
        
        print("\n" + "=" * 60)
        print("🔬 开始 SNR-集群规模关系实验")
        if hasattr(self, 'debug_wait') and self.debug_wait:
            print("⚠️  调试模式：将在第一个 SNR 等级无限等待")
        print("=" * 60)
        
        first_snr = True
        while self.target_snr >= self.min_snr and self.running:
            print(f"\n{'─' * 60}")
            print(f"📊 测试目标 SNR = {self.target_snr} dB")
            print(f"{'─' * 60}")
            
            # 等待 SNR 稳定
            # 第一轮给予更长的时间 (120s) 以便手动启动节点，后续使用默认配置
            current_timeout = 120.0 if first_snr else self.stabilize_time
            use_infinite_wait = first_snr and hasattr(self, 'debug_wait') and self.debug_wait
            
            if not self.wait_for_snr_stable(infinite_wait=use_infinite_wait, timeout=current_timeout):
                if use_infinite_wait:
                    print("实验中止")
                    break
            first_snr = False
            
            # 显示当前各节点 SNR
            active_peers = self.get_active_peers()
            print(f"   当前活跃节点 ({len(active_peers)} 个):")
            with self.lock:
                for peer_id in active_peers:
                    info = self.peers.get(peer_id, {})
                    snr = info.get('snr', 0)
                    diff = snr - self.target_snr
                    status = "✓" if abs(diff) <= self.snr_stable_tolerance else "✗"
                    print(f"      Node {peer_id}: {snr:.1f} dB (差值: {diff:+.1f}) {status}")
            
            # 重置丢包统计
            self.reset_packet_stats()
            
            # 进行测量
            print(f"   📏 开始 {self.measurements_per_snr} 次集群规模测量...")
            measurements = []
            actual_snr_samples = {}  # {peer_id: [snr_samples]}
            
            for i in range(self.measurements_per_snr):
                if not self.running:
                    return
                
                cluster_size = self.get_cluster_size()
                measurements.append(cluster_size)
                
                # 收集各节点当前实际 SNR
                with self.lock:
                    for peer_id, info in self.peers.items():
                        if peer_id not in actual_snr_samples:
                            actual_snr_samples[peer_id] = []
                        actual_snr_samples[peer_id].append(info.get('snr', 0.0))
                
                if (i + 1) % 20 == 0:
                    avg_so_far = statistics.mean(measurements)
                    avg_loss = self.get_average_packet_loss() * 100
                    print(f"      进度: {i+1}/{self.measurements_per_snr}, 平均规模: {avg_so_far:.2f}, 丢包率: {avg_loss:.1f}%")
                
                time.sleep(self.measurement_interval)
            
            # 计算统计
            avg_size = statistics.mean(measurements)
            std_size = statistics.stdev(measurements) if len(measurements) > 1 else 0.0
            
            # 获取丢包率
            loss_rates = self.get_packet_loss_rates()
            avg_loss = self.get_average_packet_loss()
            
            # 计算各节点平均实际 SNR
            actual_snr_per_node = {}
            actual_snr_std_per_node = {}
            for peer_id, samples in actual_snr_samples.items():
                if samples:
                    actual_snr_per_node[peer_id] = statistics.mean(samples)
                    actual_snr_std_per_node[peer_id] = statistics.stdev(samples) if len(samples) > 1 else 0.0
            
            # 计算所有节点的平均实际 SNR
            all_actual_snr = [v for v in actual_snr_per_node.values()]
            avg_actual_snr = statistics.mean(all_actual_snr) if all_actual_snr else 0.0
            std_actual_snr = statistics.stdev(all_actual_snr) if len(all_actual_snr) > 1 else 0.0
            
            # 保存结果
            result = {
                'target_snr': self.target_snr,
                'avg_cluster_size': avg_size,
                'std_cluster_size': std_size,
                'avg_packet_loss': avg_loss,
                'packet_loss_per_node': loss_rates,
                'raw_cluster_measurements': measurements,
                'actual_snr_per_node': actual_snr_per_node,
                'actual_snr_std_per_node': actual_snr_std_per_node,
                'avg_actual_snr': avg_actual_snr,
                'std_actual_snr': std_actual_snr
            }
            self.results.append(result)
            
            print(f"\n   ✅ SNR={self.target_snr}dB 结果:")
            print(f"      平均集群规模: {avg_size:.2f} ± {std_size:.2f}")
            print(f"      最小: {min(measurements)}, 最大: {max(measurements)}")
            print(f"      平均丢包率: {avg_loss*100:.1f}%")
            for peer_id, loss in sorted(loss_rates.items()):
                print(f"         Node {peer_id}: {loss*100:.1f}%")
            print(f"      平均实际SNR: {avg_actual_snr:.1f} ± {std_actual_snr:.1f} dB")
            for peer_id, snr in sorted(actual_snr_per_node.items()):
                std = actual_snr_std_per_node.get(peer_id, 0)
                print(f"         Node {peer_id}: {snr:.1f} ± {std:.1f} dB")
            
            # 检查是否停止
            if avg_size <= 1.0:
                print(f"\n   🛑 平均集群规模 ≤ 1，实验结束")
                break
            
            # 降低目标 SNR
            # 🔧 动态步长调整: >8dB 时步长2.0, <=8dB 时步长0.5 (精细测量低信噪比区域)
            current_step = 2.0 if self.target_snr > 8.001 else 0.5
            self.target_snr -= current_step
        
        self.experiment_running = False
        self._print_final_results()
        self._save_results()
    
    def _print_final_results(self):
        """打印最终结果"""
        print("\n" + "=" * 80)
        print("📊 实验结果汇总")
        print("=" * 80)
        print(f"{'目标SNR':<10} {'实际SNR':<12} {'平均规模':<12} {'标准差':<10} {'丢包率':<10}")
        print("-" * 60)
        for r in self.results:
            target = r['target_snr']
            actual = r.get('avg_actual_snr', 0)
            avg = r['avg_cluster_size']
            std = r['std_cluster_size']
            loss = r['avg_packet_loss'] * 100
            print(f"{target:<10.1f} {actual:<12.1f} {avg:<12.2f} {std:<10.2f} {loss:<10.1f}%")
        print("=" * 80)
    
    def _save_results(self):
        """保存结果到 JSON 文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"snr_experiment_results_{timestamp}.json"
        
        data = {
            'start_time': datetime.now().isoformat(),
            'total_nodes': self.total_nodes,
            'start_snr': self.start_snr,
            'snr_step': self.snr_step,
            'measurements_per_snr': self.measurements_per_snr,
            'results': [
                {
                    'target_snr': r['target_snr'],
                    'average_cluster_size': r['avg_cluster_size'],
                    'std_cluster_size': r['std_cluster_size'],
                    'average_packet_loss': r['avg_packet_loss'],
                    'packet_loss_per_node': {str(k): v for k, v in r['packet_loss_per_node'].items()},
                    'raw_cluster_measurements': r['raw_cluster_measurements'],
                    'avg_actual_snr': r.get('avg_actual_snr', 0),
                    'std_actual_snr': r.get('std_actual_snr', 0),
                    'actual_snr_per_node': {str(k): v for k, v in r.get('actual_snr_per_node', {}).items()},
                    'actual_snr_std_per_node': {str(k): v for k, v in r.get('actual_snr_std_per_node', {}).items()}
                }
                for r in self.results
            ]
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"\n💾 结果已保存到: {filename}")
        except Exception as e:
            print(f"❌ 保存失败: {e}")
    
    # ========================================================================
    # 原有方法
    # ========================================================================
    
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
                        # 记录收到响应 (用于丢包率统计)
                        if self.experiment_running:
                            self.record_response_received(msg.sender_id)
                        
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
    parser = argparse.ArgumentParser(description="SNR-集群规模实验 Leader")
    parser.add_argument("--id", type=int, required=True, help="节点 ID")
    parser.add_argument("--total", type=int, default=6, help="总节点数")
    parser.add_argument("--tx", type=int, required=True, help="TX 端口")
    parser.add_argument("--rx", type=int, required=True, help="RX 端口")
    # 实验参数
    parser.add_argument("--start-snr", type=float, default=20.0, help="起始目标 SNR")
    parser.add_argument("--snr-step", type=float, default=2.0, help="SNR 递减步长")
    parser.add_argument("--measurements", type=int, default=100, help="每个 SNR 测量次数")
    parser.add_argument("--stabilize-time", type=float, default=30.0, help="最大稳定等待时间 (秒)")
    parser.add_argument("--snr-tolerance", type=float, default=3.0, help="SNR 稳定容差 (dB)")
    parser.add_argument("--stable-count", type=int, default=3, help="需要连续稳定的次数")
    parser.add_argument("--min-peers", type=int, default=1, help="最少需要的活跃节点数")
    parser.add_argument("--debug-wait", action="store_true", help="调试模式：无限等待SNR稳定")
    args = parser.parse_args()
    
    node = LeaderWithSNRBroadcast(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx
    )
    
    # 应用实验参数
    node.start_snr = args.start_snr
    node.target_snr = args.start_snr
    node.snr_step = args.snr_step
    node.measurements_per_snr = args.measurements
    node.stabilize_time = args.stabilize_time
    node.snr_stable_tolerance = args.snr_tolerance
    node.snr_stable_count_required = args.stable_count
    node.min_active_peers = args.min_peers
    node.debug_wait = args.debug_wait
    
    # 启动接收线程
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    # 启动主循环线程 (保持心跳和 SNR 报告)
    t_main = threading.Thread(target=node.main_loop, daemon=True)
    t_main.start()
    
    print("\n" + "=" * 60)
    print("准备就绪！")
    print("等待 Follower 节点加入...")
    print("SNR 稳定后将自动开始实验")
    print("=" * 60 + "\n")
    
    try:
        # 运行实验
        node.run_experiment()
    except KeyboardInterrupt:
        print("\n🛑 实验中断")
        if node.results:
            node._print_final_results()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

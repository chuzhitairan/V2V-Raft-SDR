#!/usr/bin/env python3
"""
可靠性共识实验 - Follower 端
============================

基于 raft_follower_snr_experiment.py，添加"传感器可信度模拟"功能：
1. 接收 Leader 广播的 p_node 参数
2. 收到日志请求时，以 p_node 概率返回 success=True（正确），
   以 (1-p_node) 概率返回 success=False（误判）
3. 注意：无论正确还是误判，都会回复（区分"网络丢包"和"节点反对"）

使用方法:
    python3 raft_follower_reliability.py --id 2 --total 6 \
        --tx 10002 --rx 20002 --ctrl 9002

作者: V2V-Raft-SDR 项目
"""

import socket
import time
import random
import json
import argparse
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict

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
    p_node: float = 1.0          # 节点可信度参数 (0.0-1.0)
    vote_request_id: int = 0      # 投票请求 ID (用于区分不同的投票轮次)

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
# Follower 节点 (可靠性实验版)
# ============================================================================

class FollowerReliability:
    """
    可靠性实验版 Follower
    
    在原有增益调整基础上，增加：
    1. 接收 Leader 广播的 p_node 参数
    2. 模拟传感器误判：以 (1-p_node) 概率回复 success=False
    """
    
    def __init__(self, node_id: int, total_nodes: int, 
                 tx_port: int, rx_port: int, ctrl_port: int, leader_id: int = 1):
        self.node_id = node_id
        self.role = 'follower'
        self.total_nodes = total_nodes
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.ctrl_port = ctrl_port
        self.leader_id = leader_id
        
        # Raft 状态
        self.current_term = 1
        self.log: List[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0
        
        # 增益控制 (复用)
        self.current_tx_gain = 0.5
        self.min_gain = 0.1
        self.max_gain = 0.8
        self.target_snr = 20.0
        self.snr_tolerance = 2.0
        self.gain_step = 0.05
        self.last_observed_snr = 0.0
        self.gain_adjust_count = 0
        
        # 可靠性实验参数
        self.p_node = 1.0              # 当前节点可信度 (默认完美)
        self.vote_stats = {
            'total_votes': 0,
            'yes_votes': 0,
            'no_votes': 0,
        }
        
        # 邻居记录
        self.peers: Dict[int, dict] = {}
        
        # 配置
        self.snr_threshold = 0.0
        self.status_interval = 2.0
        
        # 统计
        self.stats = {
            'heartbeats_received': 0,
            'snr_reports_received': 0,
            'gain_adjustments': 0,
            'commands_committed': 0,
        }
        
        # 网络
        self.lock = threading.RLock()
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BROADCAST_IP, self.rx_port))
        
        # 控制 socket
        self.ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl_sock.settimeout(1.0)
        
        print(f"👥 [节点 {node_id}] FOLLOWER (可靠性实验版)")
        print(f"   TX:{tx_port} RX:{rx_port} Ctrl:{ctrl_port}")
        print(f"   初始 p_node: {self.p_node}")

    def handle_append(self, msg: Message):
        """
        处理 APPEND 消息 - 无状态伯努利投票
        
        修改点 (移除日志一致性检查):
        1. 不检查 prev_log_index / prev_log_term (无前序检查)
        2. 不做日志截断 (无冲突处理)
        3. 收到就投票，纯粹基于 p_node 的伯努利试验
        4. last_log_index 返回收到的日志 index (而非本地日志长度)
        
        这确保每轮实验都是独立的伯努利试验，不受历史丢包影响。
        """
        with self.lock:
            self.stats['heartbeats_received'] += 1
            
            # 更新 p_node (如果 Leader 广播了新的值)
            if hasattr(msg, 'p_node') and msg.p_node > 0:
                if abs(msg.p_node - self.p_node) > 0.001:
                    print(f"🎲 [可信度更新] p_node: {self.p_node:.2f} -> {msg.p_node:.2f}")
                    self.p_node = msg.p_node
            
            # 更新目标 SNR (如果有)
            if hasattr(msg, 'target_snr') and msg.target_snr > 0:
                if abs(msg.target_snr - self.target_snr) > 0.1:
                    print(f"🎯 [目标SNR更新] {self.target_snr:.1f} -> {msg.target_snr:.1f} dB")
                    self.target_snr = msg.target_snr
            
            # ===== 伯努利投票 (无状态) =====
            # 收到 APPEND 消息说明 SNR 足够、通信层成功
            # 纯粹基于 p_node 决定投票结果
            rand_val = random.random()
            if rand_val < self.p_node:
                # 传感器正常 -> 赞成 (success=True)
                vote_success = True
                self.vote_stats['yes_votes'] += 1
            else:
                # 传感器故障 -> 反对 (success=False)
                vote_success = False
                self.vote_stats['no_votes'] += 1
            
            self.vote_stats['total_votes'] += 1
            
            # 获取收到的日志 index (用于回复)
            received_log_index = 0
            if msg.entries:
                received_log_index = msg.entries[-1].index
            
            # 构造回复
            # 关键: last_log_index 设为收到的日志 index (不是本地日志长度)
            # 这表明 "我针对第 N 条日志投了 赞成/反对 票"
            reply = Message(
                type="APPEND_RESPONSE",
                term=self.current_term,
                sender_id=self.node_id,
                success=vote_success,
                last_log_index=received_log_index,  # 关键变化!
                vote_request_id=msg.vote_request_id
            )
            
            # 无条件追加日志 (不检查索引是否连续)
            # 即使投了反对票也追加，保证状态同步 (弱一致性)
            if msg.entries:
                for entry in msg.entries:
                    # 直接追加，不管是否已存在或索引是否连续
                    self.log.append(entry)
            
            # 更新 commit (无论赞成还是反对都更新，保持弱一致性)
            if msg.leader_commit > self.commit_index:
                self.commit_index = msg.leader_commit
                self._apply_committed()
            
            # 🔧 随机抖动，避免冲突
            time.sleep(random.uniform(0.01, 0.05))
            self._broadcast(reply)
    
    def handle_snr_report(self, msg: Message):
        """处理 SNR 报告，调整增益 (复用)"""
        self.stats['snr_reports_received'] += 1
        
        # 更新动态目标 SNR
        if hasattr(msg, 'target_snr') and msg.target_snr > 0:
            if abs(msg.target_snr - self.target_snr) > 0.1:
                self.target_snr = msg.target_snr
        
        # 更新 p_node
        if hasattr(msg, 'p_node') and msg.p_node > 0:
            if abs(msg.p_node - self.p_node) > 0.001:
                print(f"🎲 [可信度更新] p_node: {self.p_node:.2f} -> {msg.p_node:.2f}")
                self.p_node = msg.p_node
        
        # 查找自己的 SNR
        my_snr = msg.snr_report.get(self.node_id, None)
        if my_snr is None:
            return
        
        self.last_observed_snr = my_snr
        
        # 计算偏差并调整增益
        snr_diff = my_snr - self.target_snr
        
        if abs(snr_diff) <= self.snr_tolerance:
            return
        
        adjust_factor = -snr_diff / 5.0
        gain_delta = self.gain_step * adjust_factor
        gain_delta = max(-0.15, min(0.15, gain_delta))
        
        new_gain = self.current_tx_gain + gain_delta
        new_gain = max(self.min_gain, min(self.max_gain, new_gain))
        
        if abs(new_gain - self.current_tx_gain) > 0.001:
            old_gain = self.current_tx_gain
            self.current_tx_gain = new_gain
            self.gain_adjust_count += 1
            self.stats['gain_adjustments'] += 1
            
            success = self._set_phy_tx_gain(new_gain)
            
            direction = "📈" if gain_delta > 0 else "📉"
            status = "✅" if success else "❌"
            print(f"{direction} [增益调整] SNR={my_snr:.1f}dB, "
                  f"TX: {old_gain:.3f} -> {new_gain:.3f} {status}")
    
    def _set_phy_tx_gain(self, gain: float) -> bool:
        """通过控制端口设置 PHY TX 增益"""
        try:
            cmd = json.dumps({"cmd": "set_tx_gain", "value": gain})
            self.ctrl_sock.sendto(cmd.encode(), (BROADCAST_IP, self.ctrl_port))
            
            try:
                response, _ = self.ctrl_sock.recvfrom(1024)
                result = json.loads(response.decode())
                return result.get('status') == 'ok'
            except socket.timeout:
                return False
        except Exception as e:
            print(f"❌ 设置增益失败: {e}")
            return False
    
    def _apply_committed(self):
        """应用已提交日志"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied - 1]
            self.stats['commands_committed'] += 1
            # print(f"✨ [共识] 执行命令 #{entry.index}: {entry.command}")
    
    def _update_peer(self, sender_id: int, phy_state: PhyState):
        """更新邻居状态"""
        if sender_id not in self.peers:
            self.peers[sender_id] = {'snr': 0.0, 'last_seen': 0.0, 'count': 0}
        self.peers[sender_id]['snr'] = phy_state.snr
        self.peers[sender_id]['last_seen'] = time.time()
        self.peers[sender_id]['count'] += 1
    
    def _broadcast(self, msg: Message):
        """发送消息"""
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
                    
                    if msg.type == "APPEND" or msg.type == "HEARTBEAT":
                        self.handle_append(msg)
                    elif msg.type == "SNR_REPORT":
                        self.handle_snr_report(msg)
                        
            except Exception as e:
                if self.running:
                    print(f"接收错误: {e}")
    
    def main_loop(self):
        """主循环"""
        print("🟢 主循环启动")
        last_status = time.time()
        
        while self.running:
            now = time.time()
            
            if now - last_status >= self.status_interval:
                self._print_status()
                last_status = now
            
            time.sleep(0.05)
    
    def _print_status(self):
        """打印状态"""
        with self.lock:
            snr_diff = self.last_observed_snr - self.target_snr
            if self.last_observed_snr > 0:
                if abs(snr_diff) <= self.snr_tolerance:
                    status = "✅"
                elif snr_diff < 0:
                    status = "📉"
                else:
                    status = "📈"
            else:
                status = "❓"
            
            total = self.vote_stats['total_votes']
            yes = self.vote_stats['yes_votes']
            no = self.vote_stats['no_votes']
            yes_rate = (yes / total * 100) if total > 0 else 0
            
            print(f"\n📊 [Follower {self.node_id}] p_node={self.p_node:.2f}")
            print(f"   SNR: {self.last_observed_snr:.1f}dB (目标{self.target_snr}) {status}")
            print(f"   TX增益: {self.current_tx_gain:.3f}")
            print(f"   投票: {total}次 (赞成{yes}/{yes_rate:.1f}%, 反对{no})")
    
    def stop(self):
        self.running = False
        self.sock.close()
        self.ctrl_sock.close()


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Follower 节点 (可靠性实验版)")
    parser.add_argument("--id", type=int, required=True, help="节点 ID")
    parser.add_argument("--role", type=str, default='follower', help="角色")
    parser.add_argument("--total", type=int, default=6, help="总节点数")
    parser.add_argument("--tx", type=int, required=True, help="TX 端口")
    parser.add_argument("--rx", type=int, required=True, help="RX 端口")
    parser.add_argument("--ctrl", type=int, required=True, help="PHY 控制端口")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader ID")
    parser.add_argument("--target-snr", type=float, default=20.0, help="目标 SNR")
    parser.add_argument("--snr-tolerance", type=float, default=2.0, help="SNR 容差")
    parser.add_argument("--init-gain", type=float, default=0.5, help="初始 TX 增益")
    parser.add_argument("--p-node", type=float, default=1.0, help="初始节点可信度")
    parser.add_argument("--status-interval", type=float, default=2.0, help="状态打印间隔")
    args = parser.parse_args()
    
    node = FollowerReliability(
        node_id=args.id,
        total_nodes=args.total,
        tx_port=args.tx,
        rx_port=args.rx,
        ctrl_port=args.ctrl,
        leader_id=args.leader_id
    )
    node.target_snr = args.target_snr
    node.snr_tolerance = args.snr_tolerance
    node.current_tx_gain = args.init_gain
    node.p_node = args.p_node
    node.status_interval = args.status_interval
    
    # 设置初始增益
    node._set_phy_tx_gain(args.init_gain)
    
    t_recv = threading.Thread(target=node.recv_loop, daemon=True)
    t_recv.start()
    
    try:
        node.main_loop()
    except KeyboardInterrupt:
        print("\n🛑 停止")
        node._print_status()
    finally:
        node.stop()


if __name__ == "__main__":
    main()

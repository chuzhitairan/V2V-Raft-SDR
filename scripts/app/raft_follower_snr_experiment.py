#!/usr/bin/env python3
"""
SNR-集群规模关系实验 - Follower 端
==================================

基于 raft_follower_gain_adjust.py，接收 Leader 广播的动态目标 SNR，
自动调整 TX 增益使 SNR 接近目标值。

使用方法:
    python3 raft_follower_snr_experiment.py --id 2 --total 6 \
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
    """消息结构"""
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
    target_snr: float = 0.0  # 动态目标 SNR

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
# Follower 节点 (带增益调整)
# ============================================================================

class FollowerWithGainAdjust:
    """
    带自动增益调整的 Follower
    
    接收 Leader 的 SNR 报告，根据反馈调整 TX 增益。
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
        
        # 增益控制
        self.current_tx_gain = 0.7      # 当前 TX 增益
        self.min_gain = 0.1             # 最小增益
        self.max_gain = 0.7             # 最大增益
        self.target_snr = 20.0          # 目标 SNR
        self.snr_tolerance = 2.0        # SNR 容差
        self.gain_step = 0.05           # 基础调整步长 (增大加快收敛)
        self.last_observed_snr = 0.0    # 上次观测到的 SNR
        self.gain_adjust_count = 0      # 增益调整次数
        
        # 邻居记录
        self.peers: Dict[int, dict] = {}
        
        # 配置
        self.snr_threshold = 0.0        # 不过滤
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
        
        # 控制 socket (用于调整 PHY 增益)
        self.ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl_sock.settimeout(1.0)
        
        print(f"👥 [节点 {node_id}] FOLLOWER (增益自动调整版)")
        print(f"   TX:{tx_port} RX:{rx_port} Ctrl:{ctrl_port}")
        print(f"   目标 SNR: {self.target_snr} dB ± {self.snr_tolerance} dB")
        print(f"   初始 TX 增益: {self.current_tx_gain}")

    def handle_append(self, msg: Message):
        """处理 APPEND 消息"""
        with self.lock:
            self.stats['heartbeats_received'] += 1
            
            reply = Message(
                type="APPEND_RESPONSE",
                term=self.current_term,
                sender_id=self.node_id,
                success=False,
                last_log_index=len(self.log)
            )
            
            # 日志一致性检查
            if msg.prev_log_index > 0:
                if len(self.log) < msg.prev_log_index:
                    self._broadcast(reply)
                    return
                if self.log[msg.prev_log_index - 1].term != msg.prev_log_term:
                    self.log = self.log[:msg.prev_log_index - 1]
                    self._broadcast(reply)
                    return
            
            # 追加日志
            if msg.entries:
                new_entries = []
                for entry in msg.entries:
                    if entry.index > len(self.log):
                        new_entries.append(entry)
                    elif self.log[entry.index - 1].term != entry.term:
                        self.log = self.log[:entry.index - 1]
                        new_entries.append(entry)
                
                if new_entries:
                    self.log.extend(new_entries)
                    print(f"📥 [复制] 收到 {len(new_entries)} 条新日志")
            
            # 更新 commit
            if msg.leader_commit > self.commit_index:
                self.commit_index = min(msg.leader_commit, len(self.log))
                self._apply_committed()
            
            reply.success = True
            reply.last_log_index = len(self.log)
            self._broadcast(reply)
    
    def handle_snr_report(self, msg: Message):
        """处理 SNR 报告，调整增益"""
        self.stats['snr_reports_received'] += 1
        
        # 更新动态目标 SNR (如果 Leader 发送了 target_snr)
        if hasattr(msg, 'target_snr') and msg.target_snr > 0:
            if abs(msg.target_snr - self.target_snr) > 0.1:
                print(f"🎯 [目标SNR更新] {self.target_snr:.1f} -> {msg.target_snr:.1f} dB")
                self.target_snr = msg.target_snr
        
        # 查找自己的 SNR
        my_snr = msg.snr_report.get(self.node_id, None)
        if my_snr is None:
            return
        
        self.last_observed_snr = my_snr
        
        # 计算偏差
        snr_diff = my_snr - self.target_snr
        
        # 判断是否需要调整
        if abs(snr_diff) <= self.snr_tolerance:
            # 在容差范围内，不调整
            return
        
        # 计算调整量 (比例调整)
        # SNR 低了 -> 需要增加增益
        # SNR 高了 -> 需要降低增益
        adjust_factor = -snr_diff / 5.0  # 每 5dB 偏差调整一个步长倍率 (加快收敛)
        gain_delta = self.gain_step * adjust_factor
        
        # 限制单次调整幅度
        gain_delta = max(-0.15, min(0.15, gain_delta))  # 增大最大调整幅度
        
        new_gain = self.current_tx_gain + gain_delta
        new_gain = max(self.min_gain, min(self.max_gain, new_gain))
        
        if abs(new_gain - self.current_tx_gain) > 0.001:
            old_gain = self.current_tx_gain
            self.current_tx_gain = new_gain
            self.gain_adjust_count += 1
            self.stats['gain_adjustments'] += 1
            
            # 通过控制端口调整 PHY 增益
            success = self._set_phy_tx_gain(new_gain)
            
            direction = "📈" if gain_delta > 0 else "📉"
            status = "✅" if success else "❌"
            print(f"{direction} [增益调整 #{self.gain_adjust_count}] "
                  f"SNR={my_snr:.1f}dB (目标{self.target_snr}), "
                  f"TX增益: {old_gain:.3f} -> {new_gain:.3f} {status}")
    
    def _set_phy_tx_gain(self, gain: float) -> bool:
        """通过控制端口设置 PHY TX 增益"""
        try:
            cmd = json.dumps({"cmd": "set_tx_gain", "value": gain})
            self.ctrl_sock.sendto(cmd.encode(), (BROADCAST_IP, self.ctrl_port))
            
            # 等待响应
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
            print(f"✨ [共识] 执行命令 #{entry.index}: {entry.command}")
    
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
            # 🔧 增加随机抖动，避免多个 Follower 同时回复导致冲突
            if msg.type in ["APPEND_RESPONSE", "VOTE_RESPONSE"]:
                time.sleep(random.uniform(0.01, 0.05))

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
                    status = "✅ 正常"
                elif snr_diff < 0:
                    status = "📉 偏低"
                else:
                    status = "📈 偏高"
            else:
                status = "❓ 未知"
            
            print(f"\n📊 [Follower 状态] Node {self.node_id}")
            print(f"   Leader 观测我的 SNR: {self.last_observed_snr:.1f} dB "
                  f"(目标 {self.target_snr} dB) {status}")
            print(f"   当前 TX 增益: {self.current_tx_gain:.3f}")
            print(f"   日志: {len(self.log)}, 提交: {self.commit_index}")
            print(f"   心跳: {self.stats['heartbeats_received']}, "
                  f"SNR报告: {self.stats['snr_reports_received']}, "
                  f"增益调整: {self.stats['gain_adjustments']}")
    
    def stop(self):
        self.running = False
        self.sock.close()
        self.ctrl_sock.close()


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Follower 节点 (带增益调整)")
    parser.add_argument("--id", type=int, required=True, help="节点 ID")
    parser.add_argument("--role", type=str, default='follower', help="角色 (仅支持 follower)")
    parser.add_argument("--total", type=int, default=6, help="总节点数")
    parser.add_argument("--tx", type=int, required=True, help="TX 端口")
    parser.add_argument("--rx", type=int, required=True, help="RX 端口")
    parser.add_argument("--ctrl", type=int, required=True, help="PHY 控制端口")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader ID")
    parser.add_argument("--target-snr", type=float, default=20.0, help="目标 SNR (dB)")
    parser.add_argument("--snr-tolerance", type=float, default=2.0, help="SNR 容差 (dB)")
    parser.add_argument("--init-gain", type=float, default=0.7, help="初始 TX 增益")
    parser.add_argument("--status-interval", type=float, default=2.0, help="状态打印间隔")
    args = parser.parse_args()
    
    if args.role != 'follower':
        print("⚠️  此脚本仅支持 follower 角色")
        return
    
    node = FollowerWithGainAdjust(
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

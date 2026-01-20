#!/usr/bin/env python3
"""
多节点增益调优工具
==================
同时启动多个 SDR，测试不同增益下的整体通信丢包率。

使用方法:
    python3 scripts/app/multi_gain_tuner.py
    python3 scripts/app/multi_gain_tuner.py --tx-range 0.6 0.8 0.1 --rx-range 0.6 0.8 0.1
"""

import socket
import time
import json
import argparse
import subprocess
import signal
import os
import sys
import threading
from dataclasses import dataclass
from typing import List, Dict, Tuple
import csv
from datetime import datetime

# ==========================================
# 配置 - 你的 6 台 SDR
# ==========================================

SDR_CONFIG = [
    {"id": 1, "sdr_args": "addr=192.168.1.10", "tx_port": 10001, "rx_port": 20001, "ctrl_port": 9001},
    {"id": 2, "sdr_args": "addr=192.168.1.11", "tx_port": 10002, "rx_port": 20002, "ctrl_port": 9002},
    {"id": 3, "sdr_args": "addr=192.168.1.12", "tx_port": 10003, "rx_port": 20003, "ctrl_port": 9003},
    {"id": 4, "sdr_args": "addr=192.168.1.13", "tx_port": 10004, "rx_port": 20004, "ctrl_port": 9004},
    {"id": 5, "sdr_args": "serial=U200100",    "tx_port": 10005, "rx_port": 20005, "ctrl_port": 9005},
    {"id": 6, "sdr_args": "serial=U200101",    "tx_port": 10006, "rx_port": 20006, "ctrl_port": 9006},
]

# ==========================================
# 数据结构
# ==========================================

@dataclass
class TestResult:
    tx_gain: float
    rx_gain: float
    total_sent: int
    total_received: int
    loss_rate: float
    avg_snr: float
    node_stats: Dict[int, dict]  # 每个节点的统计

# ==========================================
# PHY 层管理
# ==========================================

class MultiPhyManager:
    def __init__(self, sdr_configs: List[dict]):
        self.configs = sdr_configs
        self.processes = {}
        self.active_nodes = []  # 记录成功启动的节点
        self.project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    def start_all(self, tx_gain: float, rx_gain: float) -> bool:
        """分批启动所有 PHY 层 (先 E200 再 U200，避免冲突)"""
        print(f"🚀 分批启动 {len(self.configs)} 个 PHY 层...")
        
        # 分离 E200 和 U200
        e200_configs = [c for c in self.configs if 'addr=' in c['sdr_args']]
        u200_configs = [c for c in self.configs if 'serial=' in c['sdr_args']]
        
        self.active_nodes = []
        
        # 第一批: E200 (网络设备) - 逐个启动，避免网络冲突
        if e200_configs:
            print(f"   === 第一批: {len(e200_configs)} 个 E200 ===")
            for cfg in e200_configs:
                node_id = cfg['id']
                print(f"   启动 Node {node_id}: {cfg['sdr_args']}", end=" ", flush=True)
                
                if self._start_single_phy(cfg, tx_gain, rx_gain):
                    print("✓")
                    self.active_nodes.append(cfg)
                else:
                    print("❌")
                
                # E200 之间间隔 3 秒，避免网络冲突
                time.sleep(3)
        
        # 第二批: U200 (USB 设备) - 可以并行启动
        if u200_configs:
            print(f"   === 第二批: {len(u200_configs)} 个 U200 ===")
            for cfg in u200_configs:
                node_id = cfg['id']
                print(f"   启动 Node {node_id}: {cfg['sdr_args']}")
                
                cmd = self._build_cmd(cfg, tx_gain, rx_gain)
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setsid
                    )
                    self.processes[node_id] = proc
                except Exception as e:
                    print(f"   ❌ Node {node_id} 启动失败: {e}")
            
            # U200 等待初始化
            print(f"   等待 U200 初始化 (12 秒)...", end=" ", flush=True)
            time.sleep(12)
            print("完成")
            
            # 检查 U200 状态
            for cfg in u200_configs:
                node_id = cfg['id']
                ok = False
                for attempt in range(3):
                    if self._ping_ctrl(cfg['ctrl_port']):
                        ok = True
                        break
                    time.sleep(1)
                
                if ok:
                    print(f"     Node {node_id}: ✓")
                    self.active_nodes.append(cfg)
                else:
                    print(f"     Node {node_id}: ❌")
        
        print(f"\n   📊 {len(self.active_nodes)}/{len(self.configs)} 个节点就绪")
        print(f"   活跃节点: {[c['id'] for c in self.active_nodes]}")
        
        # 至少有 2 个节点才能测试
        return len(self.active_nodes) >= 2
    
    def _build_cmd(self, cfg: dict, tx_gain: float, rx_gain: float) -> List[str]:
        """构建 PHY 启动命令"""
        return [
            sys.executable,
            os.path.join(self.project_dir, "scripts/core/v2v_hw_phy.py"),
            "--sdr-args", cfg['sdr_args'],
            "--tx-gain", str(tx_gain),
            "--rx-gain", str(rx_gain),
            "--udp-recv-port", str(cfg['tx_port']),
            "--udp-send-port", str(cfg['rx_port']),
            "--ctrl-port", str(cfg['ctrl_port']),
            "--no-gui"
        ]
    
    def _start_single_phy(self, cfg: dict, tx_gain: float, rx_gain: float) -> bool:
        """启动单个 PHY 并等待就绪"""
        node_id = cfg['id']
        cmd = self._build_cmd(cfg, tx_gain, rx_gain)
        
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
            self.processes[node_id] = proc
            
            # 等待初始化
            time.sleep(8)
            
            # 检查控制端口
            for attempt in range(5):
                if self._ping_ctrl(cfg['ctrl_port']):
                    return True
                time.sleep(1)
            
            return False
        except:
            return False
    
    def _ping_ctrl(self, port: int) -> bool:
        """检查控制端口是否响应"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            cmd = json.dumps({"cmd": "ping"})
            sock.sendto(cmd.encode(), ('127.0.0.1', port))
            data, _ = sock.recvfrom(1024)
            sock.close()
            resp = json.loads(data.decode())
            return resp.get('msg') == 'pong'
        except:
            return False
    
    def get_active_configs(self) -> List[dict]:
        """获取活跃节点配置"""
        return self.active_nodes
    
    def set_all_gains(self, tx_gain: float, rx_gain: float) -> bool:
        """只设置活跃节点的增益 (带重试)"""
        if not self.active_nodes:
            return False
        
        success_count = 0
        for cfg in self.active_nodes:
            node_ok = False
            # 每个节点最多重试 3 次
            for attempt in range(3):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(2.0)  # 增加超时时间
                    
                    # 设置 TX 增益
                    cmd = json.dumps({"cmd": "set_tx_gain", "value": tx_gain})
                    sock.sendto(cmd.encode(), ('127.0.0.1', cfg['ctrl_port']))
                    sock.recvfrom(1024)
                    
                    # 设置 RX 增益
                    cmd = json.dumps({"cmd": "set_rx_gain", "value": rx_gain})
                    sock.sendto(cmd.encode(), ('127.0.0.1', cfg['ctrl_port']))
                    sock.recvfrom(1024)
                    
                    sock.close()
                    node_ok = True
                    break
                except:
                    time.sleep(0.5)
            
            if node_ok:
                success_count += 1
        
        # 只要有超过一半的节点成功就算成功
        return success_count >= len(self.active_nodes) // 2 + 1
    
    def stop_all(self):
        """停止所有 PHY 层"""
        print("🛑 停止所有 PHY 层...")
        for node_id, proc in self.processes.items():
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=3)
            except:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except:
                    pass
        self.processes.clear()
        
        # 强制清理
        try:
            subprocess.run(['pkill', '-f', 'v2v_hw_phy.py'], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
        time.sleep(2)

# ==========================================
# 多节点通信测试
# ==========================================

class MultiNodeTester:
    def __init__(self, sdr_configs: List[dict]):
        self.configs = sdr_configs
        self.results = {}  # node_id -> {sent, received, snr_list}
    
    def run_test(self, duration: float = 5.0, interval: float = 0.1) -> Dict:
        """
        运行多节点通信测试
        每个节点同时发送和接收消息
        """
        # 初始化统计
        stats = {}
        for cfg in self.configs:
            stats[cfg['id']] = {
                'sent': 0,
                'received': 0,
                'snr_list': [],
                'sources': set()  # 收到消息的来源节点
            }
        
        # 创建接收 socket
        rx_socks = {}
        for cfg in self.configs:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', cfg['rx_port']))
            sock.setblocking(False)
            rx_socks[cfg['id']] = sock
        
        # 创建发送 socket
        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        start_time = time.time()
        seq = 0
        
        try:
            while time.time() - start_time < duration:
                # 每个节点轮流发送
                for cfg in self.configs:
                    packet = json.dumps({
                        "type": "TEST",
                        "seq": seq,
                        "sender_id": cfg['id'],
                        "term": 0,
                        "ts": time.time(),
                        "phy_state": {"snr": 0.0}
                    })
                    tx_sock.sendto(packet.encode(), ('127.0.0.1', cfg['tx_port']))
                    stats[cfg['id']]['sent'] += 1
                    seq += 1
                
                # 尝试从所有节点接收
                for node_id, sock in rx_socks.items():
                    try:
                        while True:
                            data, _ = sock.recvfrom(4096)
                            try:
                                msg = json.loads(data.decode())
                                sender = msg.get('sender_id', -1)
                                
                                # 忽略自己发的包
                                if sender != node_id and sender > 0:
                                    stats[node_id]['received'] += 1
                                    stats[node_id]['sources'].add(sender)
                                    
                                    if 'phy_state' in msg:
                                        snr = msg['phy_state'].get('snr', 0)
                                        if snr > 0:
                                            stats[node_id]['snr_list'].append(snr)
                            except:
                                pass
                    except BlockingIOError:
                        pass
                
                time.sleep(interval)
        
        finally:
            for sock in rx_socks.values():
                sock.close()
            tx_sock.close()
        
        return stats

# ==========================================
# 主程序
# ==========================================

def generate_gain_range(start: float, end: float, step: float) -> List[float]:
    """生成增益范围"""
    gains = []
    g = start
    while g <= end + 0.001:
        gains.append(round(g, 2))
        g += step
    return gains

def print_results_table(results: List[TestResult]):
    """打印结果表格"""
    print("\n" + "=" * 90)
    print("测试结果汇总 (按丢包率排序)")
    print("=" * 90)
    print(f"{'TX Gain':>8} {'RX Gain':>8} {'总发送':>8} {'总接收':>8} {'丢包率':>8} {'平均SNR':>10} {'连通节点对':>12}")
    print("-" * 90)
    
    for r in sorted(results, key=lambda x: x.loss_rate):
        # 计算有多少节点对能互相通信
        pairs = sum(len(s.get('sources', set())) for s in r.node_stats.values())
        print(f"{r.tx_gain:>8.2f} {r.rx_gain:>8.2f} {r.total_sent:>8} {r.total_received:>8} "
              f"{r.loss_rate:>7.1f}% {r.avg_snr:>9.1f}dB {pairs:>12}")
    
    print("=" * 90)
    
    if results:
        best = min(results, key=lambda x: x.loss_rate)
        print(f"\n🏆 最佳配置: TX={best.tx_gain}, RX={best.rx_gain}")
        print(f"   整体丢包率: {best.loss_rate:.1f}%")
        print(f"   平均 SNR: {best.avg_snr:.1f}dB")
        
        # 打印每个节点的详细统计
        print("\n   各节点详情:")
        for node_id, stat in best.node_stats.items():
            sources = stat.get('sources', set())
            print(f"     Node {node_id}: 收到来自 {len(sources)} 个节点的消息 {sources if sources else '{}'}")

def save_results_csv(results: List[TestResult], filename: str):
    """保存结果到 CSV"""
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['tx_gain', 'rx_gain', 'total_sent', 'total_received', 
                        'loss_rate', 'avg_snr', 'connected_pairs'])
        for r in results:
            pairs = sum(len(s.get('sources', set())) for s in r.node_stats.values())
            writer.writerow([r.tx_gain, r.rx_gain, r.total_sent, r.total_received,
                           f"{r.loss_rate:.2f}", f"{r.avg_snr:.2f}", pairs])
    print(f"📁 结果已保存到: {filename}")

def main():
    parser = argparse.ArgumentParser(description="多节点增益调优工具")
    parser.add_argument("--tx-range", nargs=3, type=float, default=[0.5, 0.9, 0.1],
                       metavar=('START', 'END', 'STEP'),
                       help="TX 增益范围 [default: 0.5 0.9 0.1]")
    parser.add_argument("--rx-range", nargs=3, type=float, default=[0.5, 0.9, 0.1],
                       metavar=('START', 'END', 'STEP'),
                       help="RX 增益范围 [default: 0.5 0.9 0.1]")
    parser.add_argument("--duration", type=float, default=5.0, 
                       help="每次测试持续时间(秒) [default: 5.0]")
    parser.add_argument("--output", type=str, help="输出 CSV 文件路径")
    parser.add_argument("--nodes", type=str, default="1,2,3,4,5,6",
                       help="参与测试的节点 ID (逗号分隔) [default: 1,2,3,4,5,6]")
    args = parser.parse_args()
    
    # 过滤要测试的节点
    test_node_ids = [int(x.strip()) for x in args.nodes.split(',')]
    test_configs = [cfg for cfg in SDR_CONFIG if cfg['id'] in test_node_ids]
    
    if not test_configs:
        print("❌ 没有有效的节点配置")
        return
    
    # 生成增益范围
    tx_gains = generate_gain_range(*args.tx_range)
    rx_gains = generate_gain_range(*args.rx_range)
    
    total_tests = len(tx_gains) * len(rx_gains)
    print("=" * 60)
    print("多节点增益调优工具")
    print("=" * 60)
    print(f"测试节点: {[cfg['id'] for cfg in test_configs]}")
    print(f"TX 增益范围: {tx_gains}")
    print(f"RX 增益范围: {rx_gains}")
    print(f"总测试次数: {total_tests}")
    print(f"每次测试时长: {args.duration}s")
    print("=" * 60)
    
    # 初始化
    phy_manager = MultiPhyManager(test_configs)
    results = []
    
    try:
        # 启动所有 PHY
        if not phy_manager.start_all(tx_gains[0], rx_gains[0]):
            print("❌ PHY 层启动失败，活跃节点不足 2 个")
            return
        
        # 使用实际启动成功的节点进行测试
        active_configs = phy_manager.get_active_configs()
        tester = MultiNodeTester(active_configs)
        
        test_num = 0
        for tx_gain in tx_gains:
            for rx_gain in rx_gains:
                test_num += 1
                print(f"\n[{test_num}/{total_tests}] 测试 TX={tx_gain}, RX={rx_gain}...", end=" ", flush=True)
                
                # 动态调整活跃节点的增益
                if not phy_manager.set_all_gains(tx_gain, rx_gain):
                    print("❌ 设置增益失败")
                    continue
                
                time.sleep(1)  # 等待增益生效
                
                # 运行测试
                stats = tester.run_test(duration=args.duration)
                
                # 计算总体统计
                total_sent = sum(s['sent'] for s in stats.values())
                total_received = sum(s['received'] for s in stats.values())
                
                # 理论上每个节点发的包应该被其他所有节点收到
                # 如果 4 个节点，每个发 10 个包，总发 40 个
                # 每个包被其他 3 个节点收到，期望总接收 = 40 * 3 = 120
                num_active = len(active_configs)
                expected_received = total_sent * (num_active - 1) if num_active > 1 else 1
                loss_rate = (1 - total_received / expected_received) * 100 if expected_received > 0 else 100
                loss_rate = max(0, loss_rate)  # 丢包率不能为负
                
                # 平均 SNR
                all_snr = []
                for s in stats.values():
                    all_snr.extend(s['snr_list'])
                avg_snr = sum(all_snr) / len(all_snr) if all_snr else 0
                
                result = TestResult(
                    tx_gain=tx_gain,
                    rx_gain=rx_gain,
                    total_sent=total_sent,
                    total_received=total_received,
                    loss_rate=loss_rate,
                    avg_snr=avg_snr,
                    node_stats=stats
                )
                results.append(result)
                
                print(f"丢包: {loss_rate:.1f}%, SNR: {avg_snr:.1f}dB")
        
        # 输出结果
        print_results_table(results)
        
        # 保存 CSV
        if args.output:
            save_results_csv(results, args.output)
        else:
            project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            results_dir = os.path.join(project_dir, "results", "csv")
            os.makedirs(results_dir, exist_ok=True)
            filename = os.path.join(results_dir, f"multi_gain_tuning_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            save_results_csv(results, filename)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
        if results:
            print_results_table(results)
    finally:
        phy_manager.stop_all()

if __name__ == "__main__":
    main()

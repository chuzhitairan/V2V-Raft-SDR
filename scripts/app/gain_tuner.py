#!/usr/bin/env python3
"""
增益自动调优工具
================
扫描 TX/RX 增益组合，找到丢包率最低的配置。

使用方法:
    python3 scripts/app/gain_tuner.py --sdr-args "addr=192.168.1.10"
    python3 scripts/app/gain_tuner.py --sdr-args "addr=192.168.1.10" --tx-range 0.5 0.9 0.1 --rx-range 0.4 0.8 0.1
"""

import socket
import time
import json
import argparse
import subprocess
import signal
import os
import sys
from dataclasses import dataclass
from typing import List, Tuple
import csv
from datetime import datetime

# ==========================================
# 配置
# ==========================================

@dataclass
class TestResult:
    tx_gain: float
    rx_gain: float
    packets_sent: int
    packets_received: int
    loss_rate: float
    avg_snr: float
    avg_rtt_ms: float

# ==========================================
# PHY 层管理
# ==========================================

class PhyManager:
    def __init__(self, sdr_args: str, udp_recv_port: int, udp_send_port: int, ctrl_port: int):
        self.sdr_args = sdr_args
        self.udp_recv_port = udp_recv_port
        self.udp_send_port = udp_send_port
        self.ctrl_port = ctrl_port
        self.process = None
        self.project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    def start(self, tx_gain: float, rx_gain: float) -> bool:
        """启动 PHY 层 (跳过设备检查，直接尝试启动)"""
        cmd = [
            sys.executable,
            os.path.join(self.project_dir, "scripts/core/v2v_hw_phy.py"),
            "--sdr-args", self.sdr_args,
            "--tx-gain", str(tx_gain),
            "--rx-gain", str(rx_gain),
            "--udp-recv-port", str(self.udp_recv_port),
            "--udp-send-port", str(self.udp_send_port),
            "--ctrl-port", str(self.ctrl_port),
            "--no-gui"
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
            
            # 等待 PHY 初始化 (U200 + E200 混合时需要更长时间)
            wait_time = 12 if 'serial=' in self.sdr_args else 8
            print(f"等待 PHY 初始化 ({wait_time}s)...", end=" ", flush=True)
            time.sleep(wait_time)
            
            # 只通过控制端口检查是否成功 (多次尝试)
            for attempt in range(5):
                if self._ping_ctrl_port():
                    print("✓")
                    return True
                time.sleep(2)
            
            print("❌ 控制端口无响应")
            return False
        except Exception as e:
            print(f"\n❌ PHY 启动异常: {e}")
            return False
    
    def _ping_ctrl_port(self) -> bool:
        """检查控制端口是否响应"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            cmd = json.dumps({"cmd": "ping"})
            sock.sendto(cmd.encode(), ('127.0.0.1', self.ctrl_port))
            data, _ = sock.recvfrom(1024)
            sock.close()
            resp = json.loads(data.decode())
            return resp.get('msg') == 'pong'
        except:
            return False
    
    def stop(self):
        """停止 PHY 层"""
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except:
                    pass
            self.process = None
        
        # 强制清理所有残留进程
        try:
            subprocess.run(['pkill', '-f', 'v2v_hw_phy.py'], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
        
        # 等待端口释放
        time.sleep(2)
    
    def set_gains(self, tx_gain: float, rx_gain: float) -> bool:
        """通过控制端口动态调整增益"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.0)
            
            # 设置 TX 增益
            cmd = json.dumps({"cmd": "set_tx_gain", "value": tx_gain})
            sock.sendto(cmd.encode(), ('127.0.0.1', self.ctrl_port))
            sock.recvfrom(1024)
            
            # 设置 RX 增益
            cmd = json.dumps({"cmd": "set_rx_gain", "value": rx_gain})
            sock.sendto(cmd.encode(), ('127.0.0.1', self.ctrl_port))
            sock.recvfrom(1024)
            
            sock.close()
            return True
        except Exception as e:
            return False

# ==========================================
# 丢包率测试
# ==========================================

class PacketTester:
    def __init__(self, tx_port: int, rx_port: int):
        self.tx_port = tx_port
        self.rx_port = rx_port
    
    def run_test(self, num_packets: int = 100, interval: float = 0.05) -> Tuple[int, int, List[float], List[float]]:
        """
        发送测试包并统计响应
        返回: (发送数, 接收数, SNR列表, RTT列表)
        """
        # 创建接收 socket
        rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx_sock.bind(('127.0.0.1', self.rx_port))
        rx_sock.settimeout(0.1)
        
        # 创建发送 socket
        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        sent = 0
        received = 0
        snr_list = []
        rtt_list = []
        pending = {}  # seq -> send_time
        
        try:
            for seq in range(num_packets):
                # 构造测试包
                packet = json.dumps({
                    "type": "PING",
                    "seq": seq,
                    "ts": time.time(),
                    "sender_id": 0,  # 测试用
                    "term": 0,
                    "phy_state": {"snr": 0.0}
                })
                
                # 发送
                tx_sock.sendto(packet.encode(), ('127.0.0.1', self.tx_port))
                pending[seq] = time.time()
                sent += 1
                
                # 尝试接收响应 (非阻塞)
                try:
                    while True:
                        data, _ = rx_sock.recvfrom(4096)
                        try:
                            msg = json.loads(data.decode())
                            recv_time = time.time()
                            
                            # 提取 SNR
                            if 'phy_state' in msg:
                                snr = msg['phy_state'].get('snr', 0)
                                snr_list.append(snr)
                            
                            # 计算 RTT (如果是我们发的包回来了)
                            msg_seq = msg.get('seq', -1)
                            if msg_seq in pending:
                                rtt = (recv_time - pending[msg_seq]) * 1000
                                rtt_list.append(rtt)
                                del pending[msg_seq]
                            
                            received += 1
                        except:
                            pass
                except socket.timeout:
                    pass
                
                time.sleep(interval)
            
            # 最后等待一段时间接收剩余响应
            deadline = time.time() + 1.0
            while time.time() < deadline:
                try:
                    data, _ = rx_sock.recvfrom(4096)
                    try:
                        msg = json.loads(data.decode())
                        recv_time = time.time()
                        
                        if 'phy_state' in msg:
                            snr = msg['phy_state'].get('snr', 0)
                            snr_list.append(snr)
                        
                        msg_seq = msg.get('seq', -1)
                        if msg_seq in pending:
                            rtt = (recv_time - pending[msg_seq]) * 1000
                            rtt_list.append(rtt)
                            del pending[msg_seq]
                        
                        received += 1
                    except:
                        pass
                except socket.timeout:
                    pass
            
        finally:
            rx_sock.close()
            tx_sock.close()
        
        return sent, received, snr_list, rtt_list

# ==========================================
# 主程序
# ==========================================

def generate_gain_range(start: float, end: float, step: float) -> List[float]:
    """生成增益范围"""
    gains = []
    g = start
    while g <= end + 0.001:  # 浮点精度
        gains.append(round(g, 2))
        g += step
    return gains

def print_results_table(results: List[TestResult]):
    """打印结果表格"""
    print("\n" + "=" * 80)
    print("测试结果汇总")
    print("=" * 80)
    print(f"{'TX Gain':>8} {'RX Gain':>8} {'发送':>6} {'接收':>6} {'丢包率':>8} {'平均SNR':>10} {'平均RTT':>10}")
    print("-" * 80)
    
    for r in sorted(results, key=lambda x: x.loss_rate):
        print(f"{r.tx_gain:>8.2f} {r.rx_gain:>8.2f} {r.packets_sent:>6} {r.packets_received:>6} "
              f"{r.loss_rate:>7.1f}% {r.avg_snr:>9.1f}dB {r.avg_rtt_ms:>9.1f}ms")
    
    print("=" * 80)
    
    # 找出最佳配置
    if results:
        best = min(results, key=lambda x: x.loss_rate)
        print(f"\n🏆 最佳配置: TX={best.tx_gain}, RX={best.rx_gain}")
        print(f"   丢包率: {best.loss_rate:.1f}%, SNR: {best.avg_snr:.1f}dB, RTT: {best.avg_rtt_ms:.1f}ms")

def save_results_csv(results: List[TestResult], filename: str):
    """保存结果到 CSV"""
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['tx_gain', 'rx_gain', 'packets_sent', 'packets_received', 
                        'loss_rate', 'avg_snr', 'avg_rtt_ms'])
        for r in results:
            writer.writerow([r.tx_gain, r.rx_gain, r.packets_sent, r.packets_received,
                           f"{r.loss_rate:.2f}", f"{r.avg_snr:.2f}", f"{r.avg_rtt_ms:.2f}"])
    print(f"📁 结果已保存到: {filename}")

def main():
    parser = argparse.ArgumentParser(description="增益自动调优工具")
    parser.add_argument("--sdr-args", required=True, help="SDR 设备参数 (如 addr=192.168.1.10)")
    parser.add_argument("--tx-range", nargs=3, type=float, default=[0.4, 0.9, 0.1],
                       metavar=('START', 'END', 'STEP'),
                       help="TX 增益范围 [default: 0.4 0.9 0.1]")
    parser.add_argument("--rx-range", nargs=3, type=float, default=[0.4, 0.9, 0.1],
                       metavar=('START', 'END', 'STEP'),
                       help="RX 增益范围 [default: 0.4 0.9 0.1]")
    parser.add_argument("--packets", type=int, default=50, help="每次测试发送的包数 [default: 50]")
    parser.add_argument("--interval", type=float, default=0.05, help="发包间隔秒数 [default: 0.05]")
    parser.add_argument("--udp-recv-port", type=int, default=10000, help="PHY 接收端口")
    parser.add_argument("--udp-send-port", type=int, default=20000, help="PHY 发送端口")
    parser.add_argument("--ctrl-port", type=int, default=9999, help="控制端口")
    parser.add_argument("--output", type=str, help="输出 CSV 文件路径")
    parser.add_argument("--dynamic", action="store_true", 
                       help="使用动态调整增益模式（PHY 只启动一次）")
    args = parser.parse_args()
    
    # 生成增益范围
    tx_gains = generate_gain_range(*args.tx_range)
    rx_gains = generate_gain_range(*args.rx_range)
    
    total_tests = len(tx_gains) * len(rx_gains)
    print("=" * 60)
    print("增益自动调优工具")
    print("=" * 60)
    print(f"SDR: {args.sdr_args}")
    print(f"TX 增益范围: {tx_gains}")
    print(f"RX 增益范围: {rx_gains}")
    print(f"总测试次数: {total_tests}")
    print(f"每次测试包数: {args.packets}")
    print(f"模式: {'动态调整' if args.dynamic else '重启 PHY'}")
    print("=" * 60)
    
    # 初始化
    phy = PhyManager(args.sdr_args, args.udp_recv_port, args.udp_send_port, args.ctrl_port)
    tester = PacketTester(args.udp_recv_port, args.udp_send_port)
    results = []
    
    try:
        test_num = 0
        
        if args.dynamic:
            # 动态模式：PHY 只启动一次
            print("\n🚀 启动 PHY 层...")
            if not phy.start(tx_gains[0], rx_gains[0]):
                print("❌ PHY 启动失败")
                return
            time.sleep(2)
        
        for tx_gain in tx_gains:
            for rx_gain in rx_gains:
                test_num += 1
                print(f"\n[{test_num}/{total_tests}] 测试 TX={tx_gain}, RX={rx_gain}...", end=" ", flush=True)
                
                if args.dynamic:
                    # 动态调整增益
                    if not phy.set_gains(tx_gain, rx_gain):
                        print("❌ 设置增益失败")
                        continue
                    time.sleep(0.5)
                else:
                    # 重启 PHY
                    phy.stop()
                    time.sleep(1)
                    if not phy.start(tx_gain, rx_gain):
                        print("❌ PHY 启动失败")
                        continue
                    time.sleep(2)
                
                # 运行测试
                sent, received, snr_list, rtt_list = tester.run_test(args.packets, args.interval)
                
                # 计算统计
                loss_rate = (1 - received / sent) * 100 if sent > 0 else 100
                avg_snr = sum(snr_list) / len(snr_list) if snr_list else 0
                avg_rtt = sum(rtt_list) / len(rtt_list) if rtt_list else 0
                
                result = TestResult(
                    tx_gain=tx_gain,
                    rx_gain=rx_gain,
                    packets_sent=sent,
                    packets_received=received,
                    loss_rate=loss_rate,
                    avg_snr=avg_snr,
                    avg_rtt_ms=avg_rtt
                )
                results.append(result)
                
                print(f"丢包: {loss_rate:.1f}%, SNR: {avg_snr:.1f}dB")
        
        # 输出结果
        print_results_table(results)
        
        # 保存 CSV
        if args.output:
            save_results_csv(results, args.output)
        else:
            # 默认保存路径
            project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            results_dir = os.path.join(project_dir, "results", "csv")
            os.makedirs(results_dir, exist_ok=True)
            filename = os.path.join(results_dir, f"gain_tuning_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            save_results_csv(results, filename)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
        if results:
            print_results_table(results)
    finally:
        print("\n🛑 停止 PHY 层...")
        phy.stop()

if __name__ == "__main__":
    main()

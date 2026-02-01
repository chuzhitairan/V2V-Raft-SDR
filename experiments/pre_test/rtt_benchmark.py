#!/usr/bin/env python3
"""
RTT (Round-Trip Time) 测量工具

用于测量 SDR PHY 层的收发延迟，帮助确定 Raft 参数。
支持单板自回环模式。

用法:
    # 先启动 SDR PHY
    python3 core/v2v_hw_phy.py --sdr-args "addr=192.168.1.10"
    
    # 运行 RTT 测量
    python3 experiments/pre_test/rtt_benchmark.py --packets 100
"""

import socket
import time
import json
import argparse
import threading
import statistics
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime

# 默认端口 (与 v2v_hw_phy.py 一致)
DEFAULT_TX_PORT = 10000  # 发送到 SDR
DEFAULT_RX_PORT = 20000  # 从 SDR 接收


@dataclass
class PingMessage:
    """Ping 消息"""
    type: str = "ping"
    seq: int = 0
    timestamp: float = 0.0
    payload: str = ""  # 填充数据
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))
    
    @staticmethod
    def from_json(data: str) -> Optional['PingMessage']:
        try:
            d = json.loads(data)
            return PingMessage(**d)
        except:
            return None


class RTTBenchmark:
    def __init__(self, tx_port: int, rx_port: int, timeout: float = 2.0):
        self.tx_port = tx_port
        self.rx_port = rx_port
        self.timeout = timeout
        
        # 发送 socket
        self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # 接收 socket
        self.rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.rx_sock.bind(("0.0.0.0", rx_port))
        self.rx_sock.settimeout(timeout)
        
        # 结果存储
        self.pending = {}  # seq -> send_time
        self.rtts: List[float] = []
        self.lost = 0
        self.received = 0
        
        # 控制
        self.running = True
        self.lock = threading.Lock()
    
    def recv_loop(self):
        """接收线程"""
        while self.running:
            try:
                data, _ = self.rx_sock.recvfrom(4096)
                recv_time = time.time()
                
                msg = PingMessage.from_json(data.decode('utf-8'))
                if msg and msg.type == "ping":
                    with self.lock:
                        if msg.seq in self.pending:
                            send_time = self.pending.pop(msg.seq)
                            rtt = (recv_time - send_time) * 1000  # 转换为 ms
                            self.rtts.append(rtt)
                            self.received += 1
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"接收错误: {e}")
    
    def run(self, num_packets: int, interval: float, payload_size: int):
        """运行测试"""
        print("=" * 60)
        print("🔬 SDR RTT 测量工具")
        print("=" * 60)
        print(f"发送端口: {self.tx_port}")
        print(f"接收端口: {self.rx_port}")
        print(f"发包数量: {num_packets}")
        print(f"发包间隔: {interval * 1000:.0f} ms")
        print(f"包大小: ~{payload_size + 50} bytes")
        print(f"超时时间: {self.timeout} s")
        print("=" * 60)
        print()
        
        # 启动接收线程
        recv_thread = threading.Thread(target=self.recv_loop, daemon=True)
        recv_thread.start()
        
        # 填充数据
        payload = "X" * payload_size
        
        print("📡 开始发送...")
        start_time = time.time()
        
        for seq in range(num_packets):
            msg = PingMessage(
                type="ping",
                seq=seq,
                timestamp=time.time(),
                payload=payload
            )
            
            with self.lock:
                self.pending[seq] = time.time()
            
            data = msg.to_json().encode('utf-8')
            self.tx_sock.sendto(data, ("127.0.0.1", self.tx_port))
            
            # 进度显示
            if (seq + 1) % 10 == 0 or seq == num_packets - 1:
                print(f"  发送: {seq + 1}/{num_packets}, 收到: {self.received}", end='\r')
            
            time.sleep(interval)
        
        # 等待最后的包
        print(f"\n\n⏳ 等待最后的响应 ({self.timeout}s)...")
        time.sleep(self.timeout)
        
        self.running = False
        total_time = time.time() - start_time
        
        # 统计丢失的包
        with self.lock:
            self.lost = len(self.pending)
        
        # 打印结果
        self.print_results(num_packets, total_time)
        
        return self.rtts
    
    def print_results(self, num_packets: int, total_time: float):
        """打印统计结果"""
        print()
        print("=" * 60)
        print("📊 测量结果")
        print("=" * 60)
        
        loss_rate = self.lost / num_packets * 100
        
        print(f"发送: {num_packets} 包")
        print(f"接收: {self.received} 包")
        print(f"丢失: {self.lost} 包 ({loss_rate:.1f}%)")
        print(f"总耗时: {total_time:.2f} s")
        print()
        
        if self.rtts:
            rtt_min = min(self.rtts)
            rtt_max = max(self.rtts)
            rtt_avg = statistics.mean(self.rtts)
            rtt_std = statistics.stdev(self.rtts) if len(self.rtts) > 1 else 0
            rtt_median = statistics.median(self.rtts)
            
            # 计算百分位
            sorted_rtts = sorted(self.rtts)
            p95_idx = int(len(sorted_rtts) * 0.95)
            p99_idx = int(len(sorted_rtts) * 0.99)
            rtt_p95 = sorted_rtts[p95_idx] if p95_idx < len(sorted_rtts) else rtt_max
            rtt_p99 = sorted_rtts[p99_idx] if p99_idx < len(sorted_rtts) else rtt_max
            
            print("RTT 统计 (毫秒):")
            print(f"  最小值: {rtt_min:.2f} ms")
            print(f"  最大值: {rtt_max:.2f} ms")
            print(f"  平均值: {rtt_avg:.2f} ms")
            print(f"  标准差: {rtt_std:.2f} ms")
            print(f"  中位数: {rtt_median:.2f} ms")
            print(f"  P95:    {rtt_p95:.2f} ms")
            print(f"  P99:    {rtt_p99:.2f} ms")
            print()
            
            # 参数建议
            print("=" * 60)
            print("🔧 Raft 参数建议")
            print("=" * 60)
            
            # 心跳间隔 = RTT * 3~5
            suggested_heartbeat = rtt_p95 * 4 / 1000  # 转换为秒
            suggested_heartbeat = max(suggested_heartbeat, 0.1)  # 至少 100ms
            
            # 选举超时 = 心跳 * 10~20 (或 RTT * 30~50)
            suggested_timeout_min = suggested_heartbeat * 10
            suggested_timeout_max = suggested_heartbeat * 20
            
            print(f"基于 P95 RTT ({rtt_p95:.1f} ms) 的建议:")
            print()
            print(f"  heartbeat_interval = {suggested_heartbeat:.2f} s")
            print(f"  T_base = {suggested_timeout_min:.2f} ~ {suggested_timeout_max:.2f} s")
            print()
            print("参数设置原则:")
            print("  • heartbeat_interval > 2~3 × RTT (确保心跳不会超时)")
            print("  • T_base > 10 × heartbeat_interval (避免频繁选举)")
            print("  • 如果网络不稳定，增大 T_base")
            
            # RTT 分布直方图 (ASCII)
            print()
            print("=" * 60)
            print("📈 RTT 分布")
            print("=" * 60)
            self.print_histogram()
        else:
            print("❌ 没有收到任何响应!")
            print()
            print("可能的原因:")
            print("  1. SDR PHY 层未启动")
            print("  2. TX/RX 端口不匹配")
            print("  3. 硬件连接问题")
    
    def print_histogram(self, bins: int = 10):
        """打印 ASCII 直方图"""
        if not self.rtts:
            return
        
        rtt_min = min(self.rtts)
        rtt_max = max(self.rtts)
        bin_width = (rtt_max - rtt_min) / bins if rtt_max > rtt_min else 1
        
        # 统计每个 bin 的数量
        counts = [0] * bins
        for rtt in self.rtts:
            idx = min(int((rtt - rtt_min) / bin_width), bins - 1)
            counts[idx] += 1
        
        max_count = max(counts)
        bar_max_width = 40
        
        for i in range(bins):
            bin_start = rtt_min + i * bin_width
            bin_end = bin_start + bin_width
            count = counts[i]
            bar_width = int(count / max_count * bar_max_width) if max_count > 0 else 0
            bar = "█" * bar_width
            print(f"  {bin_start:6.1f}-{bin_end:6.1f} ms | {bar} ({count})")


def main():
    parser = argparse.ArgumentParser(
        description="SDR RTT 测量工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 基本测试
    python3 experiments/pre_test/rtt_benchmark.py
    
    # 更多包
    python3 experiments/pre_test/rtt_benchmark.py --packets 200
    
    # 更快发送
    python3 experiments/pre_test/rtt_benchmark.py --interval 10
    
    # 大包测试
    python3 experiments/pre_test/rtt_benchmark.py --payload 500
        """
    )
    
    parser.add_argument("--packets", "-n", type=int, default=100,
                        help="发送包数量 (默认: 100)")
    parser.add_argument("--interval", "-i", type=float, default=50,
                        help="发包间隔 (毫秒, 默认: 50)")
    parser.add_argument("--payload", "-s", type=int, default=100,
                        help="负载大小 (字节, 默认: 100)")
    parser.add_argument("--timeout", "-t", type=float, default=2.0,
                        help="接收超时 (秒, 默认: 2.0)")
    parser.add_argument("--tx-port", type=int, default=DEFAULT_TX_PORT,
                        help=f"发送端口 (默认: {DEFAULT_TX_PORT})")
    parser.add_argument("--rx-port", type=int, default=DEFAULT_RX_PORT,
                        help=f"接收端口 (默认: {DEFAULT_RX_PORT})")
    
    args = parser.parse_args()
    
    benchmark = RTTBenchmark(
        tx_port=args.tx_port,
        rx_port=args.rx_port,
        timeout=args.timeout
    )
    
    try:
        benchmark.run(
            num_packets=args.packets,
            interval=args.interval / 1000,  # 转换为秒
            payload_size=args.payload
        )
    except KeyboardInterrupt:
        print("\n🛑 测试中断")


if __name__ == "__main__":
    main()

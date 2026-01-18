#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全自动基准测试脚本 (Full Auto Benchmark)
========================================
无需手动改参数，自动遍历 TX Gain 并绘图

使用方法:
    1. 终端 1 启动 SDR (一次性):
       sudo python3 scripts/core/v2v_hw_phy.py \\
           --serial-num "addr=192.168.1.10" \\
           --tx-gain 0.5 --rx-gain 0.5 \\
           --ctrl-port 9999
    
    2. 终端 2 运行自动测试:
       python3 scripts/app/full_auto_benchmark.py \\
           --rx-gain 0.5 \\
           --tx-range 0.1 0.9 0.1 \\
           --packets 200

特点:
    - 通过 UDP 控制端口动态调整增益，无需重启 PHY
    - 自动遍历 TX Gain 范围
    - 自动生成 CSV 和图表
"""

import socket
import time
import json
import argparse
import csv
import os
from datetime import datetime
import statistics
from typing import List, Dict, Tuple
from dataclasses import dataclass

# ==========================================
# 配置
# ==========================================

CTRL_PORT = 9999      # v2v_hw_phy.py 控制端口
DATA_TX_PORT = 10000  # 数据发送端口
DATA_RX_PORT = 20000  # 数据接收端口


# ==========================================
# 控制器类
# ==========================================

class SDRController:
    """SDR 增益控制器"""
    
    def __init__(self, ctrl_port: int = CTRL_PORT):
        self.ctrl_port = ctrl_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
    
    def _send_cmd(self, cmd: dict) -> dict:
        """发送控制命令并等待响应"""
        try:
            data = json.dumps(cmd).encode('utf-8')
            self.sock.sendto(data, ('127.0.0.1', self.ctrl_port))
            
            resp_data, _ = self.sock.recvfrom(1024)
            return json.loads(resp_data.decode('utf-8'))
        except socket.timeout:
            return {"status": "error", "msg": "timeout"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}
    
    def ping(self) -> bool:
        """检查连接"""
        resp = self._send_cmd({"cmd": "ping"})
        return resp.get("status") == "ok"
    
    def set_tx_gain(self, value: float) -> bool:
        """设置 TX Gain"""
        resp = self._send_cmd({"cmd": "set_tx_gain", "value": value})
        return resp.get("status") == "ok"
    
    def set_rx_gain(self, value: float) -> bool:
        """设置 RX Gain"""
        resp = self._send_cmd({"cmd": "set_rx_gain", "value": value})
        return resp.get("status") == "ok"
    
    def get_gains(self) -> Tuple[float, float]:
        """获取当前增益"""
        resp = self._send_cmd({"cmd": "get_gains"})
        if resp.get("status") == "ok":
            return resp.get("tx_gain", 0), resp.get("rx_gain", 0)
        return 0, 0


# ==========================================
# 数据结构
# ==========================================

@dataclass
class TestResult:
    tx_gain: float
    rx_gain: float
    packets_sent: int
    packets_received: int
    packet_loss_rate: float
    snr_mean: float
    snr_std: float
    snr_min: float
    snr_max: float
    snr_samples: int


# ==========================================
# 测试函数
# ==========================================

def run_single_test(
    tx_port: int,
    rx_port: int,
    tx_gain: float,
    rx_gain: float,
    num_packets: int,
    interval_ms: int,
    timeout_sec: float
) -> TestResult:
    """执行单次测试"""
    
    # 创建 socket
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx_sock.bind(('127.0.0.1', rx_port))
    rx_sock.settimeout(0.1)
    
    # 清空缓冲区
    rx_sock.setblocking(False)
    try:
        while True:
            rx_sock.recv(4096)
    except BlockingIOError:
        pass
    rx_sock.settimeout(0.1)
    
    # 统计变量
    recv_seqs = set()
    snr_samples = []
    
    # 发送
    for seq in range(num_packets):
        packet = {
            "type": "Benchmark",
            "seq": seq,
            "timestamp": time.time(),
            "sender_id": 0,
            "term": 0,
            "phy_state": {"snr": 0, "pos": [0, 0], "vel": [0, 0]}
        }
        data = json.dumps(packet).encode('utf-8')
        tx_sock.sendto(data, ('127.0.0.1', tx_port))
        time.sleep(interval_ms / 1000.0)
    
    # 接收
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            data, _ = rx_sock.recvfrom(4096)
            try:
                msg = json.loads(data.decode('utf-8'))
                if 'seq' in msg:
                    recv_seqs.add(msg['seq'])
                if 'phy_state' in msg:
                    snr = msg['phy_state'].get('snr', 0)
                    if snr > 0:
                        snr_samples.append(snr)
            except:
                pass
        except socket.timeout:
            continue
    
    # 统计
    received = len(recv_seqs)
    loss_rate = (num_packets - received) / num_packets * 100
    
    if snr_samples:
        snr_mean = statistics.mean(snr_samples)
        snr_std = statistics.stdev(snr_samples) if len(snr_samples) > 1 else 0
        snr_min = min(snr_samples)
        snr_max = max(snr_samples)
    else:
        snr_mean = snr_std = snr_min = snr_max = 0
    
    tx_sock.close()
    rx_sock.close()
    
    return TestResult(
        tx_gain=tx_gain,
        rx_gain=rx_gain,
        packets_sent=num_packets,
        packets_received=received,
        packet_loss_rate=loss_rate,
        snr_mean=snr_mean,
        snr_std=snr_std,
        snr_min=snr_min,
        snr_max=snr_max,
        snr_samples=len(snr_samples)
    )


def save_results(results: List[TestResult], output_dir: str) -> str:
    """保存结果到 CSV (存放在 csv 子目录)"""
    csv_dir = os.path.join(output_dir, "csv")
    os.makedirs(csv_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(csv_dir, f"auto_benchmark_{timestamp}.csv")
    
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'tx_gain', 'rx_gain', 'packets_sent', 'packets_received',
            'packet_loss_rate(%)', 'snr_mean(dB)', 'snr_std(dB)',
            'snr_min(dB)', 'snr_max(dB)', 'snr_samples'
        ])
        for r in results:
            writer.writerow([
                f"{r.tx_gain:.2f}", f"{r.rx_gain:.2f}",
                r.packets_sent, r.packets_received,
                f"{r.packet_loss_rate:.2f}",
                f"{r.snr_mean:.2f}", f"{r.snr_std:.2f}",
                f"{r.snr_min:.2f}", f"{r.snr_max:.2f}",
                r.snr_samples
            ])
    
    print(f"💾 CSV 已保存: {csv_path}")
    return timestamp


def plot_results(results: List[TestResult], output_dir: str, timestamp: str):
    """绘制全面的图表 - 使用所有采集的数据"""
    try:
        import matplotlib
        matplotlib.use('TkAgg')  # 使用 TkAgg 后端以支持显示
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("❌ 需要安装 matplotlib: pip3 install matplotlib")
        return
    
    if len(results) < 2:
        print("⚠️ 数据点不足，跳过绘图")
        return
    
    # 提取所有数据
    tx_gains = [r.tx_gain for r in results]
    loss_rates = [r.packet_loss_rate for r in results]
    snr_means = [r.snr_mean for r in results]
    snr_stds = [r.snr_std for r in results]
    snr_mins = [r.snr_min for r in results]
    snr_maxs = [r.snr_max for r in results]
    snr_samples_list = [r.snr_samples for r in results]
    packets_sent_list = [r.packets_sent for r in results]
    packets_recv_list = [r.packets_received for r in results]
    rx_gain = results[0].rx_gain
    
    # 创建 3x2 图表布局 (6个子图)
    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle(f'V2V-SDR Auto Benchmark 全面分析 (RX Gain = {rx_gain})', 
                 fontsize=16, fontweight='bold')
    
    # ======== 图1: TX Gain vs 丢包率 ========
    ax1 = axes[0, 0]
    ax1.plot(tx_gains, loss_rates, 'ro-', linewidth=2, markersize=10)
    ax1.fill_between(tx_gains, loss_rates, alpha=0.3, color='red')
    ax1.set_xlabel('TX Gain', fontsize=12)
    ax1.set_ylabel('Packet Loss Rate (%)', fontsize=12)
    ax1.set_title('TX Gain vs Packet Loss Rate', fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(bottom=0)
    for x, y in zip(tx_gains, loss_rates):
        ax1.annotate(f'{y:.1f}%', (x, y), textcoords="offset points", 
                    xytext=(0, 10), ha='center', fontsize=9)
    
    # ======== 图2: TX Gain vs SNR (含范围) ========
    ax2 = axes[0, 1]
    # 绘制 SNR 范围 (min-max) 作为填充区域
    ax2.fill_between(tx_gains, snr_mins, snr_maxs, alpha=0.3, color='blue', 
                     label='SNR Range (min-max)')
    # 绘制均值和标准差
    ax2.errorbar(tx_gains, snr_means, yerr=snr_stds, fmt='bo-', 
                 linewidth=2, markersize=10, capsize=5, capthick=2, 
                 label='SNR Mean ± Std')
    ax2.set_xlabel('TX Gain', fontsize=12)
    ax2.set_ylabel('SNR (dB)', fontsize=12)
    ax2.set_title('TX Gain vs SNR (with Range)', fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best')
    
    # ======== 图3: SNR vs 丢包率 (关键图 + 趋势线) ========
    ax3 = axes[1, 0]
    scatter = ax3.scatter(snr_means, loss_rates, c=tx_gains, cmap='viridis', 
                          s=200, edgecolors='black', linewidths=2)
    ax3.set_xlabel('SNR (dB)', fontsize=12)
    ax3.set_ylabel('Packet Loss Rate (%)', fontsize=12)
    ax3.set_title('SNR vs Packet Loss Rate (Key Result)', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax3)
    cbar.set_label('TX Gain')
    
    # 添加趋势线
    if len(snr_means) >= 3 and any(s > 0 for s in snr_means):
        valid_idx = [i for i, s in enumerate(snr_means) if s > 0]
        if len(valid_idx) >= 3:
            x_valid = [snr_means[i] for i in valid_idx]
            y_valid = [loss_rates[i] for i in valid_idx]
            try:
                z = np.polyfit(x_valid, y_valid, 2)
                p = np.poly1d(z)
                x_trend = np.linspace(min(x_valid), max(x_valid), 50)
                ax3.plot(x_trend, np.clip(p(x_trend), 0, 100), 'r--', 
                        alpha=0.7, linewidth=2, label=f'Trend: y={z[0]:.2f}x²+{z[1]:.2f}x+{z[2]:.2f}')
                ax3.legend(fontsize=8)
            except:
                pass
    
    # ======== 图4: 收发包统计 (堆叠柱状图) ========
    ax4 = axes[1, 1]
    x_pos = np.arange(len(tx_gains))
    width = 0.6
    packets_lost = [s - r for s, r in zip(packets_sent_list, packets_recv_list)]
    
    bars1 = ax4.bar(x_pos, packets_recv_list, width, label='Received', color='green', alpha=0.8)
    bars2 = ax4.bar(x_pos, packets_lost, width, bottom=packets_recv_list, 
                    label='Lost', color='red', alpha=0.8)
    
    ax4.set_xlabel('TX Gain', fontsize=12)
    ax4.set_ylabel('Packets', fontsize=12)
    ax4.set_title('Packets Sent/Received/Lost per TX Gain', fontsize=12)
    ax4.set_xticks(x_pos)
    ax4.set_xticklabels([f'{g:.2f}' for g in tx_gains], fontsize=9)
    ax4.legend(loc='upper right')
    ax4.grid(True, alpha=0.3, axis='y')
    
    # 在柱子上标注总发送数
    for i, (sent, recv) in enumerate(zip(packets_sent_list, packets_recv_list)):
        ax4.annotate(f'{sent}', (i, sent + 2), ha='center', fontsize=8, color='gray')
    
    # ======== 图5: 数据质量 (SNR 样本数 vs 收到包数) ========
    ax5 = axes[2, 0]
    x_pos = np.arange(len(tx_gains))
    width = 0.35
    
    bars1 = ax5.bar(x_pos - width/2, packets_recv_list, width, label='Packets Received', color='steelblue')
    bars2 = ax5.bar(x_pos + width/2, snr_samples_list, width, label='SNR Samples', color='orange')
    
    ax5.set_xlabel('TX Gain', fontsize=12)
    ax5.set_ylabel('Count', fontsize=12)
    ax5.set_title('Data Quality: Packets vs SNR Samples', fontsize=12)
    ax5.set_xticks(x_pos)
    ax5.set_xticklabels([f'{g:.2f}' for g in tx_gains], fontsize=9)
    ax5.legend(loc='best')
    ax5.grid(True, alpha=0.3, axis='y')
    
    # 标注匹配率
    for i, (recv, snr_n) in enumerate(zip(packets_recv_list, snr_samples_list)):
        if recv > 0:
            ratio = snr_n / recv * 100
            ax5.annotate(f'{ratio:.0f}%', (i, max(recv, snr_n) + 2), 
                        ha='center', fontsize=8, color='gray')
    
    # ======== 图6: 综合双轴视图 ========
    ax6 = axes[2, 1]
    ax6_twin = ax6.twinx()
    
    line1, = ax6.plot(tx_gains, snr_means, 'b-o', linewidth=2, 
                      markersize=10, label='SNR Mean (dB)')
    ax6.fill_between(tx_gains, np.array(snr_means) - np.array(snr_stds),
                     np.array(snr_means) + np.array(snr_stds), 
                     alpha=0.2, color='blue')
    
    line2, = ax6_twin.plot(tx_gains, loss_rates, 'r-s', linewidth=2, 
                           markersize=10, label='Loss Rate (%)')
    
    ax6.set_xlabel('TX Gain', fontsize=12)
    ax6.set_ylabel('SNR (dB)', fontsize=12, color='blue')
    ax6_twin.set_ylabel('Packet Loss Rate (%)', fontsize=12, color='red')
    ax6.set_title('Combined View: SNR & Loss Rate', fontsize=12)
    ax6.grid(True, alpha=0.3)
    ax6.tick_params(axis='y', labelcolor='blue')
    ax6_twin.tick_params(axis='y', labelcolor='red')
    ax6_twin.set_ylim(bottom=0)
    
    lines = [line1, line2]
    ax6.legend(lines, [l.get_label() for l in lines], loc='center right')
    
    plt.tight_layout()
    
    # 保存到 plots 子目录
    plots_dir = os.path.join(output_dir, "plots")
    os.makedirs(plots_dir, exist_ok=True)
    fig_path = os.path.join(plots_dir, f"auto_benchmark_{timestamp}.png")
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    print(f"📊 图表已保存: {fig_path}")
    
    # 打印数据摘要
    print("\n" + "="*70)
    print("📋 数据摘要")
    print("="*70)
    print(f"{'TX Gain':<10}{'Sent':<8}{'Recv':<8}{'Lost':<8}{'Loss%':<10}"
          f"{'SNR Mean':<12}{'SNR Std':<10}{'SNR Min':<10}{'SNR Max':<10}{'Samples':<8}")
    print("-"*70)
    for r in results:
        lost = r.packets_sent - r.packets_received
        print(f"{r.tx_gain:<10.2f}{r.packets_sent:<8}{r.packets_received:<8}{lost:<8}"
              f"{r.packet_loss_rate:<10.2f}{r.snr_mean:<12.2f}{r.snr_std:<10.2f}"
              f"{r.snr_min:<10.2f}{r.snr_max:<10.2f}{r.snr_samples:<8}")
    print("="*70)
    
    # 显示
    print("📊 显示图表 (关闭窗口继续)...")
    plt.show()


# ==========================================
# 主程序
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="V2V-SDR 全自动基准测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 扫描 TX Gain 0.1 到 0.9
  python3 scripts/app/full_auto_benchmark.py \\
      --rx-gain 0.5 \\
      --tx-range 0.1 0.9 0.1 \\
      --packets 200

注意: 先启动 v2v_hw_phy.py 并确保 --ctrl-port 9999
        """
    )
    
    parser.add_argument("--rx-gain", type=float, required=True,
                        help="固定的 RX Gain")
    parser.add_argument("--tx-range", nargs=3, type=float, required=True,
                        metavar=('START', 'END', 'STEP'),
                        help="TX Gain 范围: 起始 结束 步长")
    parser.add_argument("--packets", type=int, default=100,
                        help="每次测试发包数 (默认: 100)")
    parser.add_argument("--interval", type=int, default=50,
                        help="发包间隔 ms (默认: 50)")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="接收超时秒 (默认: 3.0)")
    parser.add_argument("--ctrl-port", type=int, default=9999,
                        help="控制端口 (默认: 9999)")
    parser.add_argument("--data-tx", type=int, default=10000,
                        help="数据发送端口 (默认: 10000)")
    parser.add_argument("--data-rx", type=int, default=20000,
                        help="数据接收端口 (默认: 20000)")
    parser.add_argument("--output", type=str, default="results",
                        help="输出目录 (默认: results)")
    parser.add_argument("--settle-time", type=float, default=1.0,
                        help="增益切换后等待时间 (默认: 1.0)")
    
    args = parser.parse_args()
    
    # 生成 TX Gain 列表
    start, end, step = args.tx_range
    
    # 根据步长自动计算所需的小数位数
    step_str = f"{step:.10f}".rstrip('0')
    if '.' in step_str:
        decimals = len(step_str.split('.')[1])
    else:
        decimals = 2
    decimals = max(decimals, 2)  # 至少 2 位
    
    tx_gains = []
    g = start
    while g <= end + step * 0.1:  # 小余量避免浮点误差
        tx_gains.append(round(g, decimals))
        g += step
    
    print("=" * 60)
    print("🔬 V2V-SDR 全自动基准测试")
    print("=" * 60)
    print(f"RX Gain (固定): {args.rx_gain}")
    print(f"TX Gain 扫描: {tx_gains}")
    print(f"每次发包数: {args.packets}")
    print(f"发包间隔: {args.interval}ms")
    print("=" * 60)
    
    # 创建控制器
    controller = SDRController(args.ctrl_port)
    
    # 检查连接
    print("\n🔗 检查 SDR 连接...")
    if not controller.ping():
        print("❌ 无法连接到 v2v_hw_phy.py")
        print("   请确保已启动: sudo python3 scripts/core/v2v_hw_phy.py --ctrl-port 9999")
        return
    print("✅ SDR 连接正常")
    
    # 设置 RX Gain
    print(f"🔧 设置 RX Gain = {args.rx_gain}")
    if not controller.set_rx_gain(args.rx_gain):
        print("⚠️ 设置 RX Gain 失败，继续测试...")
    
    # 执行测试
    results = []
    total = len(tx_gains)
    
    for i, tx_gain in enumerate(tx_gains):
        print(f"\n{'#' * 60}")
        print(f"# 测试 {i+1}/{total}: TX Gain = {tx_gain}")
        print(f"{'#' * 60}")
        
        # 设置 TX Gain
        print(f"🔧 设置 TX Gain = {tx_gain}")
        if not controller.set_tx_gain(tx_gain):
            print("❌ 设置失败，跳过此测试")
            continue
        
        # 等待增益稳定
        print(f"⏳ 等待 {args.settle_time}s 让增益稳定...")
        time.sleep(args.settle_time)
        
        # 执行测试
        print(f"📊 开始测试: 发送 {args.packets} 包...")
        result = run_single_test(
            tx_port=args.data_tx,
            rx_port=args.data_rx,
            tx_gain=tx_gain,
            rx_gain=args.rx_gain,
            num_packets=args.packets,
            interval_ms=args.interval,
            timeout_sec=args.timeout
        )
        
        # 打印结果
        print(f"\n📈 结果:")
        print(f"   收包: {result.packets_received}/{result.packets_sent} ({100-result.packet_loss_rate:.1f}%)")
        print(f"   丢包率: {result.packet_loss_rate:.1f}%")
        print(f"   SNR: {result.snr_mean:.2f} ± {result.snr_std:.2f} dB")
        
        results.append(result)
    
    # 保存和绘图
    if results:
        print(f"\n{'=' * 60}")
        print("📊 测试完成，生成报告...")
        print(f"{'=' * 60}")
        
        timestamp = save_results(results, args.output)
        plot_results(results, args.output, timestamp)
        
        # 打印总结
        print(f"\n📋 测试总结:")
        print(f"   总测试数: {len(results)}")
        print(f"   TX Gain 范围: {min(r.tx_gain for r in results)} - {max(r.tx_gain for r in results)}")
        print(f"   丢包率范围: {min(r.packet_loss_rate for r in results):.1f}% - {max(r.packet_loss_rate for r in results):.1f}%")
        valid_snr = [r.snr_mean for r in results if r.snr_mean > 0]
        if valid_snr:
            print(f"   SNR 范围: {min(valid_snr):.1f} - {max(valid_snr):.1f} dB")
    else:
        print("❌ 没有有效测试结果")
    
    print("\n✅ 全部完成!")


if __name__ == "__main__":
    main()

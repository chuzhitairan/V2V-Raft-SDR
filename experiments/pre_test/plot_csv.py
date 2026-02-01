"""
从 CSV 文件绘制 Benchmark 图表

用法:
    python3 experiments/pre_test/plot_csv.py results/benchmark_results.csv
    python3 experiments/pre_test/plot_csv.py results/benchmark_results.csv --output results/my_plot.png
"""

import argparse
import csv
import sys
import os
from dataclasses import dataclass
from typing import List

@dataclass
class DataPoint:
    label: str
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


def parse_label(label: str) -> tuple:
    """从 label 解析 tx_gain 和 rx_gain"""
    # 格式: tx0.5_rx0.5
    try:
        parts = label.split('_')
        tx = float(parts[0].replace('tx', ''))
        rx = float(parts[1].replace('rx', ''))
        return tx, rx
    except:
        return 0.0, 0.0


def get_float(row: dict, *keys) -> float:
    """尝试多个键名获取 float 值"""
    for key in keys:
        if key in row and row[key]:
            try:
                return float(row[key])
            except:
                pass
    return 0.0


def get_int(row: dict, *keys) -> int:
    """尝试多个键名获取 int 值"""
    for key in keys:
        if key in row and row[key]:
            try:
                return int(row[key])
            except:
                pass
    return 0


def load_csv(csv_path: str) -> List[DataPoint]:
    """加载 CSV 文件 - 支持多种格式"""
    data = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        print(f"📋 CSV 列名: {headers}")
        
        # 检测格式类型
        is_auto_format = 'tx_gain' in headers  # auto_benchmark 格式
        
        for row in reader:
            if is_auto_format:
                # auto_benchmark 格式: tx_gain, rx_gain, packet_loss_rate(%), snr_mean(dB), ...
                tx_gain = get_float(row, 'tx_gain')
                rx_gain = get_float(row, 'rx_gain')
                label = f"tx{tx_gain:.2f}_rx{rx_gain:.2f}"
            else:
                # manual_benchmark 格式: label, packet_loss_rate, snr_mean, ...
                label = row.get('label', '')
                tx_gain, rx_gain = parse_label(label)
            
            data.append(DataPoint(
                label=label,
                tx_gain=tx_gain,
                rx_gain=rx_gain,
                packets_sent=get_int(row, 'packets_sent'),
                packets_received=get_int(row, 'packets_received'),
                packet_loss_rate=get_float(row, 'packet_loss_rate(%)', 'packet_loss_rate'),
                snr_mean=get_float(row, 'snr_mean(dB)', 'snr_mean'),
                snr_std=get_float(row, 'snr_std(dB)', 'snr_std'),
                snr_min=get_float(row, 'snr_min(dB)', 'snr_min'),
                snr_max=get_float(row, 'snr_max(dB)', 'snr_max'),
                snr_samples=get_int(row, 'snr_samples', 'snr_samples_count')
            ))
    
    return data


def plot_data(data: List[DataPoint], output_path: str = None, show: bool = True):
    """绘制全面的图表"""
    try:
        import matplotlib
        matplotlib.use('TkAgg')
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("❌ 需要安装 matplotlib: sudo apt install python3-matplotlib")
        sys.exit(1)
    
    if len(data) < 1:
        print("❌ CSV 文件为空")
        return
    
    # 按 TX Gain 排序
    data = sorted(data, key=lambda x: x.tx_gain)
    
    # 提取数据
    labels = [d.label for d in data]
    tx_gains = [d.tx_gain for d in data]
    loss_rates = [d.packet_loss_rate for d in data]
    snr_means = [d.snr_mean for d in data]
    snr_stds = [d.snr_std for d in data]
    snr_mins = [d.snr_min for d in data]
    snr_maxs = [d.snr_max for d in data]
    snr_samples_list = [d.snr_samples for d in data]
    packets_sent_list = [d.packets_sent for d in data]
    packets_recv_list = [d.packets_received for d in data]
    rx_gain = data[0].rx_gain
    
    # 创建 3x2 图表
    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle(f'V2V-SDR Benchmark 分析 (RX Gain = {rx_gain})', 
                 fontsize=16, fontweight='bold')
    
    # ======== 图1: TX Gain vs 丢包率 ========
    ax1 = axes[0, 0]
    ax1.plot(tx_gains, loss_rates, 'ro-', linewidth=2, markersize=10)
    ax1.fill_between(tx_gains, loss_rates, alpha=0.3, color='red')
    ax1.set_xlabel('TX Gain', fontsize=12)
    ax1.set_ylabel('Packet Loss Rate (%)', fontsize=12)
    ax1.set_title('TX Gain vs Packet Loss Rate', fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 105)
    for x, y in zip(tx_gains, loss_rates):
        ax1.annotate(f'{y:.1f}%', (x, y), textcoords="offset points", 
                    xytext=(0, 10), ha='center', fontsize=9)
    
    # ======== 图2: TX Gain vs SNR (含范围) ========
    ax2 = axes[0, 1]
    ax2.fill_between(tx_gains, snr_mins, snr_maxs, alpha=0.3, color='blue', 
                     label='SNR Range (min-max)')
    ax2.errorbar(tx_gains, snr_means, yerr=snr_stds, fmt='bo-', 
                 linewidth=2, markersize=10, capsize=5, capthick=2, 
                 label='SNR Mean ± Std')
    ax2.set_xlabel('TX Gain', fontsize=12)
    ax2.set_ylabel('SNR (dB)', fontsize=12)
    ax2.set_title('TX Gain vs SNR (with Range)', fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best')
    
    # ======== 图3: SNR vs 丢包率 ========
    ax3 = axes[1, 0]
    # 过滤掉 SNR=0 的点（无效数据）
    valid_data = [(s, l, t) for s, l, t in zip(snr_means, loss_rates, tx_gains) if s > 0]
    
    if valid_data:
        valid_snr = [v[0] for v in valid_data]
        valid_loss = [v[1] for v in valid_data]
        valid_tx = [v[2] for v in valid_data]
        
        scatter = ax3.scatter(valid_snr, valid_loss, c=valid_tx, cmap='viridis', 
                              s=200, edgecolors='black', linewidths=2)
        cbar = plt.colorbar(scatter, ax=ax3)
        cbar.set_label('TX Gain')
        
        # 趋势线
        if len(valid_snr) >= 3:
            try:
                z = np.polyfit(valid_snr, valid_loss, 2)
                p = np.poly1d(z)
                x_trend = np.linspace(min(valid_snr), max(valid_snr), 50)
                ax3.plot(x_trend, np.clip(p(x_trend), 0, 100), 'r--', 
                        alpha=0.7, linewidth=2, 
                        label=f'Trend: y={z[0]:.2f}x²+{z[1]:.2f}x+{z[2]:.2f}')
                ax3.legend(fontsize=8)
            except:
                pass
    else:
        ax3.text(0.5, 0.5, 'No valid SNR data\n(all SNR=0)', 
                ha='center', va='center', transform=ax3.transAxes,
                fontsize=14, color='gray')
    
    ax3.set_xlabel('SNR (dB)', fontsize=12)
    ax3.set_ylabel('Packet Loss Rate (%)', fontsize=12)
    ax3.set_title('SNR vs Packet Loss Rate (Key Result)', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    
    # ======== 图4: 收发包统计 ========
    ax4 = axes[1, 1]
    x_pos = np.arange(len(tx_gains))
    width = 0.6
    packets_lost = [s - r for s, r in zip(packets_sent_list, packets_recv_list)]
    
    bars1 = ax4.bar(x_pos, packets_recv_list, width, label='Received', color='green', alpha=0.8)
    bars2 = ax4.bar(x_pos, packets_lost, width, bottom=packets_recv_list, 
                    label='Lost', color='red', alpha=0.8)
    
    ax4.set_xlabel('TX Gain', fontsize=12)
    ax4.set_ylabel('Packets', fontsize=12)
    ax4.set_title('Packets Sent/Received/Lost', fontsize=12)
    ax4.set_xticks(x_pos)
    ax4.set_xticklabels([f'{g:.2f}' for g in tx_gains], fontsize=9)
    ax4.legend(loc='upper right')
    ax4.grid(True, alpha=0.3, axis='y')
    
    for i, (sent, recv) in enumerate(zip(packets_sent_list, packets_recv_list)):
        ax4.annotate(f'{sent}', (i, sent + 5), ha='center', fontsize=8, color='gray')
    
    # ======== 图5: 数据质量 ========
    ax5 = axes[2, 0]
    x_pos = np.arange(len(tx_gains))
    width = 0.35
    
    bars1 = ax5.bar(x_pos - width/2, packets_recv_list, width, 
                    label='Packets Received', color='steelblue')
    bars2 = ax5.bar(x_pos + width/2, snr_samples_list, width, 
                    label='SNR Samples', color='orange')
    
    ax5.set_xlabel('TX Gain', fontsize=12)
    ax5.set_ylabel('Count', fontsize=12)
    ax5.set_title('Data Quality: Packets vs SNR Samples', fontsize=12)
    ax5.set_xticks(x_pos)
    ax5.set_xticklabels([f'{g:.2f}' for g in tx_gains], fontsize=9)
    ax5.legend(loc='best')
    ax5.grid(True, alpha=0.3, axis='y')
    
    for i, (recv, snr_n) in enumerate(zip(packets_recv_list, snr_samples_list)):
        if recv > 0:
            ratio = snr_n / recv * 100
            ax5.annotate(f'{ratio:.0f}%', (i, max(recv, snr_n) + 5), 
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
    ax6_twin.set_ylim(0, 105)
    
    lines = [line1, line2]
    ax6.legend(lines, [l.get_label() for l in lines], loc='center right')
    
    plt.tight_layout()
    
    # 打印数据摘要
    print("\n" + "="*80)
    print("📋 数据摘要")
    print("="*80)
    print(f"{'Label':<16}{'Sent':<8}{'Recv':<8}{'Lost':<8}{'Loss%':<10}"
          f"{'SNR Mean':<12}{'SNR Std':<10}{'Samples':<8}")
    print("-"*80)
    for d in data:
        lost = d.packets_sent - d.packets_received
        print(f"{d.label:<16}{d.packets_sent:<8}{d.packets_received:<8}{lost:<8}"
              f"{d.packet_loss_rate:<10.1f}{d.snr_mean:<12.2f}{d.snr_std:<10.2f}"
              f"{d.snr_samples:<8}")
    print("="*80)
    
    # 保存
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"\n📊 图表已保存: {output_path}")
    else:
        # 默认保存到 CSV 同目录
        default_path = csv_path.replace('.csv', '_plot.png')
        plt.savefig(default_path, dpi=150, bbox_inches='tight')
        print(f"\n📊 图表已保存: {default_path}")
    
    # 显示
    if show:
        print("📊 显示图表 (关闭窗口退出)...")
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="从 CSV 文件绘制 Benchmark 图表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python3 experiments/pre_test/plot_csv.py results/benchmark_results.csv
    python3 experiments/pre_test/plot_csv.py results/benchmark_results.csv --output results/my_plot.png
    python3 experiments/pre_test/plot_csv.py results/benchmark_results.csv --no-show
        """
    )
    
    parser.add_argument("csv_file", help="CSV 文件路径")
    parser.add_argument("--output", "-o", help="输出图片路径 (默认: CSV同名_plot.png)")
    parser.add_argument("--no-show", action="store_true", help="不显示图表窗口")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.csv_file):
        print(f"❌ 文件不存在: {args.csv_file}")
        sys.exit(1)
    
    print(f"📂 加载 CSV: {args.csv_file}")
    data = load_csv(args.csv_file)
    print(f"📊 数据点: {len(data)}")
    
    global csv_path
    csv_path = args.csv_file
    
    plot_data(data, args.output, show=not args.no_show)


if __name__ == "__main__":
    main()

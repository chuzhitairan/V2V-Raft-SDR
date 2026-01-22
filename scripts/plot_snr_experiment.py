#!/usr/bin/env python3
"""
SNR-集群规模实验结果绘图工具
============================

读取实验结果 JSON 文件，绘制：
1. SNR vs 集群规模
2. SNR vs 丢包率
3. 各节点丢包率对比

使用方法:
    python3 plot_snr_experiment.py <result_file.json>
    python3 plot_snr_experiment.py  # 自动查找最新结果文件

作者: V2V-Raft-SDR 项目
"""

import json
import sys
import os
import glob
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# 设置字体
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False


def find_latest_result_file():
    """查找最新的结果文件"""
    pattern = "snr_experiment_results_*.json"
    files = glob.glob(pattern)
    if not files:
        # 也在 scripts 目录下查找
        files = glob.glob(os.path.join("scripts", pattern))
    if not files:
        return None
    return max(files, key=os.path.getctime)


def load_results(filepath):
    """加载结果文件"""
    with open(filepath, 'r') as f:
        return json.load(f)


def plot_results(data, output_prefix=None):
    """绘制实验结果图表"""
    results = data['results']
    
    # 提取数据
    snr_values = [r['target_snr'] for r in results]
    cluster_sizes = [r['average_cluster_size'] for r in results]
    cluster_stds = [r.get('std_cluster_size', r.get('std_dev', 0)) for r in results]
    
    # 丢包率数据（如果有）
    has_packet_loss = 'average_packet_loss' in results[0]
    if has_packet_loss:
        packet_losses = [r['average_packet_loss'] * 100 for r in results]  # 转为百分比
        packet_loss_per_node = [r.get('packet_loss_per_node', {}) for r in results]
    
    # 实际 SNR 数据（如果有）
    has_actual_snr = 'avg_actual_snr' in results[0]
    if has_actual_snr:
        actual_snr_values = [r.get('avg_actual_snr', 0) for r in results]
        actual_snr_stds = [r.get('std_actual_snr', 0) for r in results]
        actual_snr_per_node = [r.get('actual_snr_per_node', {}) for r in results]
    
    # 创建图表 (3x2 布局，增加实际SNR相关图表)
    if has_packet_loss and has_actual_snr:
        fig, axes = plt.subplots(3, 2, figsize=(14, 15))
        ax1, ax2 = axes[0, 0], axes[0, 1]
        ax3, ax4 = axes[1, 0], axes[1, 1]
        ax5, ax6 = axes[2, 0], axes[2, 1]
        fig.suptitle(f'SNR-Cluster Size Experiment Results\nTotal Nodes: {data["total_nodes"]}, '
                     f'Start SNR: {data["start_snr"]}dB, Step: {data["snr_step"]}dB', 
                     fontsize=14, fontweight='bold')
    elif has_packet_loss:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        ax1, ax2, ax3, ax4 = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]
        ax5, ax6 = None, None
        fig.suptitle(f'SNR-Cluster Size Experiment Results\nTotal Nodes: {data["total_nodes"]}, '
                     f'Start SNR: {data["start_snr"]}dB, Step: {data["snr_step"]}dB', 
                     fontsize=14, fontweight='bold')
    else:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        ax1, ax2 = axes[0], axes[1]
        ax3, ax4, ax5, ax6 = None, None, None, None
        fig.suptitle(f'SNR-Cluster Size Experiment Results\nTotal Nodes: {data["total_nodes"]}, '
                     f'Start SNR: {data["start_snr"]}dB, Step: {data["snr_step"]}dB', 
                     fontsize=14, fontweight='bold')
    
    # 图1: SNR vs 集群规模 (带误差线)
    ax1.errorbar(snr_values, cluster_sizes, yerr=cluster_stds, 
                 fmt='o-', capsize=5, capthick=2, linewidth=2, markersize=8,
                 color='#2196F3', ecolor='#90CAF9', label='Avg Cluster Size')
    ax1.fill_between(snr_values, 
                     np.array(cluster_sizes) - np.array(cluster_stds),
                     np.array(cluster_sizes) + np.array(cluster_stds),
                     alpha=0.2, color='#2196F3')
    ax1.set_xlabel('Target SNR (dB)', fontsize=12)
    ax1.set_ylabel('Cluster Size (nodes)', fontsize=12)
    ax1.set_title('SNR vs Cluster Size', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    ax1.set_ylim(bottom=0)
    
    # 在点上标注数值
    for x, y in zip(snr_values, cluster_sizes):
        ax1.annotate(f'{y:.1f}', (x, y), textcoords="offset points", 
                     xytext=(0, 10), ha='center', fontsize=9)
    
    # 图2: 集群规模的原始测量分布 (箱线图)
    raw_measurements = [r.get('raw_cluster_measurements', r.get('raw_measurements', [])) 
                        for r in results]
    if raw_measurements and raw_measurements[0]:
        bp = ax2.boxplot(raw_measurements, labels=[f'{s:.0f}' for s in snr_values],
                         patch_artist=True)
        for patch in bp['boxes']:
            patch.set_facecolor('#E3F2FD')
            patch.set_edgecolor('#2196F3')
        ax2.set_xlabel('Target SNR (dB)', fontsize=12)
        ax2.set_ylabel('Cluster Size (nodes)', fontsize=12)
        ax2.set_title('Cluster Size Distribution (Boxplot)', fontsize=12, fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
    
    if has_packet_loss:
        # 图3: SNR vs 丢包率
        ax3.plot(snr_values, packet_losses, 'o-', linewidth=2, markersize=8,
                 color='#F44336', label='Avg Packet Loss')
        ax3.fill_between(snr_values, 0, packet_losses, alpha=0.2, color='#F44336')
        ax3.set_xlabel('Target SNR (dB)', fontsize=12)
        ax3.set_ylabel('Packet Loss Rate (%)', fontsize=12)
        ax3.set_title('SNR vs Packet Loss Rate', fontsize=12, fontweight='bold')
        ax3.grid(True, alpha=0.3)
        ax3.legend()
        ax3.set_ylim(bottom=0)
        
        # 在点上标注数值
        for x, y in zip(snr_values, packet_losses):
            ax3.annotate(f'{y:.1f}%', (x, y), textcoords="offset points", 
                         xytext=(0, 10), ha='center', fontsize=9)
        
        # 图4: 各节点丢包率对比
        # 收集所有节点ID
        all_nodes = set()
        for plr in packet_loss_per_node:
            all_nodes.update(plr.keys())
        all_nodes = sorted(all_nodes, key=lambda x: int(x) if str(x).isdigit() else 0)
        
        if all_nodes:
            # 为每个节点绘制一条线
            colors = plt.cm.tab10(np.linspace(0, 1, len(all_nodes)))
            for i, node_id in enumerate(all_nodes):
                node_losses = []
                for plr in packet_loss_per_node:
                    loss = plr.get(str(node_id), plr.get(node_id, 0))
                    node_losses.append(loss * 100)
                ax4.plot(snr_values, node_losses, 'o-', linewidth=2, markersize=6,
                         color=colors[i], label=f'Node {node_id}')
            
            ax4.set_xlabel('Target SNR (dB)', fontsize=12)
            ax4.set_ylabel('Packet Loss Rate (%)', fontsize=12)
            ax4.set_title('Packet Loss per Node', fontsize=12, fontweight='bold')
            ax4.grid(True, alpha=0.3)
            ax4.legend()
            ax4.set_ylim(bottom=0)
    
    # 图5 & 图6: 实际 SNR 相关图表
    if has_actual_snr and ax5 is not None:
        # 图5: 目标 SNR vs 实际 SNR (对比图)
        # 绘制理想线 (y=x)
        min_snr = min(snr_values)
        max_snr = max(snr_values)
        ax5.plot([min_snr, max_snr], [min_snr, max_snr], 'k--', linewidth=1.5, 
                 alpha=0.5, label='Ideal (Actual=Target)')
        
        # 绘制实际值（带误差线）
        ax5.errorbar(snr_values, actual_snr_values, yerr=actual_snr_stds,
                     fmt='o-', capsize=5, capthick=2, linewidth=2, markersize=8,
                     color='#4CAF50', ecolor='#A5D6A7', label='Actual SNR (avg)')
        
        ax5.set_xlabel('Target SNR (dB)', fontsize=12)
        ax5.set_ylabel('Actual SNR (dB)', fontsize=12)
        ax5.set_title('Target SNR vs Actual SNR', fontsize=12, fontweight='bold')
        ax5.grid(True, alpha=0.3)
        ax5.legend()
        
        # 在点上标注差值
        for x, y in zip(snr_values, actual_snr_values):
            diff = y - x
            color = '#4CAF50' if abs(diff) <= 3 else '#F44336'
            ax5.annotate(f'{diff:+.1f}', (x, y), textcoords="offset points", 
                         xytext=(5, 5), ha='left', fontsize=9, color=color)
        
        # 图6: 各节点实际 SNR 对比
        all_nodes = set()
        for asnr in actual_snr_per_node:
            all_nodes.update(asnr.keys())
        all_nodes = sorted(all_nodes, key=lambda x: int(x) if str(x).isdigit() else 0)
        
        if all_nodes:
            # 绘制理想线
            ax6.plot([min_snr, max_snr], [min_snr, max_snr], 'k--', linewidth=1.5, 
                     alpha=0.5, label='Ideal')
            
            # 为每个节点绘制一条线
            colors = plt.cm.tab10(np.linspace(0, 1, len(all_nodes)))
            for i, node_id in enumerate(all_nodes):
                node_snrs = []
                for asnr in actual_snr_per_node:
                    snr = asnr.get(str(node_id), asnr.get(node_id, 0))
                    node_snrs.append(snr)
                ax6.plot(snr_values, node_snrs, 'o-', linewidth=2, markersize=6,
                         color=colors[i], label=f'Node {node_id}')
            
            ax6.set_xlabel('Target SNR (dB)', fontsize=12)
            ax6.set_ylabel('Actual SNR (dB)', fontsize=12)
            ax6.set_title('Actual SNR per Node', fontsize=12, fontweight='bold')
            ax6.grid(True, alpha=0.3)
            ax6.legend()
    
    plt.tight_layout()
    
    # 保存图表
    if output_prefix is None:
        output_prefix = 'snr_experiment_plot'
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f'{output_prefix}_{timestamp}.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"[Saved] Plot saved to: {output_file}")
    
    # 显示图表
    plt.show()
    
    return output_file


def print_summary(data):
    """Print experiment summary"""
    results = data['results']
    
    print("\n" + "=" * 75)
    print("Experiment Results Summary")
    print("=" * 75)
    print(f"Total nodes: {data['total_nodes']}")
    print(f"Start SNR: {data['start_snr']} dB")
    print(f"SNR step: {data['snr_step']} dB")
    print(f"Measurements per SNR: {data['measurements_per_snr']}")
    print("-" * 75)
    
    has_packet_loss = 'average_packet_loss' in results[0]
    has_actual_snr = 'avg_actual_snr' in results[0]
    
    if has_packet_loss and has_actual_snr:
        print(f"{'Target':<10} {'Actual SNR':<15} {'Cluster Size':<15} {'Packet Loss':<12}")
        print("-" * 55)
        for r in results:
            target = r['target_snr']
            actual = r.get('avg_actual_snr', 0)
            actual_std = r.get('std_actual_snr', 0)
            size = r['average_cluster_size']
            std = r.get('std_cluster_size', r.get('std_dev', 0))
            loss = r['average_packet_loss'] * 100
            diff = actual - target
            diff_str = f"({diff:+.1f})" if has_actual_snr else ""
            print(f"{target:<10.1f} {actual:.1f} ± {actual_std:.1f} {diff_str:<6} {size:.2f} ± {std:.2f}      {loss:.1f}%")
    elif has_packet_loss:
        print(f"{'SNR(dB)':<10} {'Cluster Size':<15} {'Packet Loss':<10}")
        print("-" * 35)
        for r in results:
            snr = r['target_snr']
            size = r['average_cluster_size']
            std = r.get('std_cluster_size', r.get('std_dev', 0))
            loss = r['average_packet_loss'] * 100
            print(f"{snr:<10.1f} {size:.2f} ± {std:.2f}      {loss:.1f}%")
    else:
        print(f"{'SNR(dB)':<10} {'Cluster Size':<15}")
        print("-" * 25)
        for r in results:
            snr = r['target_snr']
            size = r['average_cluster_size']
            std = r.get('std_cluster_size', r.get('std_dev', 0))
            print(f"{snr:<10.1f} {size:.2f} ± {std:.2f}")
    
    print("=" * 75)
    
    # Find key points
    for i, r in enumerate(results):
        if r['average_cluster_size'] < data['total_nodes'] * 0.9:
            print(f"[!] Cluster size starts dropping at SNR = {r['target_snr']} dB")
            break
    
    for i, r in enumerate(results):
        if r['average_cluster_size'] <= 1.5:
            print(f"[X] Cluster near collapse at SNR = {r['target_snr']} dB (size ~ {r['average_cluster_size']:.1f})")
            break
    
    # Print actual SNR accuracy summary
    if has_actual_snr:
        print("\n[SNR Accuracy Summary]")
        total_diff = 0
        for r in results:
            diff = abs(r.get('avg_actual_snr', 0) - r['target_snr'])
            total_diff += diff
        avg_diff = total_diff / len(results) if results else 0
        print(f"  Average |Target - Actual|: {avg_diff:.2f} dB")


def main():
    # Get result file
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = find_latest_result_file()
        if filepath is None:
            print("[Error] No result file found!")
            print("Usage: python3 plot_snr_experiment.py <result_file.json>")
            sys.exit(1)
        print(f"[Info] Using latest result file: {filepath}")
    
    if not os.path.exists(filepath):
        print(f"[Error] File not found: {filepath}")
        sys.exit(1)
    
    # Load data
    data = load_results(filepath)
    
    # Print summary
    print_summary(data)
    
    # Plot results
    plot_results(data)


if __name__ == "__main__":
    main()

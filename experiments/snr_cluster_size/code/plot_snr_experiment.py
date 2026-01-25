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
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
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
    # 1. 过滤数据: 仅保留 target_snr <= 18 的数据
    results = [r for r in data['results'] if r['target_snr'] <= 18.001]
    
    # 按 Target SNR 升序排序 (方便绘图)
    results.sort(key=lambda x: x['target_snr'])
    
    if not results:
        print("❌ 没有 target_snr <= 18 的数据，无法绘图。")
        return

    # 提取数据
    snr_values = [r['target_snr'] for r in results]
    cluster_sizes = [r['average_cluster_size'] for r in results]
    cluster_stds = [r.get('std_cluster_size', r.get('std_dev', 0)) for r in results]
    
    # 丢包率数据
    has_packet_loss = 'average_packet_loss' in results[0]
    if has_packet_loss:
        packet_losses = [r['average_packet_loss'] * 100 for r in results]  # 转为百分比
        packet_loss_per_node = [r.get('packet_loss_per_node', {}) for r in results]
    
    # 实际 SNR 数据
    has_actual_snr = 'avg_actual_snr' in results[0]
    if has_actual_snr:
        actual_snr_values = [r.get('avg_actual_snr', 0) for r in results]
        actual_snr_stds = [r.get('std_actual_snr', 0) for r in results]
        actual_snr_per_node = [r.get('actual_snr_per_node', {}) for r in results]

    # 设置图表保存前缀
    if output_prefix is None:
        output_prefix = 'snr_experiment_plot'
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 通用 X 轴标签 (去除 Target)
    x_label = 'Leader Received SNR (dB)'
    
    def save_current_fig(suffix):
        filename = f'{output_prefix}_{suffix}_{timestamp}.png'
        # 优化边距
        plt.tight_layout() 
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[Saved] {filename}")
        return filename

    # ==========================================
    # 图1: Cluster Size vs SNR (Combined: Avg + Raw Discrete)
    # ==========================================
    plt.figure(figsize=(10, 7))
    
    # 准备原始数据
    raw_measurements = [r.get('raw_cluster_measurements', r.get('raw_measurements', [])) 
                        for r in results]
    
    # 学术蓝颜色定义
    academic_blue = '#1f77b4'
    
    # 1. 绘制散点 (Raw Discrete Points) with Jitter
    # 让离散点在背景中显示，稍微抖动 X 轴
    if raw_measurements and raw_measurements[0]:
        scatter_x = []
        scatter_y = []
        for snr, measurements in zip(snr_values, raw_measurements):
            for m in measurements:
                # 添加随机抖动到 X 轴 (SNR)
                # 范围稍微加大一点点 +/- 0.2 以分散密集点
                jitter = np.random.uniform(-0.2, 0.2)
                scatter_x.append(snr + jitter)
                scatter_y.append(m)
        
        # 散点颜色使用淡化的学术蓝，增加透明度降低重叠感
        plt.scatter(scatter_x, scatter_y, alpha=0.08, color=academic_blue, s=30, 
                   label='Raw Measurements', zorder=1)

    # 2. 绘制平均值折线 (Average Line)
    # 线条加粗 (linewidth=4)，颜色使用深学术蓝
    plt.plot(snr_values, cluster_sizes, linewidth=4, 
             color=academic_blue, label='Avg Cluster Size', zorder=2)

    # 字体与坐标轴设置
    plt.xlabel(x_label, fontsize=18, fontweight='normal')  # 加大字号
    plt.ylabel('Cluster Size (nodes)', fontsize=18, fontweight='normal') # 加大字号
    plt.tick_params(axis='both', which='major', labelsize=16) # 加大刻度字号
    
    # 去除顶部标题
    # plt.title('Cluster Size vs Leader Received SNR (Avg & Raw)', ...) 
    
    plt.grid(True, alpha=0.3)
    
    # 优化图例：移到右下角，去除边框
    plt.legend(loc='lower right', frameon=False, fontsize=16)
    
    # 设置 Y 轴范围
    max_y = max(data.get('total_nodes', 6), max(cluster_sizes) if cluster_sizes else 6)
    plt.ylim(bottom=0, top=max_y + 0.5)
    
    save_current_fig("cluster_size_combined")
    
    if has_packet_loss:
        # ==========================================
        # 图3: Packet Loss Rate vs SNR
        # ==========================================
        plt.figure(figsize=(8, 6))
        plt.plot(snr_values, packet_losses, 'o-', linewidth=2, markersize=8,
                 color='#F44336', label='Avg Packet Loss')
        plt.fill_between(snr_values, 0, packet_losses, alpha=0.2, color='#F44336')
        plt.xlabel(x_label, fontsize=12)
        plt.ylabel('Packet Loss Rate (%)', fontsize=12)
        plt.title('Packet Loss Rate vs Leader Received SNR', fontsize=12, fontweight='bold')
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.ylim(bottom=0)
        save_current_fig("packet_loss")
        
        # ==========================================
        # 图4: Packet Loss per Node
        # ==========================================
        plt.figure(figsize=(8, 6))
        all_nodes = set()
        for plr in packet_loss_per_node:
            all_nodes.update(plr.keys())
        all_nodes = sorted(all_nodes, key=lambda x: int(x) if str(x).isdigit() else 0)
        
        if all_nodes:
            colors = plt.cm.tab10(np.linspace(0, 1, len(all_nodes)))
            for i, node_id in enumerate(all_nodes):
                node_losses = []
                for plr in packet_loss_per_node:
                    loss = plr.get(str(node_id), plr.get(node_id, 0))
                    node_losses.append(loss * 100)
                plt.plot(snr_values, node_losses, 'o-', linewidth=2, markersize=6,
                         color=colors[i], label=f'Node {node_id}')
            
            plt.xlabel(x_label, fontsize=12)
            plt.ylabel('Packet Loss Rate (%)', fontsize=12)
            plt.title('Packet Loss Rate per Node vs Leader Received SNR', fontsize=12, fontweight='bold')
            plt.grid(True, alpha=0.3)
            plt.legend()
            save_current_fig("packet_loss_node")
    
    if has_actual_snr:
        # ==========================================
        # 图5: Actual SNR vs Target
        # ==========================================
        plt.figure(figsize=(8, 6))
        min_snr = min(snr_values)
        max_snr = max(snr_values)
        padding = 1
        plt.plot([min_snr-padding, max_snr+padding], [min_snr-padding, max_snr+padding], 
                 'k--', linewidth=1.5, alpha=0.5, label='Ideal')
        
        plt.errorbar(snr_values, actual_snr_values, yerr=actual_snr_stds,
                     fmt='o-', capsize=5, capthick=2, linewidth=2, markersize=8,
                     color='#4CAF50', ecolor='#A5D6A7', label='Actual SNR (avg)')
        
        plt.xlabel(x_label, fontsize=12)
        plt.ylabel('Actual Leader Received SNR (dB)', fontsize=12)
        plt.title('Actual Leader Received SNR vs Target', fontsize=12, fontweight='bold')
        plt.grid(True, alpha=0.3)
        plt.legend()
        save_current_fig("actual_snr")
        
        # ==========================================
        # 图6: Actual SNR per Node
        # ==========================================
        plt.figure(figsize=(8, 6))
        all_nodes = set()
        for asnr in actual_snr_per_node:
            all_nodes.update(asnr.keys())
        all_nodes = sorted(all_nodes, key=lambda x: int(x) if str(x).isdigit() else 0)
        
        if all_nodes:
            plt.plot([min_snr-padding, max_snr+padding], [min_snr-padding, max_snr+padding], 
                     'k--', linewidth=1.5, alpha=0.5, label='Ideal')
            
            colors = plt.cm.tab10(np.linspace(0, 1, len(all_nodes)))
            for i, node_id in enumerate(all_nodes):
                node_snrs = []
                for asnr in actual_snr_per_node:
                    snr = asnr.get(str(node_id), asnr.get(node_id, 0))
                    node_snrs.append(snr)
                plt.plot(snr_values, node_snrs, 'o-', linewidth=2, markersize=6,
                         color=colors[i], label=f'Node {node_id}')
            
            plt.xlabel(x_label, fontsize=12)
            plt.ylabel('Actual Leader Received SNR (dB)', fontsize=12)
            plt.title('Actual Leader Received SNR per Node vs Target', fontsize=12, fontweight='bold')
            plt.grid(True, alpha=0.3)
            plt.legend()
            save_current_fig("actual_snr_node")
    
    return output_prefix


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

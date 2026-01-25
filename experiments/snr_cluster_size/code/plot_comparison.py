#!/usr/bin/env python3
"""
SNR-集群规模实验对比绘图工具 (6节点 vs 4节点)
=============================================
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# 设置字体
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
plt.rcParams['axes.unicode_minus'] = False

def load_results(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def plot_comparison(file_6node, file_4node):
    # 加载数据
    data_6 = load_results(file_6node)
    data_4 = load_results(file_4node)
    
    # 过滤与整理数据 (Target SNR <= 18)
    results_6 = [r for r in data_6['results'] if r['target_snr'] <= 18.001]
    results_4 = [r for r in data_4['results'] if r['target_snr'] <= 18.001]
    
    results_6.sort(key=lambda x: x['target_snr'])
    results_4.sort(key=lambda x: x['target_snr'])
    
    # 提取序列
    snr_6 = [r['target_snr'] for r in results_6]
    size_6 = [r['average_cluster_size'] for r in results_6]
    raw_6 = [r.get('raw_cluster_measurements', []) for r in results_6]
    
    snr_4 = [r['target_snr'] for r in results_4]
    size_4 = [r['average_cluster_size'] for r in results_4]
    raw_4 = [r.get('raw_cluster_measurements', []) for r in results_4]
    
    # 绘图设置
    plt.figure(figsize=(10, 7))
    
    color_6 = '#1f77b4'  # 学术蓝
    color_4 = '#d62728'  # 学术红
    
    # --- 绘制 6 节点数据 ---
    # 散点 (带 Jitter)
    scatter_x_6 = []
    scatter_y_6 = []
    for s, measurements in zip(snr_6, raw_6):
        for m in measurements:
            jitter = np.random.uniform(-0.15, 0.15)
            scatter_x_6.append(s + jitter)
            scatter_y_6.append(m)
    
    plt.scatter(scatter_x_6, scatter_y_6, alpha=0.05, color=color_6, s=20, zorder=1)
    
    # 均值线
    plt.plot(snr_6, size_6, linewidth=4, color=color_6, label='6 Nodes', zorder=2)
    
    # --- 绘制 4 节点数据 ---
    # 散点 (带 Jitter)
    scatter_x_4 = []
    scatter_y_4 = []
    for s, measurements in zip(snr_4, raw_4):
        for m in measurements:
            jitter = np.random.uniform(-0.15, 0.15)
            scatter_x_4.append(s + jitter)
            scatter_y_4.append(m)
            
    plt.scatter(scatter_x_4, scatter_y_4, alpha=0.05, color=color_4, s=20, zorder=1)
    
    # 均值线
    plt.plot(snr_4, size_4, linewidth=4, color=color_4, label='4 Nodes', zorder=2)
    
    # --- 装饰 ---
    plt.xlabel('Leader Received SNR (dB)', fontsize=18, fontweight='normal')
    plt.ylabel('Cluster Size (nodes)', fontsize=18, fontweight='normal')
    plt.tick_params(axis='both', which='major', labelsize=16)
    
    # 理想线 (可选: 显示 4 和 6 的上限)
    # plt.axhline(y=6, color=color_6, linestyle='--', alpha=0.3, linewidth=1)
    # plt.axhline(y=4, color=color_4, linestyle='--', alpha=0.3, linewidth=1)
    
    plt.grid(True, alpha=0.3)
    plt.legend(loc='lower right', frameon=False, fontsize=16)
    
    # 如果两个数据集的 SNR 范围不完全一致，取并集范围
    all_snr = snr_6 + snr_4
    # plt.xlim(min(all_snr)-1, max(all_snr)+1)
    
    plt.ylim(bottom=0, top=6.5) # 固定为 6.5 以容纳 6 节点数据
    
    # 保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f'snr_experiment_comparison_{timestamp}.png'
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"[Saved] {filename}")
    plt.show()

if __name__ == "__main__":
    # 指定文件 (这里硬编码为您环境中的具体文件，或者自动查找最近的)
    # 6 节点文件 (之前使用过的)
    file_6 = "scripts/snr_experiment_results_20260124_215123.json"
    # 4 节点文件 (最新生成的)
    file_4 = "scripts/snr_experiment_results_20260124_230119.json"
    
    print(f"Comparing:")
    print(f"  6 Nodes: {file_6}")
    print(f"  4 Nodes: {file_4}")
    
    plot_comparison(file_6, file_4)

#!/usr/bin/env python3
"""
SNR-集群规模实验对比绘图工具 (6节点 vs 4节点)
=============================================

优化版本：
- 方案一：散点降为背景纹理（极低透明度、灰色）
- 方案二：使用 fill_between 色带显示 Min-Max 范围
- 强调整数 Y 轴刻度网格线
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# 设置字体 - 使用 LaTeX 风格
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
plt.rcParams['mathtext.fontset'] = 'cm'
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
    snr_6 = np.array([r['target_snr'] for r in results_6])
    size_6 = np.array([r['average_cluster_size'] for r in results_6])
    raw_6 = [r.get('raw_cluster_measurements', []) for r in results_6]
    
    snr_4 = np.array([r['target_snr'] for r in results_4])
    size_4 = np.array([r['average_cluster_size'] for r in results_4])
    raw_4 = [r.get('raw_cluster_measurements', []) for r in results_4]
    
    # 计算 Min-Max 范围（用于色带）
    min_6 = np.array([min(m) if m else 0 for m in raw_6])
    max_6 = np.array([max(m) if m else 0 for m in raw_6])
    min_4 = np.array([min(m) if m else 0 for m in raw_4])
    max_4 = np.array([max(m) if m else 0 for m in raw_4])
    
    # 绘图设置
    fig, ax = plt.subplots(figsize=(10, 7))
    
    color_6 = '#1f77b4'  # 学术蓝
    color_4 = '#d62728'  # 学术红
    
    # ========== 1. 强调整数 Y 轴网格线 ==========
    # 只在整数位置画水平网格线（从1开始，因为0没有数据）
    ax.set_yticks([1, 2, 3, 4, 5, 6])
    ax.yaxis.grid(True, which='major', color='#cccccc', linestyle='-', linewidth=1.0, zorder=0)
    ax.xaxis.grid(True, which='major', color='#eeeeee', linestyle='--', linewidth=0.5, zorder=0)
    
    # ========== 2. 散点作为背景纹理（统一灰色、极低透明度）==========
    scatter_x_6, scatter_y_6 = [], []
    for s, measurements in zip(snr_6, raw_6):
        for m in measurements:
            scatter_x_6.append(s)  # 不加 jitter，保持整数特征
            scatter_y_6.append(m)
    
    scatter_x_4, scatter_y_4 = [], []
    for s, measurements in zip(snr_4, raw_4):
        for m in measurements:
            scatter_x_4.append(s)
            scatter_y_4.append(m)
    
    # 散点用统一的浅灰色，极低透明度
    ax.scatter(scatter_x_6, scatter_y_6, alpha=0.08, color='gray', s=15, 
               edgecolors='none', zorder=1, label=None)
    ax.scatter(scatter_x_4, scatter_y_4, alpha=0.08, color='gray', s=15, 
               edgecolors='none', zorder=1, label=None)
    
    # ========== 3. Min-Max 色带（fill_between）==========
    # 6 节点色带
    ax.fill_between(snr_6, min_6, max_6, alpha=0.15, color=color_6, 
                    edgecolor='none', zorder=2, label=None)
    # 4 节点色带
    ax.fill_between(snr_4, min_4, max_4, alpha=0.15, color=color_4, 
                    edgecolor='none', zorder=2, label=None)
    
    # ========== 4. 均值折线（主视觉）==========
    # 先画白色描边，增强可读性
    ax.plot(snr_6, size_6, linewidth=6, color='white', zorder=3)
    ax.plot(snr_4, size_4, linewidth=6, color='white', zorder=3)
    
    # 再画彩色均值线 - 使用学术符号 N= 表示网络总规模
    ax.plot(snr_6, size_6, linewidth=3, color=color_6, marker='o', markersize=6,
            label=r'$N=6$', zorder=4)
    ax.plot(snr_4, size_4, linewidth=3, color=color_4, marker='s', markersize=6,
            label=r'$N=4$', zorder=4)
    
    # ========== 5. 装饰与标签 ==========
    ax.set_xlabel('Leader Received SNR (dB)', fontsize=16)
    ax.set_ylabel('Cluster Size (mean)', fontsize=16)
    ax.tick_params(axis='both', which='major', labelsize=14)
    
    # Y 轴范围固定，强调整数（从1开始）
    ax.set_ylim(0.5, 6.8)
    ax.set_xlim(min(min(snr_6), min(snr_4)) - 0.5, max(max(snr_6), max(snr_4)) + 0.5)
    
    # 图例
    ax.legend(loc='lower right', frameon=True, fontsize=13, 
              fancybox=True, framealpha=0.9, edgecolor='lightgray')
    
    # 保存到 plots 目录
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    plots_dir = os.path.join(script_dir, '..', 'plots')
    os.makedirs(plots_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(plots_dir, f'snr_experiment_comparison_{timestamp}.png')
    plt.tight_layout()
    plt.savefig(filename, dpi=200, bbox_inches='tight')
    print(f"[Saved] {filename}")
    plt.show()

if __name__ == "__main__":
    import os
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(script_dir, '..', 'results')
    
    # 6 节点文件
    file_6 = os.path.join(results_dir, "snr_experiment_results_20260124_215123.json")
    # 4 节点文件
    file_4 = os.path.join(results_dir, "snr_experiment_results_20260124_230119.json")
    
    print(f"Comparing:")
    print(f"  6 Nodes: {file_6}")
    print(f"  4 Nodes: {file_4}")
    
    plot_comparison(file_6, file_4)

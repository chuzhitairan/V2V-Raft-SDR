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
import os
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


def find_latest_result_file(search_dirs, total_nodes):
    candidates = []
    for base_dir in search_dirs:
        if not os.path.isdir(base_dir):
            continue
        for name in os.listdir(base_dir):
            if not name.startswith("snr_experiment_results_") or not name.endswith(".json"):
                continue
            path = os.path.join(base_dir, name)
            try:
                data = load_results(path)
            except Exception:
                continue
            if data.get("total_nodes") != total_nodes:
                continue
            mtime = os.path.getmtime(path)
            candidates.append((mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def plot_comparison(file_6node, file_4node, show=True):
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
    
    # ========== 2. 散点作为背景纹理（带微小抖动，匹配颜色）==========
    # 使用 Jitter (抖动) 避免点重叠，同时颜色与主线保持一致
    jitter_strength = 0.12  # X轴抖动幅度

    scatter_x_6, scatter_y_6 = [], []
    for s, measurements in zip(snr_6, raw_6):
        for m in measurements:
            # 添加随机抖动
            jitter = np.random.uniform(-jitter_strength, jitter_strength)
            scatter_x_6.append(s + jitter) 
            scatter_y_6.append(m)
    
    scatter_x_4, scatter_y_4 = [], []
    for s, measurements in zip(snr_4, raw_4):
        for m in measurements:
            jitter = np.random.uniform(-jitter_strength, jitter_strength)
            scatter_x_4.append(s + jitter)
            scatter_y_4.append(m)
    
    # 散点颜色匹配，但透明度很低，体现分布密度
    ax.scatter(scatter_x_6, scatter_y_6, alpha=0.06, color=color_6, s=12, 
               edgecolors='none', zorder=1, label=None)
    ax.scatter(scatter_x_4, scatter_y_4, alpha=0.06, color=color_4, s=12, 
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
    ax.set_ylim(1.0, 6.0)
    ax.set_xlim(2.0, 14.0)
    
    # 图例
    # 添加一个用于说明 Min-Max 范围的图例项
    from matplotlib.patches import Patch
    handles, labels = ax.get_legend_handles_labels()
    
    # 创建一个灰色的补丁代表 Range
    range_patch = Patch(facecolor='gray', alpha=0.2, label='Min-Max Range')
    
    # 将 Range 放到底部
    handles.append(range_patch)
    
    ax.legend(handles=handles, loc='lower right', frameon=True, fontsize=13, 
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
    if show:
        plt.show()

if __name__ == "__main__":
    import argparse
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(script_dir, '..', 'results')
    repo_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))

    search_dirs = [results_dir, repo_root]

    parser = argparse.ArgumentParser(description="SNR-集群规模对比绘图")
    parser.add_argument("--no-show", action="store_true", help="仅保存图片，不弹出窗口")
    args = parser.parse_args()

    # 自动查找最新的 6 节点和 4 节点结果
    file_6 = find_latest_result_file(search_dirs, total_nodes=6)
    file_4 = find_latest_result_file(search_dirs, total_nodes=4)

    if not file_6 or not file_4:
        print("❌ 未找到完整的 6 节点/4 节点结果文件。")
        print(f"搜索目录: {search_dirs}")
        raise SystemExit(1)

    print(f"Comparing:")
    print(f"  6 Nodes: {file_6}")
    print(f"  4 Nodes: {file_4}")

    plot_comparison(file_6, file_4, show=not args.no_show)

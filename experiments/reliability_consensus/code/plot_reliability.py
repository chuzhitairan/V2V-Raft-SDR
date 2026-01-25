#!/usr/bin/env python3
"""
可靠性共识实验结果绘图工具
=========================

绘制：
1. 高 SNR 环境下的 P_sys vs p_node 曲线 (6条线对应 n=1~6)
2. 低 SNR 环境下的 P_sys vs p_node 曲线

使用方法:
    python3 plot_reliability.py <result_file.json>
    python3 plot_reliability.py  # 自动查找最新结果文件

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
    pattern = "reliability_experiment_results_*.json"
    files = glob.glob(pattern)
    if not files:
        files = glob.glob(os.path.join("scripts", pattern))
    if not files:
        files = glob.glob(os.path.join("experiments/reliability_consensus/results", pattern))
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
    snr_levels = data['snr_levels']
    p_node_levels = data['p_node_levels']
    n_levels = data['n_levels']
    
    if output_prefix is None:
        output_prefix = 'reliability_experiment_plot'
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 颜色映射
    colors = plt.cm.viridis(np.linspace(0, 0.9, len(n_levels)))
    
    for snr in snr_levels:
        # 过滤该 SNR 的数据
        snr_data = [r for r in results if r['snr'] == snr]
        
        if not snr_data:
            continue
        
        # 创建图表
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # ===== 左图: P_sys vs p_node =====
        for i, n in enumerate(n_levels):
            n_data = [r for r in snr_data if r['n'] == n]
            if not n_data:
                continue
            
            # 按 p_node 排序
            n_data.sort(key=lambda x: x['p_node'])
            
            p_nodes = [r['p_node'] for r in n_data]
            p_sys_values = [r['p_sys'] for r in n_data]
            
            ax1.plot(p_nodes, p_sys_values, 'o-', linewidth=2, markersize=8,
                    color=colors[i], label=f'n = {n}')
        
        # 绘制 n=1 时的理想线 (P_sys = p_node)
        ax1.plot([0.5, 1.0], [0.5, 1.0], 'k--', linewidth=1, alpha=0.5, 
                label='Ideal (n=1)')
        
        ax1.set_xlabel('Node Reliability ($p_{node}$)', fontsize=16)
        ax1.set_ylabel('System Reliability ($P_{sys}$)', fontsize=16)
        ax1.tick_params(axis='both', which='major', labelsize=14)
        ax1.set_xlim(0.55, 1.05)
        ax1.set_ylim(0, 1.05)
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='lower right', frameon=False, fontsize=12)
        
        # ===== 右图: 有效规模 vs p_node =====
        for i, n in enumerate(n_levels):
            n_data = [r for r in snr_data if r['n'] == n]
            if not n_data:
                continue
            
            n_data.sort(key=lambda x: x['p_node'])
            
            p_nodes = [r['p_node'] for r in n_data]
            effective_scales = [r['avg_effective_scale'] for r in n_data]
            scale_stds = [r['std_effective_scale'] for r in n_data]
            
            ax2.errorbar(p_nodes, effective_scales, yerr=scale_stds,
                        fmt='o-', linewidth=2, markersize=8, capsize=3,
                        color=colors[i], label=f'n = {n}')
        
        ax2.set_xlabel('Node Reliability ($p_{node}$)', fontsize=16)
        ax2.set_ylabel('Effective Scale (nodes)', fontsize=16)
        ax2.tick_params(axis='both', which='major', labelsize=14)
        ax2.set_xlim(0.55, 1.05)
        ax2.set_ylim(0, max(n_levels) + 0.5)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='lower right', frameon=False, fontsize=12)
        
        plt.tight_layout()
        
        # 保存
        filename = f'{output_prefix}_snr{int(snr)}_{timestamp}.png'
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"[Saved] {filename}")
        plt.close()
    
    # ===== 对比图: 不同 SNR 下 n=6 的曲线对比 =====
    if len(snr_levels) > 1:
        fig, ax = plt.subplots(figsize=(8, 6))
        
        snr_colors = {'20.0': '#1f77b4', '8.0': '#d62728', 20.0: '#1f77b4', 8.0: '#d62728'}
        
        for snr in snr_levels:
            snr_data = [r for r in results if r['snr'] == snr and r['n'] == max(n_levels)]
            if not snr_data:
                continue
            
            snr_data.sort(key=lambda x: x['p_node'])
            
            p_nodes = [r['p_node'] for r in snr_data]
            p_sys_values = [r['p_sys'] for r in snr_data]
            
            color = snr_colors.get(snr, '#333333')
            ax.plot(p_nodes, p_sys_values, 'o-', linewidth=3, markersize=10,
                   color=color, label=f'SNR = {snr} dB')
        
        ax.set_xlabel('Node Reliability ($p_{node}$)', fontsize=18)
        ax.set_ylabel('System Reliability ($P_{sys}$)', fontsize=18)
        ax.tick_params(axis='both', which='major', labelsize=16)
        ax.set_xlim(0.55, 1.05)
        ax.set_ylim(0, 1.05)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='lower right', frameon=False, fontsize=16)
        
        plt.tight_layout()
        
        filename = f'{output_prefix}_comparison_{timestamp}.png'
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"[Saved] {filename}")
        plt.close()
    
    return output_prefix


def print_summary(data):
    """打印实验摘要"""
    results = data['results']
    
    print("\n" + "=" * 70)
    print("可靠性共识实验结果摘要")
    print("=" * 70)
    print(f"总节点数: {data['total_nodes']}")
    print(f"SNR 等级: {data['snr_levels']}")
    print(f"p_node 等级: {data['p_node_levels']}")
    print(f"系统规模: {data['n_levels']}")
    print(f"每组测试轮数: {data['rounds_per_config']}")
    print("-" * 70)
    
    for snr in data['snr_levels']:
        print(f"\n--- SNR = {snr} dB ---")
        print(f"{'p_node':<10} " + " ".join([f"n={n:<6}" for n in data['n_levels']]))
        print("-" * 55)
        
        for p_node in data['p_node_levels']:
            row = f"{p_node:<10.2f} "
            for n in data['n_levels']:
                match = [r for r in results 
                        if r['snr'] == snr and r['p_node'] == p_node and r['n'] == n]
                if match:
                    p_sys = match[0]['p_sys']
                    row += f"{p_sys:<8.3f}"
                else:
                    row += f"{'N/A':<8}"
            print(row)
    
    print("=" * 70)


def main():
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = find_latest_result_file()
        if not filepath:
            print("❌ 找不到结果文件。请指定文件路径:")
            print("   python3 plot_reliability.py <result_file.json>")
            return
    
    print(f"📊 加载结果文件: {filepath}")
    
    try:
        data = load_results(filepath)
    except Exception as e:
        print(f"❌ 加载失败: {e}")
        return
    
    print_summary(data)
    plot_results(data)


if __name__ == "__main__":
    main()

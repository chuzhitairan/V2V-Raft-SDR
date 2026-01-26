#!/usr/bin/env python3
"""
可靠性共识实验结果绘图工具
=========================

支持两种模式：
1. 单文件模式: 对一次实验（固定 SNR 和 n）的结果画图
2. 合并模式: 合并多个结果文件，按 SNR 或 n 分组对比

结果目录结构:
    results/
    ├── n3_snr12/
    │   └── reliability_20250126_120000.json
    ├── n3_snr16/
    │   └── reliability_20250126_130000.json
    └── n4_snr16/
        └── reliability_20250126_140000.json

使用方法:
    # 列出所有结果文件
    python3 plot_reliability.py --list
    
    # 处理最新的结果文件
    python3 plot_reliability.py
    
    # 处理所有结果文件
    python3 plot_reliability.py --all
    
    # 指定特定文件
    python3 plot_reliability.py ../results/n4_snr16/reliability_*.json
    
    # 合并多个文件画图 (同一 SNR，不同 n)
    python3 plot_reliability.py --merge --all
    
    # 合并多个文件画图 (同一 n，不同 SNR)  
    python3 plot_reliability.py --merge --group-by snr --all

作者: V2V-Raft-SDR 项目
"""

import json
import sys
import os
import glob
import argparse
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# 设置字体
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
plt.rcParams['axes.unicode_minus'] = False


def find_latest_result_file():
    """查找最新的结果文件"""
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_base = os.path.join(script_dir, '..', 'results')
    
    patterns = [
        # 新目录结构: results/n{n}_snr{snr}/reliability_*.json
        os.path.join(results_base, '*', 'reliability_*.json'),
        # 旧目录结构（兼容）
        os.path.join(results_base, 'reliability_*.json'),
        "reliability_snr*.json",
        "experiments/reliability_consensus/results/*/reliability_*.json",
        "experiments/reliability_consensus/results/reliability_*.json",
    ]
    
    all_files = []
    for pattern in patterns:
        all_files.extend(glob.glob(pattern))
    
    if not all_files:
        return None
    return max(all_files, key=os.path.getctime)


def find_all_result_files(results_dir=None):
    """查找所有结果文件"""
    if results_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        results_dir = os.path.join(script_dir, '..', 'results')
    
    patterns = [
        os.path.join(results_dir, '*', 'reliability_*.json'),  # 新结构
        os.path.join(results_dir, 'reliability_*.json'),       # 旧结构
    ]
    
    all_files = []
    for pattern in patterns:
        all_files.extend(glob.glob(pattern))
    
    return sorted(set(all_files), key=os.path.getctime, reverse=True)


def load_results(filepath):
    """加载结果文件"""
    with open(filepath, 'r') as f:
        return json.load(f)


def plot_single_result(data, output_dir=None):
    """
    绘制单次实验结果（固定 SNR 和 n）
    生成两张图：
    1. P_sys vs p_node
    2. 有效规模 vs p_node
    """
    results = data['results']
    snr = data['snr']
    n = data['n']
    
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 按 p_node 排序
    results_sorted = sorted(results, key=lambda x: x['p_node'])
    
    p_nodes = [r['p_node'] for r in results_sorted]
    p_sys_values = [r['p_sys'] for r in results_sorted]
    effective_scales = [r['avg_effective_scale'] for r in results_sorted]
    scale_stds = [r['std_effective_scale'] for r in results_sorted]
    
    # ===== 图1: P_sys vs p_node =====
    fig, ax = plt.subplots(figsize=(8, 6))
    
    ax.plot(p_nodes, p_sys_values, 'o-', linewidth=2.5, markersize=10,
            color='#1f77b4', label=f'Measured ($n={n}$, SNR={snr}dB)')
    
    # 理论曲线: 多数表决二项分布
    # P_sys = sum_{k=ceil((n+1)/2)}^{n+1} C(n+1,k) * p^k * (1-p)^(n+1-k)
    # 其中 n+1 是总节点数（含 Leader）
    try:
        from scipy.special import comb
        p_theory = np.linspace(0.5, 1.0, 100)
        total_nodes = n + 1  # 含 Leader
        threshold = (total_nodes + 1) // 2  # 多数阈值
        
        p_sys_theory = np.zeros_like(p_theory)
        for k in range(threshold, total_nodes + 1):
            p_sys_theory += comb(total_nodes, k, exact=True) * (p_theory ** k) * ((1 - p_theory) ** (total_nodes - k))
        
        ax.plot(p_theory, p_sys_theory, '--', linewidth=2, color='#ff7f0e', 
                alpha=0.8, label=f'Theory (Binomial, $n={n}$)')
    except ImportError:
        print("⚠️ scipy 未安装，跳过理论曲线")
    
    # n=1 基准线
    ax.plot([0.5, 1.0], [0.5, 1.0], 'k:', linewidth=1.5, alpha=0.5,
            label='Baseline ($n=1$)')
    
    ax.set_xlabel('Node Reliability ($p_{node}$)', fontsize=16)
    ax.set_ylabel('System Reliability ($P_{sys}$)', fontsize=16)
    ax.set_title(f'Reliability Experiment: SNR = {snr} dB, n = {n}', fontsize=14)
    ax.tick_params(axis='both', which='major', labelsize=14)
    ax.set_xlim(0.55, 1.02)
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right', frameon=True, fontsize=12)
    
    plt.tight_layout()
    
    filename = os.path.join(output_dir, f'plot_psys_snr{snr:.0f}_n{n}_{timestamp}.png')
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"[保存] {filename}")
    plt.close()
    
    # ===== 图2: 有效规模 vs p_node =====
    fig, ax = plt.subplots(figsize=(8, 6))
    
    ax.errorbar(p_nodes, effective_scales, yerr=scale_stds,
                fmt='s-', linewidth=2.5, markersize=10, capsize=4,
                color='#2ca02c', label=f'Measured ($n={n}$)')
    
    # 理论有效规模: E[scale] = n * p_node (Follower)
    p_theory = np.array(p_nodes)
    scale_theory = n * p_theory
    ax.plot(p_theory, scale_theory, '--', linewidth=2, color='#d62728',
            alpha=0.8, label=f'Theory ($n \\times p_{{node}}$)')
    
    ax.axhline(y=n, color='gray', linestyle=':', linewidth=1.5, alpha=0.5,
               label=f'Max scale ($n={n}$)')
    
    ax.set_xlabel('Node Reliability ($p_{node}$)', fontsize=16)
    ax.set_ylabel('Effective Scale (nodes)', fontsize=16)
    ax.set_title(f'Effective Scale: SNR = {snr} dB, n = {n}', fontsize=14)
    ax.tick_params(axis='both', which='major', labelsize=14)
    ax.set_xlim(0.55, 1.02)
    ax.set_ylim(0, n + 1)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right', frameon=True, fontsize=12)
    
    plt.tight_layout()
    
    filename = os.path.join(output_dir, f'plot_scale_snr{snr:.0f}_n{n}_{timestamp}.png')
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"[保存] {filename}")
    plt.close()
    
    return True


def plot_merged_results(data_list, group_by='n', output_dir=None):
    """
    合并多个结果文件，绘制对比图
    
    group_by: 'n' - 同一 SNR，对比不同 n
              'snr' - 同一 n，对比不同 SNR
    """
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 颜色映射
    colors = plt.cm.tab10(np.linspace(0, 1, 10))
    
    if group_by == 'n':
        # 按 n 分组，同一 SNR 下对比不同 n
        snr_groups = {}
        for data in data_list:
            snr = data['snr']
            if snr not in snr_groups:
                snr_groups[snr] = []
            snr_groups[snr].append(data)
        
        for snr, group in snr_groups.items():
            fig, ax = plt.subplots(figsize=(10, 7))
            
            # 按 n 排序
            group_sorted = sorted(group, key=lambda x: x['n'])
            
            for i, data in enumerate(group_sorted):
                n = data['n']
                results = sorted(data['results'], key=lambda x: x['p_node'])
                
                p_nodes = [r['p_node'] for r in results]
                p_sys_values = [r['p_sys'] for r in results]
                
                ax.plot(p_nodes, p_sys_values, 'o-', linewidth=2.5, markersize=9,
                       color=colors[i % len(colors)], label=f'$n = {n}$')
            
            # 基准线
            ax.plot([0.5, 1.0], [0.5, 1.0], 'k:', linewidth=1.5, alpha=0.5,
                   label='Baseline ($n=1$)')
            
            ax.set_xlabel('Node Reliability ($p_{node}$)', fontsize=18)
            ax.set_ylabel('System Reliability ($P_{sys}$)', fontsize=18)
            ax.set_title(f'Reliability Comparison: SNR = {snr} dB', fontsize=16)
            ax.tick_params(axis='both', which='major', labelsize=14)
            ax.set_xlim(0.55, 1.02)
            ax.set_ylim(0, 1.05)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='lower right', frameon=True, fontsize=14)
            
            plt.tight_layout()
            
            filename = os.path.join(output_dir, f'plot_compare_snr{snr:.0f}_by_n_{timestamp}.png')
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            print(f"[保存] {filename}")
            plt.close()
    
    else:  # group_by == 'snr'
        # 按 SNR 分组，同一 n 下对比不同 SNR
        n_groups = {}
        for data in data_list:
            n = data['n']
            if n not in n_groups:
                n_groups[n] = []
            n_groups[n].append(data)
        
        for n, group in n_groups.items():
            fig, ax = plt.subplots(figsize=(10, 7))
            
            # 按 SNR 排序
            group_sorted = sorted(group, key=lambda x: x['snr'], reverse=True)
            
            snr_colors = {16.0: '#1f77b4', 6.0: '#d62728', 20.0: '#2ca02c', 10.0: '#ff7f0e'}
            
            for i, data in enumerate(group_sorted):
                snr = data['snr']
                results = sorted(data['results'], key=lambda x: x['p_node'])
                
                p_nodes = [r['p_node'] for r in results]
                p_sys_values = [r['p_sys'] for r in results]
                
                color = snr_colors.get(snr, colors[i % len(colors)])
                ax.plot(p_nodes, p_sys_values, 'o-', linewidth=2.5, markersize=9,
                       color=color, label=f'SNR = {snr} dB')
            
            # 基准线
            ax.plot([0.5, 1.0], [0.5, 1.0], 'k:', linewidth=1.5, alpha=0.5,
                   label='Baseline ($n=1$)')
            
            ax.set_xlabel('Node Reliability ($p_{node}$)', fontsize=18)
            ax.set_ylabel('System Reliability ($P_{sys}$)', fontsize=18)
            ax.set_title(f'Reliability Comparison: $n = {n}$', fontsize=16)
            ax.tick_params(axis='both', which='major', labelsize=14)
            ax.set_xlim(0.55, 1.02)
            ax.set_ylim(0, 1.05)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='lower right', frameon=True, fontsize=14)
            
            plt.tight_layout()
            
            filename = os.path.join(output_dir, f'plot_compare_n{n}_by_snr_{timestamp}.png')
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            print(f"[保存] {filename}")
            plt.close()


def print_summary(data):
    """打印单次实验摘要"""
    results = data['results']
    snr = data['snr']
    n = data['n']
    
    print("\n" + "=" * 60)
    print("可靠性共识实验结果摘要")
    print("=" * 60)
    print(f"SNR: {snr} dB")
    print(f"Follower 数量 (n): {n}")
    print(f"每组测试轮数: {data.get('rounds_per_config', 'N/A')}")
    print(f"p_node 等级: {data.get('p_node_levels', 'N/A')}")
    print("-" * 60)
    
    print(f"\n{'p_node':<10} {'P_sys':<10} {'有效规模':<20} {'成功/总数':<15}")
    print("-" * 60)
    
    for r in sorted(results, key=lambda x: x['p_node']):
        scale_str = f"{r['avg_effective_scale']:.2f}±{r['std_effective_scale']:.2f}"
        count_str = f"{r['success_count']}/{r['total_rounds']}"
        print(f"{r['p_node']:<10.2f} {r['p_sys']:<10.3f} {scale_str:<20} {count_str:<15}")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='可靠性共识实验结果绘图工具')
    parser.add_argument('files', nargs='*', help='结果文件路径 (支持通配符)')
    parser.add_argument('--merge', action='store_true', help='合并多个文件绘制对比图')
    parser.add_argument('--group-by', choices=['n', 'snr'], default='n',
                       help='合并模式下的分组方式: n (同SNR比较不同n) 或 snr (同n比较不同SNR)')
    parser.add_argument('--output-dir', '-o', help='输出目录')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有可用的结果文件')
    parser.add_argument('--all', '-a', action='store_true', help='处理所有找到的结果文件')
    
    args = parser.parse_args()
    
    # 列出所有文件模式
    if args.list:
        all_files = find_all_result_files()
        if not all_files:
            print("❌ 未找到任何结果文件")
        else:
            print(f"📂 找到 {len(all_files)} 个结果文件:")
            for f in all_files:
                try:
                    data = load_results(f)
                    n = data.get('n', '?')
                    snr = data.get('snr', '?')
                    print(f"   - {f}  (n={n}, SNR={snr} dB)")
                except Exception as e:
                    print(f"   - {f}  (加载失败: {e})")
        return
    
    # 获取文件列表
    if args.files:
        files = []
        for pattern in args.files:
            matched = glob.glob(pattern)
            if matched:
                files.extend(matched)
            elif os.path.exists(pattern):
                files.append(pattern)
        files = list(set(files))  # 去重
    elif args.all:
        files = find_all_result_files()
    else:
        filepath = find_latest_result_file()
        if filepath:
            files = [filepath]
        else:
            print("❌ 找不到结果文件。请指定文件路径:")
            print("   python3 plot_reliability.py <result_file.json>")
            print("   python3 plot_reliability.py --merge *.json")
            print("   python3 plot_reliability.py --list  # 列出所有文件")
            print("   python3 plot_reliability.py --all   # 处理所有文件")
            return
    
    if not files:
        print("❌ 没有找到匹配的文件")
        return
    
    print(f"📊 找到 {len(files)} 个结果文件:")
    for f in sorted(files):
        print(f"   - {f}")
    
    # 加载所有数据
    data_list = []
    for filepath in files:
        try:
            data = load_results(filepath)
            data['_filepath'] = filepath
            data_list.append(data)
        except Exception as e:
            print(f"⚠️ 加载失败: {filepath} - {e}")
    
    if not data_list:
        print("❌ 没有成功加载任何数据")
        return
    
    if args.output_dir:
        output_dir = args.output_dir
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    os.makedirs(output_dir, exist_ok=True)
    
    if args.merge and len(data_list) > 1:
        # 合并模式
        print(f"\n📈 合并绘图模式 (按 {args.group_by} 分组)")
        plot_merged_results(data_list, group_by=args.group_by, output_dir=output_dir)
    else:
        # 单文件模式
        for data in data_list:
            print(f"\n--- {data['_filepath']} ---")
            print_summary(data)
            plot_single_result(data, output_dir=output_dir)
    
    print("\n✅ 绘图完成!")


if __name__ == "__main__":
    main()

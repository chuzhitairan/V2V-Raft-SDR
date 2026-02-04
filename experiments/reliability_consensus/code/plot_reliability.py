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
        p_theory = np.linspace(0.55, 1.05, 100)
        total_nodes = n + 1  # 含 Leader
        threshold = (total_nodes + 1) // 2  # 多数阈值
        
        p_sys_theory = np.zeros_like(p_theory)
        for k in range(threshold, total_nodes + 1):
            p_sys_theory += comb(total_nodes, k, exact=True) * (p_theory ** k) * ((1 - p_theory) ** (total_nodes - k))
        
        ax.plot(p_theory, p_sys_theory, '--', linewidth=2, color='#ff7f0e', 
                alpha=0.8, label=f'Theory (Binomial, $n={n}$)')
    except ImportError:
        print("⚠️ scipy 未安装，跳过理论曲线")

    # 基线：单节点可靠性（期望） - 绘制一次并放在图例底部
    baseline_label = 'Single-node Reliability (Expected)'
    ax.plot([0.55, 1.05], [0.55, 1.05], 'k:', linewidth=1.5, alpha=0.5,
            label=baseline_label)

    ax.set_xlabel('Node Reliability ($p_{node}$)', fontsize=16)
    ax.set_ylabel('System Reliability ($P_{sys}$)', fontsize=16)
    ax.set_title(f'Reliability Experiment: SNR = {snr} dB, n = {n}', fontsize=14)
    ax.tick_params(axis='both', which='major', labelsize=14)
    ax.set_xlim(0.55, 1.05)
    ax.set_ylim(0.55, 1.05)
    # x/y ticks show 0.6..1.0 (step 0.1); do not label the left edge 0.55
    ax.set_xticks(np.arange(0.6, 1.01, 0.1))
    ax.set_yticks(np.arange(0.6, 1.01, 0.1))
    ax.grid(True, alpha=0.3)
    # 去重 legend，避免重复标签，并把基线移动到底部
    handles, labels = ax.get_legend_handles_labels()
    unique = {}
    new_h, new_l = [], []
    for h, l in zip(handles, labels):
        if l not in unique:
            unique[l] = True
            new_h.append(h)
            new_l.append(l)
    # Move baseline to end if present
    if baseline_label in new_l and new_l[-1] != baseline_label:
        idx = new_l.index(baseline_label)
        bl_h = new_h.pop(idx)
        bl_l = new_l.pop(idx)
        new_h.append(bl_h)
        new_l.append(bl_l)
    ax.legend(new_h, new_l, loc='lower right', frameon=True, fontsize=12)
    
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
    ax.set_xlim(0.5, 0.99)
    ax.set_xticks(np.arange(0.5, 1.0, 0.1))
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
    from matplotlib.lines import Line2D
    import matplotlib.patches as mpatches
    
    # 使用 LaTeX 风格字体
    plt.rcParams['mathtext.fontset'] = 'cm'
    plt.rcParams['font.family'] = 'serif'
    
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 颜色映射 - 使用高对比度、打印友好的颜色
    color_palette = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#F0E442', 
                     '#56B4E9', '#E69F00', '#000000']
    # 标记形状 - 便于黑白打印区分
    marker_palette = ['o', 's', '^', 'D', 'v', 'p', 'h', '*']
    # 虚线样式 - 不同的点划线样式
    linestyle_palette = ['--', '-.', ':']
    
    # 右轴专用颜色（深灰色，与左轴黑色区分）
    GAIN_AXIS_COLOR = '#555555'
    LEFT_AXIS_COLOR = '#000000'
    
    if group_by == 'n':
        # 按 n 分组，同一 SNR 下对比不同 n
        snr_groups = {}
        for data in data_list:
            snr = data['snr']
            snr_groups.setdefault(snr, []).append(data)

        for snr, group in snr_groups.items():
            # 创建图形，留出顶部空间放图例
            fig, ax = plt.subplots(figsize=(8, 6))

            # 按 n 排序
            group_sorted = sorted(group, key=lambda x: x['n'])
            
            # 为每个 n 值分配颜色、标记和虚线样式
            n_values = [d['n'] for d in group_sorted]
            n_to_color = {n: color_palette[i % len(color_palette)] for i, n in enumerate(n_values)}
            n_to_marker = {n: marker_palette[i % len(marker_palette)] for i, n in enumerate(n_values)}
            n_to_dashstyle = {n: linestyle_palette[i % len(linestyle_palette)] for i, n in enumerate(n_values)}

            # 创建右轴，使用灰色强化与左轴的区分
            ax2 = ax.twinx()
            ax2.set_ylabel('Consensus Gain', fontsize=12, color=GAIN_AXIS_COLOR, fontweight='normal')
            ax2.tick_params(axis='y', labelcolor=GAIN_AXIS_COLOR, labelsize=11, colors=GAIN_AXIS_COLOR)
            ax2.spines['right'].set_color(GAIN_AXIS_COLOR)
            ax2.spines['right'].set_linewidth(1.5)
            
            # 左轴使用黑色
            ax.spines['left'].set_color(LEFT_AXIS_COLOR)
            ax.spines['left'].set_linewidth(1.5)
            ax.tick_params(axis='y', labelcolor=LEFT_AXIS_COLOR, colors=LEFT_AXIS_COLOR)
            
            for i, data in enumerate(group_sorted):
                n = data['n']
                results = sorted(data['results'], key=lambda x: x['p_node'])

                p_nodes = [r['p_node'] for r in results]
                p_sys_values = [r['p_sys'] for r in results]
                color = n_to_color[n]
                marker = n_to_marker[n]
                dashstyle = n_to_dashstyle[n]

                # 实线: 系统可靠性 P_sys
                ax.plot(p_nodes, p_sys_values, linestyle='-', linewidth=2.5, 
                        marker=marker, markersize=8, color=color)

                # 虚线: 系统增益 Gain = P_sys - p_node
                # 使用不同的虚线样式，每个数据点都有标记
                gain = np.array(p_sys_values) - np.array(p_nodes)
                ax2.plot(p_nodes, gain, linestyle=dashstyle, linewidth=1.8,
                         marker=marker, markersize=5,
                         color=color, alpha=0.65)

            # 绘制零增益线（右轴参考线）
            ax2.axhline(0.0, color=GAIN_AXIS_COLOR, linestyle=':', linewidth=1.0, alpha=0.5)

            # 基线：单节点可靠性 P_sys = p_node
            ax.plot([0.58, 0.92], [0.58, 0.92], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

            # 坐标轴设置 - 缩减范围到数据实际范围
            ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
            ax.set_ylabel(r'System Reliability ($P_{\mathrm{sys}}$)', fontsize=13, color=LEFT_AXIS_COLOR)
            ax.set_title(f'Reliability Comparison: SNR = {snr:.0f} dB', fontsize=14, fontweight='bold', pad=10)
            ax.tick_params(axis='both', which='major', labelsize=11)
            
            # X轴缩减到数据实际范围
            ax.set_xlim(0.57, 0.93)
            ax.set_xticks(np.arange(0.6, 0.91, 0.1))
            ax.set_ylim(0.57, 1.01)
            ax.set_yticks(np.arange(0.6, 1.01, 0.1))
            
            # 只保留水平网格线，突出 P_sys 数值
            ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
            ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)
            
            # 右轴范围
            ax2.set_ylim(-0.03, 0.18)
            ax2.set_yticks(np.arange(0.0, 0.16, 0.05))
            
            # ===== 创建统一图例（放在左上角空白处）=====
            # 合并数据系列和线条类型说明
            legend_handles = []
            
            # 数据系列（颜色+标记 = N 值，表示网络总规模）
            for n in n_values:
                legend_handles.append(
                    Line2D([0], [0], color=n_to_color[n], linestyle='-', linewidth=2.5, 
                           marker=n_to_marker[n], markersize=8,
                           label=f'$N = {n}$')
                )
            
            # 分隔（用空白占位）
            legend_handles.append(Line2D([0], [0], color='none', label=' '))
            
            # 线条类型说明
            legend_handles.append(
                Line2D([0], [0], color='dimgray', linestyle='-', linewidth=2.5, marker='o', markersize=6,
                       label=r'$P_{\mathrm{sys}}$ (left axis)')
            )
            legend_handles.append(
                Line2D([0], [0], color='dimgray', linestyle='--', linewidth=1.8, marker='o', markersize=4,
                       alpha=0.65, label='Gain (right axis)')
            )
            legend_handles.append(
                Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, alpha=0.6,
                       label=r'$P_{\mathrm{sys}} = p_{\mathrm{node}}$')
            )
            
            # 放在左上角，半透明背景，留出呼吸空间
            ax.legend(handles=legend_handles, loc='upper left',
                     bbox_to_anchor=(0.02, 0.98),  # 留出padding
                     frameon=True, fontsize=9, fancybox=True, 
                     framealpha=0.6,  # 半透明背景
                     edgecolor='lightgray', borderpad=0.8,
                     labelspacing=0.35, handlelength=2.2)

            plt.tight_layout()

            filename = os.path.join(output_dir, f'plot_compare_snr{snr:.0f}_by_n_{timestamp}.png')
            plt.savefig(filename, dpi=200, bbox_inches='tight')
            print(f"[保存] {filename}")
            plt.close()
    
    else:  # group_by == 'snr'
        # 按 SNR 分组，同一 n 下对比不同 SNR
        n_groups = {}
        for data in data_list:
            n = data['n']
            n_groups.setdefault(n, []).append(data)

        for n, group in n_groups.items():
            fig, ax = plt.subplots(figsize=(8, 6))

            # 按 SNR 排序（从高到低）
            group_sorted = sorted(group, key=lambda x: x['snr'], reverse=True)
            
            # 为每个 SNR 值分配颜色和标记
            snr_values = [d['snr'] for d in group_sorted]
            snr_to_color = {s: color_palette[i % len(color_palette)] for i, s in enumerate(snr_values)}
            snr_to_marker = {s: marker_palette[i % len(marker_palette)] for i, s in enumerate(snr_values)}

            for i, data in enumerate(group_sorted):
                snr_val = data['snr']
                results = sorted(data['results'], key=lambda x: x['p_node'])

                p_nodes = [r['p_node'] for r in results]
                p_sys_values = [r['p_sys'] for r in results]

                color = snr_to_color[snr_val]
                marker = snr_to_marker[snr_val]
                ax.plot(p_nodes, p_sys_values, linestyle='-', linewidth=2.5,
                        marker=marker, markersize=9, color=color)

            # 基线：单节点可靠性 P_sys = p_node
            ax.plot([0.58, 0.92], [0.58, 0.92], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

            ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
            ax.set_ylabel(r'System Reliability ($P_{\mathrm{sys}}$)', fontsize=13)
            ax.set_title(f'Reliability Comparison: $N = {n}$ ({n+1} nodes)', fontsize=14, fontweight='bold', pad=10)
            ax.tick_params(axis='both', which='major', labelsize=11)
            ax.set_xlim(0.57, 0.93)
            ax.set_xticks(np.arange(0.6, 0.91, 0.1))
            ax.set_ylim(0.57, 1.01)
            ax.set_yticks(np.arange(0.6, 1.01, 0.1))
            
            # 只保留水平网格线
            ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
            ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)
            
            # ===== 创建统一图例（放在左上角空白处）=====
            legend_handles = []
            
            # SNR 值
            for s in snr_values:
                legend_handles.append(
                    Line2D([0], [0], color=snr_to_color[s], linestyle='-', linewidth=2.5, 
                           marker=snr_to_marker[s], markersize=8,
                           label=f'SNR = {s:.0f} dB')
                )
            
            # 分隔
            legend_handles.append(Line2D([0], [0], color='none', label=' '))
            
            # 基线说明
            legend_handles.append(
                Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, alpha=0.6,
                       label=r'$P_{\mathrm{sys}} = p_{\mathrm{node}}$')
            )
            
            # 放在左上角，半透明背景
            ax.legend(handles=legend_handles, loc='upper left',
                     bbox_to_anchor=(0.02, 0.98),
                     frameon=True, fontsize=9, fancybox=True,
                     framealpha=0.6,
                     edgecolor='lightgray', borderpad=0.8,
                     labelspacing=0.35, handlelength=2.2)

            plt.tight_layout()

            filename = os.path.join(output_dir, f'plot_compare_n{n}_by_snr_{timestamp}.png')
            plt.savefig(filename, dpi=200, bbox_inches='tight')
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
    parser.add_argument('--filter-n', type=str, help='只保留指定的 n 值 (逗号分隔，如 1,3,6)')
    parser.add_argument('--filter-snr', type=str, help='只保留指定的 SNR 值 (逗号分隔，如 4,14)')
    
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
    
    # 应用过滤器
    if args.filter_n:
        filter_n_values = set(int(x.strip()) for x in args.filter_n.split(','))
        data_list = [d for d in data_list if d['n'] in filter_n_values]
        print(f"🔍 过滤 n ∈ {sorted(filter_n_values)}，剩余 {len(data_list)} 个文件")
    
    if args.filter_snr:
        filter_snr_values = set(float(x.strip()) for x in args.filter_snr.split(','))
        data_list = [d for d in data_list if d['snr'] in filter_snr_values]
        print(f"🔍 过滤 SNR ∈ {sorted(filter_snr_values)}，剩余 {len(data_list)} 个文件")
    
    if not data_list:
        print("❌ 过滤后没有剩余数据")
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

#!/usr/bin/env python3
"""
Result
=========================

Support
1. :  SNR  nResult
2. : Result SNR  n 

Result:
    results/
     n3_snr12/
        reliability_20250126_120000.json
     n3_snr16/
        reliability_20250126_130000.json
     n4_snr16/
         reliability_20250126_140000.json

Usage:
    # AllResult
    python3 plot_reliability.py --list
    
    # Result
    python3 plot_reliability.py
    
    # AllResult
    python3 plot_reliability.py --all
    
    # 
    python3 plot_reliability.py ../results/n4_snr16/reliability_*.json
    
    #  ( SNR n)
    python3 plot_reliability.py --merge --all
    
    #  ( n SNR)  
    python3 plot_reliability.py --merge --group-by snr --all

: V2V-Raft-SDR 
"""

import json
import sys
import os
import glob
import argparse
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
from math import comb

# 
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
plt.rcParams['axes.unicode_minus'] = False


def find_latest_result_file():
    """Result"""
    # 
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_base = os.path.join(script_dir, '..', 'results')
    
    patterns = [
        # : results/n{n}_snr{snr}/reliability_*.json
        os.path.join(results_base, '*', 'reliability_*.json'),
        # 
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
    """AllResult"""
    if results_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        results_dir = os.path.join(script_dir, '..', 'results')
    
    patterns = [
        os.path.join(results_dir, '*', 'reliability_*.json'),  # 
        os.path.join(results_dir, 'reliability_*.json'),       # 
    ]
    
    all_files = []
    for pattern in patterns:
        all_files.extend(glob.glob(pattern))
    
    return sorted(set(all_files), key=os.path.getctime, reverse=True)


def load_results(filepath):
    """Result"""
    with open(filepath, 'r') as f:
        return json.load(f)


def theoretical_p_sys(n: int, p: float) -> float:
    """ P_sysLoss 0.5 """
    p_sys = 0.0
    for k in range(n + 1):
        prob_k = comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
        if k > n - k:
            p_sys += prob_k
        elif k == n - k:
            p_sys += prob_k * 0.5
    return p_sys


def plot_theory_only(n_values, p_nodes, output_dir):
    """Theory"""
    from matplotlib.lines import Line2D

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    color_palette = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#F0E442',
                     '#56B4E9', '#E69F00', '#000000']
    marker_palette = ['o', 's', '^', 'D', 'v', 'p', 'h', '*']
    linestyle_palette = ['--', '-.', ':']

    fig, ax = plt.subplots(figsize=(8, 6))
    ax2 = ax.twinx()

    GAIN_AXIS_COLOR = '#555555'
    LEFT_AXIS_COLOR = '#000000'

    ax2.set_ylabel('Consensus Gain', fontsize=12, color=GAIN_AXIS_COLOR, fontweight='normal')
    ax2.tick_params(axis='y', labelcolor=GAIN_AXIS_COLOR, labelsize=11, colors=GAIN_AXIS_COLOR)
    ax2.spines['right'].set_color(GAIN_AXIS_COLOR)
    ax2.spines['right'].set_linewidth(1.5)

    ax.spines['left'].set_color(LEFT_AXIS_COLOR)
    ax.spines['left'].set_linewidth(1.5)
    ax.tick_params(axis='y', labelcolor=LEFT_AXIS_COLOR, colors=LEFT_AXIS_COLOR)

    n_values = sorted(set(n_values))
    n_to_color = {n: color_palette[i % len(color_palette)] for i, n in enumerate(n_values)}
    n_to_marker = {n: marker_palette[i % len(marker_palette)] for i, n in enumerate(n_values)}
    n_to_dashstyle = {n: linestyle_palette[i % len(linestyle_palette)] for i, n in enumerate(n_values)}

    for n in n_values:
        color = n_to_color[n]
        marker = n_to_marker[n]
        dashstyle = n_to_dashstyle[n]

        theory_values = [theoretical_p_sys(n, p) for p in p_nodes]
        theory_gain = np.array(theory_values) - np.array(p_nodes)

        ax.plot(p_nodes, theory_values, linestyle='-', linewidth=2.5,
                marker=marker, markersize=8, color=color)
        ax2.plot(p_nodes, theory_gain, linestyle=dashstyle, linewidth=1.6,
                 marker=marker, markersize=5, color=color, alpha=0.75)

    ax2.axhline(0.0, color=GAIN_AXIS_COLOR, linestyle=':', linewidth=1.0, alpha=0.5)
    ax.plot([p_nodes[0], p_nodes[-1]], [p_nodes[0], p_nodes[-1]], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

    ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
    ax.set_ylabel(r'System Reliability ($P_{\mathrm{sys}}$)', fontsize=13, color=LEFT_AXIS_COLOR)
    # ax.set_title('Reliability (Theory)', fontsize=14, fontweight='bold', pad=10)
    ax.tick_params(axis='both', which='major', labelsize=11)

    ax.set_xlim(0.55, 0.90)
    ax.set_xticks([0.6, 0.7, 0.8, 0.9])
    ax.set_ylim(0.55, 1.0)
    ax.set_yticks([0.6, 0.7, 0.8, 0.9, 1.0])

    ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
    ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)

    legend_handles = []
    for n in n_values:
        legend_handles.append(
            Line2D([0], [0], color=n_to_color[n], linestyle='-', linewidth=2.5,
                   marker=n_to_marker[n], markersize=8, label=f'$N = {n}$')
        )
    legend_handles.append(Line2D([0], [0], color='none', label=' '))
    legend_handles.append(
        Line2D([0], [0], color='dimgray', linestyle='-', linewidth=2.5, marker='o', markersize=6,
               label=r'$P_{\mathrm{sys}}$ (left axis)')
    )
    legend_handles.append(
        Line2D([0], [0], color='dimgray', linestyle='--', linewidth=1.6, marker='o', markersize=4,
               alpha=0.75, label='Gain (right axis)')
    )
    legend_handles.append(
        Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, alpha=0.6,
               label=r'$P_{\mathrm{sys}} = p_{\mathrm{node}}$')
    )

    ax2.legend(handles=legend_handles, loc='lower right',
              frameon=True, fontsize=9,
              fancybox=True, framealpha=0.8, edgecolor='lightgray',
              borderpad=0.8, labelspacing=0.35, handlelength=2.2)

    plt.tight_layout()
    filename = os.path.join(output_dir, f'plot_theory_only_n{"_".join(map(str, n_values))}_{timestamp}.png')
    plt.savefig(filename, dpi=200, bbox_inches='tight')
    print(f"[] {filename}")
    plt.close()


def plot_single_result(data, output_dir=None, add_theory=False):
    """
    Result SNR  n
    
    1. P_sys vs p_node
    2.  vs p_node
    """
    results = data['results']
    snr = data['snr']
    n = data['n']
    
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    # 
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    #  p_node 
    results_sorted = sorted(results, key=lambda x: x['p_node'])
    
    p_nodes = [r['p_node'] for r in results_sorted]
    p_sys_values = [r['p_sys'] for r in results_sorted]
    effective_scales = [r['avg_effective_scale'] for r in results_sorted]
    scale_stds = [r['std_effective_scale'] for r in results_sorted]
    
    # ===== 1: P_sys vs p_node =====
    fig, ax = plt.subplots(figsize=(8, 6))
    
    ax.plot(p_nodes, p_sys_values, 'o-', linewidth=2.5, markersize=10,
            color='#1f77b4', label=f'Measured ($n={n}$, SNR={snr}dB)')
    
    if add_theory:
        p_sys_theory = [theoretical_p_sys(n, p) for p in p_nodes]
        ax.plot(p_nodes, p_sys_theory, '-.', linewidth=2, color='#ff7f0e',
                alpha=0.8, label='Theory (no loss)')

    # Node - 
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
    #  legend
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
    print(f"[] {filename}")
    plt.close()
    
    # ===== 2:  vs p_node =====
    fig, ax = plt.subplots(figsize=(8, 6))
    
    ax.errorbar(p_nodes, effective_scales, yerr=scale_stds,
                fmt='s-', linewidth=2.5, markersize=10, capsize=4,
                color='#2ca02c', label=f'Measured ($n={n}$)')
    
    # : E[scale] = n * p_node (Follower)
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
    print(f"[] {filename}")
    plt.close()
    
    return True


def plot_merged_results(data_list, group_by='n', output_dir=None, add_theory=False, measured_only=False):
    """
    Result
    
    group_by: 'n' -  SNR n
              'snr' -  n SNR
    """
    from matplotlib.lines import Line2D
    import matplotlib.patches as mpatches
    
    #  LaTeX 
    plt.rcParams['mathtext.fontset'] = 'cm'
    plt.rcParams['font.family'] = 'serif'
    
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    # 
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    #  - 
    color_palette = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#F0E442', 
                     '#56B4E9', '#E69F00', '#000000']
    #  - 
    marker_palette = ['o', 's', '^', 'D', 'v', 'p', 'h', '*']
    #  - 
    linestyle_palette = ['--', '-.', ':']
    
    # 
    GAIN_AXIS_COLOR = '#555555'
    LEFT_AXIS_COLOR = '#000000'
    
    if group_by == 'n':
        #  n  SNR  n
        snr_groups = {}
        for data in data_list:
            snr = data['snr']
            snr_groups.setdefault(snr, []).append(data)

        for snr, group in snr_groups.items():
            # 
            fig, ax = plt.subplots(figsize=(8, 6))

            #  n 
            group_sorted = sorted(group, key=lambda x: x['n'])
            
            #  n 
            n_values = [d['n'] for d in group_sorted]
            n_to_color = {n: color_palette[i % len(color_palette)] for i, n in enumerate(n_values)}
            n_to_marker = {n: marker_palette[i % len(marker_palette)] for i, n in enumerate(n_values)}

            # 
            ax2 = ax.twinx()
            ax2.set_ylabel('Consensus Gain', fontsize=12, color=GAIN_AXIS_COLOR, fontweight='normal')
            ax2.tick_params(axis='y', labelcolor=GAIN_AXIS_COLOR, labelsize=11, colors=GAIN_AXIS_COLOR)
            ax2.spines['right'].set_color(GAIN_AXIS_COLOR)
            ax2.spines['right'].set_linewidth(1.5)
            
            # 
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

                # : System P_sys
                ax.plot(p_nodes, p_sys_values, linestyle='-', linewidth=2.5, 
                        marker=marker, markersize=8, color=color)

                # : Loss 0.5
                if add_theory:
                    theory_values = [theoretical_p_sys(n, p) for p in p_nodes]
                    ax.plot(p_nodes, theory_values, linestyle='-.', linewidth=2.0,
                            color=color, alpha=0.35)

                # : System Gain = P_sys - p_node
                # 
                gain = np.array(p_sys_values) - np.array(p_nodes)
                ax2.plot(p_nodes, gain, linestyle='--', linewidth=2.0,
                         marker=marker, markersize=5,
                         color=color, alpha=0.8)

                # : (Theory P_sys - p_node)
                if add_theory:
                    theory_values = [theoretical_p_sys(n, p) for p in p_nodes]
                    theory_gain = np.array(theory_values) - np.array(p_nodes)
                    ax2.plot(p_nodes, theory_gain, linestyle=':', linewidth=1.2,
                             marker=None,
                             color=color, alpha=0.35)

            # 
            ax2.axhline(0.0, color=GAIN_AXIS_COLOR, linestyle=':', linewidth=1.0, alpha=0.5)

            # Node P_sys = p_node
            ax.plot([0.58, 0.92], [0.58, 0.92], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

            #  - 
            ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
            ax.set_ylabel(r'System Reliability ($P_{\mathrm{sys}}$)', fontsize=13, color=LEFT_AXIS_COLOR)
            ax.set_title(f'Reliability Comparison: SNR = {snr:.0f} dB', fontsize=14, fontweight='bold', pad=10)
            ax.tick_params(axis='both', which='major', labelsize=11)
            
            # X
            ax.set_xlim(0.57, 0.93)
            ax.set_xticks(np.arange(0.6, 0.91, 0.1))
            ax.set_ylim(0.57, 1.01)
            ax.set_yticks(np.arange(0.6, 1.01, 0.1))
            
            #  P_sys 
            ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
            ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)
            
            # 
            ax2.set_ylim(-0.03, 0.18)
            ax2.set_yticks(np.arange(0.0, 0.16, 0.05))
            
            # ===== =====
            # 
            legend_handles = []
            
            # + = N 
            for n in n_values:
                legend_handles.append(
                    Line2D([0], [0], color=n_to_color[n], linestyle='-', linewidth=2.5, 
                           marker=n_to_marker[n], markersize=8,
                           label=f'$N = {n}$')
                )
            
            # 
            legend_handles.append(Line2D([0], [0], color='none', label=' '))
            
            # 
            legend_handles.append(
                Line2D([0], [0], color='dimgray', linestyle='-', linewidth=2.5, marker='o', markersize=6,
                       label=r'$P_{\mathrm{sys}}$ (left axis)')
            )
            legend_handles.append(
                Line2D([0], [0], color='dimgray', linestyle='--', linewidth=2.0, marker='o', markersize=4,
                       alpha=0.8, label='Gain (measured, right axis)')
            )
            if add_theory:
                legend_handles.append(
                    Line2D([0], [0], color='dimgray', linestyle=':', linewidth=1.2,
                           alpha=0.35, label='Gain (theory, right axis)')
                )
            legend_handles.append(
                Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, alpha=0.6,
                       label=r'$P_{\mathrm{sys}} = p_{\mathrm{node}}$')
            )

            if add_theory:
                legend_handles.append(
                    Line2D([0], [0], color='dimgray', linestyle='-.', linewidth=2.0, alpha=0.8,
                           label='Theory (no loss)')
                )
            
            # 
            ax.legend(handles=legend_handles, loc='upper left',
                     bbox_to_anchor=(0.02, 0.98),  # padding
                     frameon=True, fontsize=9, fancybox=True, 
                     framealpha=0.6,  # 
                     edgecolor='lightgray', borderpad=0.8,
                     labelspacing=0.35, handlelength=2.2)

            plt.tight_layout()

            filename = os.path.join(output_dir, f'plot_compare_snr{snr:.0f}_by_n_{timestamp}.png')
            plt.savefig(filename, dpi=200, bbox_inches='tight')
            print(f"[] {filename}")
            plt.close()

            # =====  =====
            if measured_only:
                fig, ax = plt.subplots(figsize=(8, 6))
                ax2 = ax.twinx()
                ax2.set_ylabel('Consensus Gain', fontsize=12, color=GAIN_AXIS_COLOR, fontweight='normal')
                ax2.tick_params(axis='y', labelcolor=GAIN_AXIS_COLOR, labelsize=11, colors=GAIN_AXIS_COLOR)
                ax2.spines['right'].set_color(GAIN_AXIS_COLOR)
                ax2.spines['right'].set_linewidth(1.5)

                ax.spines['left'].set_color(LEFT_AXIS_COLOR)
                ax.spines['left'].set_linewidth(1.5)
                ax.tick_params(axis='y', labelcolor=LEFT_AXIS_COLOR, colors=LEFT_AXIS_COLOR)

                for n in n_values:
                    color = n_to_color[n]
                    marker = n_to_marker[n]

                    data_for_n = next(d for d in group_sorted if d['n'] == n)
                    results = sorted(data_for_n['results'], key=lambda x: x['p_node'])
                    p_nodes = [r['p_node'] for r in results]
                    p_sys_values = [r['p_sys'] for r in results]
                    gain_values = np.array(p_sys_values) - np.array(p_nodes)

                    ax.plot(p_nodes, p_sys_values, linestyle='-', linewidth=2.5,
                            marker=marker, markersize=8, color=color)
                    ax2.plot(p_nodes, gain_values, linestyle='--', linewidth=2.0,
                             marker=marker, markersize=5, color=color, alpha=0.8)

                ax2.axhline(0.0, color=GAIN_AXIS_COLOR, linestyle=':', linewidth=1.0, alpha=0.5)
                ax.plot([0.58, 0.92], [0.58, 0.92], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

                ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
                ax.set_ylabel(r'System Reliability ($P_{\mathrm{sys}}$)', fontsize=13, color=LEFT_AXIS_COLOR)
                # ax.set_title(f'Reliability: SNR = {snr:.0f} dB', fontsize=14, fontweight='bold', pad=10)
                ax.tick_params(axis='both', which='major', labelsize=11)

                ax.set_xlim(0.55, 0.90)
                ax.set_xticks([0.6, 0.7, 0.8, 0.9])
                ax.set_ylim(0.55, 1.0)
                ax.set_yticks([0.6, 0.7, 0.8, 0.9, 1.0])

                ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
                ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)

                legend_handles = []
                for n in n_values:
                    legend_handles.append(
                        Line2D([0], [0], color=n_to_color[n], linestyle='-', linewidth=2.5,
                               marker=n_to_marker[n], markersize=8, label=f'$N = {n}$')
                    )
                legend_handles.append(Line2D([0], [0], color='none', label=' '))
                legend_handles.append(
                    Line2D([0], [0], color='dimgray', linestyle='-', linewidth=2.5, marker='o', markersize=6,
                           label=r'$P_{\mathrm{sys}}$ (left axis)')
                )
                legend_handles.append(
                    Line2D([0], [0], color='dimgray', linestyle='--', linewidth=2.0, marker='o', markersize=4,
                           alpha=0.8, label='Gain (right axis)')
                )
                legend_handles.append(
                    Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, alpha=0.6,
                           label=r'$P_{\mathrm{sys}} = p_{\mathrm{node}}$')
                )

                ax2.legend(handles=legend_handles, loc='lower right',
                          frameon=True, fontsize=9,
                          fancybox=True, framealpha=0.8, edgecolor='lightgray',
                          borderpad=0.8, labelspacing=0.35, handlelength=2.2)

                plt.tight_layout()
                measured_filename = os.path.join(output_dir, f'plot_measured_snr{snr:.0f}_by_n_{timestamp}.png')
                plt.savefig(measured_filename, dpi=200, bbox_inches='tight')
                print(f"[] {measured_filename}")
                plt.close()

            # ===== Theory =====
            if add_theory:
                fig, ax = plt.subplots(figsize=(8, 6))
                ax2 = ax.twinx()
                ax2.set_ylabel('Consensus Gain (Theory)', fontsize=12, color=GAIN_AXIS_COLOR, fontweight='normal')
                ax2.tick_params(axis='y', labelcolor=GAIN_AXIS_COLOR, labelsize=11, colors=GAIN_AXIS_COLOR)
                ax2.spines['right'].set_color(GAIN_AXIS_COLOR)
                ax2.spines['right'].set_linewidth(1.5)

                ax.spines['left'].set_color(LEFT_AXIS_COLOR)
                ax.spines['left'].set_linewidth(1.5)
                ax.tick_params(axis='y', labelcolor=LEFT_AXIS_COLOR, colors=LEFT_AXIS_COLOR)

                for n in n_values:
                    color = n_to_color[n]
                    marker = n_to_marker[n]

                    #  n  p_nodes 
                    data_for_n = next(d for d in group_sorted if d['n'] == n)
                    results = sorted(data_for_n['results'], key=lambda x: x['p_node'])
                    p_nodes = [r['p_node'] for r in results]

                    theory_values = [theoretical_p_sys(n, p) for p in p_nodes]
                    gain_values = np.array(theory_values) - np.array(p_nodes)

                    ax.plot(p_nodes, theory_values, linestyle='-', linewidth=2.5,
                            marker=marker, markersize=8, color=color)
                    ax2.plot(p_nodes, gain_values, linestyle='--', linewidth=1.8,
                             marker=marker, markersize=5, color=color, alpha=0.65)

                ax2.axhline(0.0, color=GAIN_AXIS_COLOR, linestyle=':', linewidth=1.0, alpha=0.5)
                ax.plot([0.58, 0.92], [0.58, 0.92], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

                ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
                ax.set_ylabel(r'Theoretical $P_{\mathrm{sys}}$', fontsize=13, color=LEFT_AXIS_COLOR)
                ax.set_title(f'Theoretical Reliability: SNR = {snr:.0f} dB', fontsize=14, fontweight='bold', pad=10)
                ax.tick_params(axis='both', which='major', labelsize=11)

                ax.set_xlim(0.57, 0.93)
                ax.set_xticks(np.arange(0.6, 0.91, 0.1))
                ax.set_ylim(0.57, 1.01)
                ax.set_yticks(np.arange(0.6, 1.01, 0.1))

                ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
                ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)

                legend_handles = []
                for n in n_values:
                    legend_handles.append(
                        Line2D([0], [0], color=n_to_color[n], linestyle='-', linewidth=2.5,
                               marker=n_to_marker[n], markersize=8, label=f'$N = {n}$')
                    )
                legend_handles.append(Line2D([0], [0], color='none', label=' '))
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

                ax.legend(handles=legend_handles, loc='upper left',
                          bbox_to_anchor=(0.02, 0.98), frameon=True, fontsize=9,
                          fancybox=True, framealpha=0.6, edgecolor='lightgray',
                          borderpad=0.8, labelspacing=0.35, handlelength=2.2)

                plt.tight_layout()
                theory_filename = os.path.join(output_dir, f'plot_theory_snr{snr:.0f}_by_n_{timestamp}.png')
                plt.savefig(theory_filename, dpi=200, bbox_inches='tight')
                print(f"[] {theory_filename}")
                plt.close()
    
    else:  # group_by == 'snr'
        #  SNR  n  SNR
        n_groups = {}
        for data in data_list:
            n = data['n']
            n_groups.setdefault(n, []).append(data)

        for n, group in n_groups.items():
            fig, ax = plt.subplots(figsize=(8, 6))

            #  SNR 
            group_sorted = sorted(group, key=lambda x: x['snr'], reverse=True)
            
            #  SNR 
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

            # Node P_sys = p_node
            ax.plot([0.58, 0.92], [0.58, 0.92], color='gray', linestyle=':', linewidth=1.5, alpha=0.6)

            ax.set_xlabel(r'Node Reliability ($p_{\mathrm{node}}$)', fontsize=13)
            ax.set_ylabel(r'System Reliability ($P_{\mathrm{sys}}$)', fontsize=13)
            ax.set_title(f'Reliability Comparison: $N = {n}$ ({n+1} nodes)', fontsize=14, fontweight='bold', pad=10)
            ax.tick_params(axis='both', which='major', labelsize=11)
            ax.set_xlim(0.57, 0.93)
            ax.set_xticks(np.arange(0.6, 0.91, 0.1))
            ax.set_ylim(0.57, 1.01)
            ax.set_yticks(np.arange(0.6, 1.01, 0.1))
            
            # 
            ax.grid(True, axis='y', alpha=0.4, linestyle='-', linewidth=0.6)
            ax.grid(True, axis='x', alpha=0.15, linestyle='--', linewidth=0.4)
            
            # ===== =====
            legend_handles = []
            
            # SNR 
            for s in snr_values:
                legend_handles.append(
                    Line2D([0], [0], color=snr_to_color[s], linestyle='-', linewidth=2.5, 
                           marker=snr_to_marker[s], markersize=8,
                           label=f'SNR = {s:.0f} dB')
                )
            
            # 
            legend_handles.append(Line2D([0], [0], color='none', label=' '))
            
            # 
            legend_handles.append(
                Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, alpha=0.6,
                       label=r'$P_{\mathrm{sys}} = p_{\mathrm{node}}$')
            )
            
            # 
            ax.legend(handles=legend_handles, loc='upper left',
                     bbox_to_anchor=(0.02, 0.98),
                     frameon=True, fontsize=9, fancybox=True,
                     framealpha=0.6,
                     edgecolor='lightgray', borderpad=0.8,
                     labelspacing=0.35, handlelength=2.2)

            plt.tight_layout()

            filename = os.path.join(output_dir, f'plot_compare_n{n}_by_snr_{timestamp}.png')
            plt.savefig(filename, dpi=200, bbox_inches='tight')
            print(f"[] {filename}")
            plt.close()


def print_summary(data):
    """"""
    results = data['results']
    snr = data['snr']
    n = data['n']
    
    print("\n" + "=" * 60)
    print("Result")
    print("=" * 60)
    print(f"SNR: {snr} dB")
    print(f"Follower  (n): {n}")
    print(f"Test: {data.get('rounds_per_config', 'N/A')}")
    print(f"\n{'p_node':<10} {'P_sys':<10} {'':<20} {'Success/':<15}")
    print("-" * 60)
    
    for r in sorted(results, key=lambda x: x['p_node']):
        scale_str = f"{r['avg_effective_scale']:.2f}{r['std_effective_scale']:.2f}"
        count_str = f"{r['success_count']}/{r['total_rounds']}"
        print(f"{r['p_node']:<10.2f} {r['p_sys']:<10.3f} {scale_str:<20} {count_str:<15}")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Result')
    parser.add_argument('files', nargs='*', help='Result (Support)')
    parser.add_argument('--merge', action='store_true', help='')
    parser.add_argument('--group-by', choices=['n', 'snr'], default='n',
                       help=': n (SNRn)  snr (nSNR)')
    parser.add_argument('--output-dir', '-o', help='')
    parser.add_argument('--list', '-l', action='store_true', help='AllResult')
    parser.add_argument('--all', '-a', action='store_true', help='AllResult')
    parser.add_argument('--filter-n', type=str, help=' n  ( 1,3,6)')
    parser.add_argument('--filter-snr', type=str, help=' SNR  ( 4,14)')
    parser.add_argument('--add-theory', action='store_true', help='Loss0.5')
    parser.add_argument('--measured-only', action='store_true', help='')
    parser.add_argument('--theory-only', action='store_true', help='TheoryResult')
    parser.add_argument('--theory-n', type=str, default='2,3,6,9,12,15', help=' n  ()')
    parser.add_argument('--theory-p', type=str, default='0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90',
                        help=' p_node  ()')
    
    args = parser.parse_args()
    
    # 
    if args.theory_only:
        n_values = [int(x.strip()) for x in args.theory_n.split(',') if x.strip()]
        p_nodes = [float(x.strip()) for x in args.theory_p.split(',') if x.strip()]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
        plot_theory_only(n_values, p_nodes, output_dir)
        return

    # All
    if args.list:
        all_files = find_all_result_files()
        if not all_files:
            print(" Result")
        else:
            print(f"  {len(all_files)} Result:")
            for f in all_files:
                try:
                    data = load_results(f)
                    n = data.get('n', '?')
                    snr = data.get('snr', '?')
                    print(f"   - {f}  (n={n}, SNR={snr} dB)")
                except Exception as e:
                    print(f"   - {f}  (Fail: {e})")
        return
    
    # 
    if args.files:
        files = []
        for pattern in args.files:
            matched = glob.glob(pattern)
            if matched:
                files.extend(matched)
            elif os.path.exists(pattern):
                files.append(pattern)
        files = list(set(files))  # 
    elif args.all:
        files = find_all_result_files()
    else:
        filepath = find_latest_result_file()
        if filepath:
            files = [filepath]
        else:
            print(" Result:")
            print("   python3 plot_reliability.py <result_file.json>")
            print("   python3 plot_reliability.py --merge *.json")
            print("   python3 plot_reliability.py --list  # All")
            print("   python3 plot_reliability.py --all   # All")
            return
    
    if not files:
        print(" ")
        return
    
    print(f"  {len(files)} Result:")
    for f in sorted(files):
        print(f"   - {f}")
    
    # All
    data_list = []
    for filepath in files:
        try:
            data = load_results(filepath)
            data['_filepath'] = filepath
            data_list.append(data)
        except Exception as e:
            print(f" Fail: {filepath} - {e}")
    
    if not data_list:
        print(" Success")
        return

    #  (snr, n) Result
    latest_map = {}
    for d in data_list:
        key = (d.get('snr'), d.get('n'))
        path = d.get('_filepath')
        try:
            mtime = os.path.getmtime(path) if path else 0
        except Exception:
            mtime = 0
        prev = latest_map.get(key)
        if prev is None or mtime > prev[0]:
            latest_map[key] = (mtime, d)
    data_list = [v[1] for v in latest_map.values()]
    
    # 
    if args.filter_n:
        filter_n_values = set(int(x.strip()) for x in args.filter_n.split(','))
        data_list = [d for d in data_list if d['n'] in filter_n_values]
        print(f"  n  {sorted(filter_n_values)} {len(data_list)} ")
    
    if args.filter_snr:
        filter_snr_values = set(float(x.strip()) for x in args.filter_snr.split(','))
        data_list = [d for d in data_list if d['snr'] in filter_snr_values]
        print(f"  SNR  {sorted(filter_snr_values)} {len(data_list)} ")
    
    if not data_list:
        print(" ")
        return
    
    if args.output_dir:
        output_dir = args.output_dir
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, '..', 'plots')
    os.makedirs(output_dir, exist_ok=True)
    
    if args.merge and len(data_list) > 1:
        # 
        print(f"\n  ( {args.group_by} )")
        plot_merged_results(
            data_list,
            group_by=args.group_by,
            output_dir=output_dir,
            add_theory=args.add_theory,
            measured_only=args.measured_only
        )
    else:
        # 
        for data in data_list:
            print(f"\n--- {data['_filepath']} ---")
            print_summary(data)
            plot_single_result(data, output_dir=output_dir, add_theory=args.add_theory)
    
    print("\n !")


if __name__ == "__main__":
    main()

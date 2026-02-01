#!/usr/bin/env python3
"""
合并结果目录中的 reliability_*.json 文件（按目录合并同目录下的多个运行结果）。

用法示例：
  python3 merge_results.py ../results/n3_snr4
  python3 merge_results.py ../results/n3_snr4 ../results/n3_snr14

脚本会在每个输入目录中生成一个合并文件 `reliability_merged_YYYYmmdd_HHMMSS.json`。
"""
import sys
import os
import json
from datetime import datetime
import argparse
import statistics


def merge_files_in_dir(dirpath):
    files = sorted([os.path.join(dirpath, f) for f in os.listdir(dirpath) if f.startswith('reliability_') and f.endswith('.json')])
    if len(files) < 2:
        print(f"[跳过] {dirpath}: 文件不足 (找到 {len(files)})")
        return None

    print(f"合并目录: {dirpath} -> {len(files)} 个文件")
    datas = []
    for f in files:
        with open(f, 'r') as fh:
            datas.append(json.load(fh))

    # 基本一致性检查 (n, p_node_levels, vote_deadline)
    n = datas[0].get('n')
    p_levels = datas[0].get('p_node_levels')
    vote_deadline = datas[0].get('vote_deadline')
    total_nodes = datas[0].get('total_nodes')

    for d in datas[1:]:
        if d.get('n') != n or d.get('p_node_levels') != p_levels:
            print(f"警告: 文件结构不一致，跳过合并 {dirpath}")
            return None

    # 合并 metadata
    merged = dict(datas[0])
    merged['start_time'] = datetime.now().isoformat()
    merged['rounds_per_config'] = sum(d.get('rounds_per_config', 0) for d in datas)

    # 合并 results
    merged_results = []
    follower_count = n - 1 if n else None

    for p in p_levels:
        # 找到每个文件中对应 p 的条目
        entries = []
        for d in datas:
            for r in d.get('results', []):
                if abs(r.get('p_node') - p) < 1e-6:
                    entries.append(r)
                    break
        if not entries:
            continue

        # 合并 raw_effective_scales
        all_scales = []
        total_rounds = 0
        total_success = 0
        for e in entries:
            scales = e.get('raw_effective_scales', [])
            all_scales.extend(scales)
            total_rounds += e.get('total_rounds', len(scales))
            total_success += e.get('success_count', 0)

        avg_scale = statistics.mean(all_scales) if all_scales else 0.0
        std_scale = statistics.stdev(all_scales) if len(all_scales) > 1 else 0.0

        # 重新计算丢包率：基于 follower_count * total_rounds
        if follower_count and total_rounds > 0:
            expected = follower_count * total_rounds
            received = sum(all_scales)
            packet_loss = 1.0 - (received / expected) if expected > 0 else 0.0
        else:
            packet_loss = 0.0

        merged_entry = {
            'snr': entries[0].get('snr'),
            'p_node': p,
            'n': n,
            'p_sys': total_success / total_rounds if total_rounds > 0 else 0.0,
            'avg_effective_scale': avg_scale,
            'std_effective_scale': std_scale,
            'success_count': total_success,
            'total_rounds': total_rounds,
            'packet_loss_rate': packet_loss,
            'raw_effective_scales': all_scales
        }
        merged_results.append(merged_entry)

    merged['results'] = merged_results

    out_name = f"reliability_merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = os.path.join(dirpath, out_name)
    with open(out_path, 'w') as fh:
        json.dump(merged, fh, indent=2)

    print(f"  -> 保存合并文件: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description='合并 reliability_*.json 文件（按目录）')
    parser.add_argument('dirs', nargs='+', help='要合并的结果目录（例如 ../results/n3_snr4）')
    args = parser.parse_args()

    merged_paths = []
    for d in args.dirs:
        if not os.path.isdir(d):
            print(f"目录不存在: {d}")
            continue
        p = merge_files_in_dir(d)
        if p:
            merged_paths.append(p)

    if merged_paths:
        print('\n合并完成，生成文件:')
        for p in merged_paths:
            print('  -', p)
    else:
        print('\n未生成任何合并文件')


if __name__ == '__main__':
    main()

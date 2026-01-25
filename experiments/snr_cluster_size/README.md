# SNR-集群规模关系实验

## 实验目的
测量在不同 SNR（信噪比）条件下，Raft 集群能够维持的节点规模。

## 目录结构
```
snr_cluster_size/
├── code/                    # 实验代码
│   ├── raft_leader_snr_experiment.py      # Leader 节点 (实验控制)
│   ├── raft_follower_snr_experiment.py    # Follower 节点 (增益自动调整)
│   ├── raft_leader_snr_broadcast.py       # Leader SNR 广播 (基础版)
│   ├── raft_follower_gain_adjust.py       # Follower 增益调整 (基础版)
│   ├── run_snr_experiment.sh              # 启动脚本
│   ├── plot_snr_experiment.py             # 单次实验绘图
│   └── plot_comparison.py                 # 多次实验对比绘图
├── results/                 # 实验数据 (JSON)
│   └── snr_experiment_results_*.json
├── plots/                   # 生成的图表 (PNG)
│   └── snr_experiment_plot_*.png
└── README.md                # 本说明文件
```

## 实验配置
- **6 节点实验**: 4 台 E200 (自动) + 2 台 U200 (手动)
- **4 节点实验**: 4 台 E200 (自动)
- **SNR 范围**: 24 dB → 0 dB (步长: >6dB 时 2.0, ≤6dB 时 0.5)
- **每个 SNR 测量次数**: 100 次
- **节点在线判定**: 2 秒内收到心跳回复

## 关键结果文件
| 文件 | 节点数 | 说明 |
|------|--------|------|
| `snr_experiment_results_20260124_215123.json` | 6 | 最终 6 节点实验 |
| `snr_experiment_results_20260124_230119.json` | 4 | 最终 4 节点实验 |

## 运行方式
```bash
# 从项目根目录运行
cd /home/chuzhitairan/V2V-Raft-SDR
./scripts/run_snr_experiment.sh [LEADER_TX] [LEADER_RX] [FOLLOWER_TX] [FOLLOWER_RX] [START_SNR]
```

## 绘图方式
```bash
# 单次实验绘图
python3 experiments/snr_cluster_size/code/plot_snr_experiment.py experiments/snr_cluster_size/results/<结果文件.json>

# 对比绘图 (需修改 plot_comparison.py 中的文件路径)
python3 experiments/snr_cluster_size/code/plot_comparison.py
```

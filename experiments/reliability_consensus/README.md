# 可靠性共识实验 (Reliability Consensus Experiment)

## 实验目的
评估在不同 **信道质量 (SNR)** 和 **节点可信度 (p_node)** 条件下，Raft 集群的 **系统整体可靠性 (P_sys)**。

## 核心概念

### 自变量
1. **SNR (信道质量)**：`[20.0, 8.0]` dB
   - 高 SNR (20dB): 通信近乎完美
   - 低 SNR (8dB): 存在丢包干扰

2. **p_node (节点可信度)**：`[0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]`
   - 模拟传感器判断正确的概率
   - p_node=0.8 表示 80% 概率投赞成票

3. **n (系统规模)**：`[1, 2, 3, 4, 5, 6]`
   - 软件层面屏蔽节点，统计 ID ≤ n 的投票

### 因变量
1. **P_sys (系统可靠性)**：系统做出正确决策的概率
2. **有效规模 (Effective Scale)**：实际收到投票的节点数

### 判决逻辑 (加权投票)
```
# 加权投票打破偶数节点平局
w_i = 1 + 0.001 * (SNR_i - SNR_min) / (SNR_max - SNR_min)
W_yes = sum(w_i for 赞成票)
W_total = sum(all w_i)

if W_yes > W_total / 2:
    决策正确 (Success)
else:
    决策失败 (Failure)
```

## 目录结构
```
reliability_consensus/
├── code/
│   ├── raft_leader_reliability.py      # Leader 端 (实验控制)
│   ├── raft_follower_reliability.py    # Follower 端 (可信度模拟)
│   ├── plot_reliability.py             # 绘图脚本
│   └── run_reliability_experiment.sh   # 启动脚本
├── results/
│   └── reliability_experiment_results_*.json
├── plots/
│   └── reliability_experiment_plot_*.png
└── README.md
```

## 运行方式

### PC1 (4 台 E200)
```bash
cd /home/chuzhitairan/V2V-Raft-SDR
./experiments/reliability_consensus/code/run_reliability_experiment.sh
```

### PC2 (手动启动 Node 5, 6)
```bash
# Node 5 PHY
python3 core/v2v_hw_phy.py --sdr-args 'addr=...' \
    --tx-port 20005 --rx-port 10005 --ctrl-port 9005 \
    --tx-gain 0.5 --rx-gain 0.9

# Node 5 App
python3 experiments/reliability_consensus/code/raft_follower_reliability.py \
    --id 5 --total 6 --tx 10005 --rx 20005 --ctrl 9005

# Node 6 类似
```

### 开始实验
在 Leader 窗口按 **Enter** 键开始实验。

## 预期耗时
- 2 (SNR) × 8 (p_node) × 6 (n) × 50 轮 × 0.5s ≈ **40 分钟**
- 加上 SNR 切换稳定时间 ≈ **30-35 分钟**

## 绘图
```bash
python3 experiments/reliability_consensus/code/plot_reliability.py \
    experiments/reliability_consensus/results/<结果文件.json>
```

## 预期图表
1. **高 SNR (20dB)**：P_sys vs p_node，6 条曲线
   - n=1 时为直线 (P_sys = p_node)
   - n 增大时曲线呈 S 型（放大高可信度，抑制低可信度）

2. **低 SNR (8dB)**：曲线整体下移
   - 有效规模下降
   - 展示增加节点数量对抗丢包的效果

## 关键代码差异

### Follower 端 (无状态伯努利投票)
```python
# 模拟传感器可信度 - 无日志一致性检查
rand_val = random.random()
if rand_val < self.p_node:
    vote_success = True   # 赞成
else:
    vote_success = False  # 反对 (不是丢包！)

# 无论投票结果如何，都追加日志
self.log.append(entry)
```

### Leader 端 (加权投票)
```python
# 加权投票：SNR 高的节点权重略大
w_i = 1.0 + 0.001 * (snr_i - snr_min) / (snr_max - snr_min)
# Leader 虚拟 SNR = max(Follower SNR) + 2.0 dB

# 软件屏蔽：只统计 ID <= n 的节点
W_yes = sum(w for node_id, w in weights if vote == True and node_id <= n)
W_total = sum(w for node_id, w in weights if node_id <= n)

if W_yes > W_total / 2:
    success = True
```

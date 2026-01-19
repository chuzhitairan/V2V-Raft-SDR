# 三节点硬件实验指南

## 硬件清单

| 设备 | 数量 | 说明 |
|------|------|------|
| 笔记本电脑 | 1 | 运行所有软件 |
| 交换机 | 1 | 千兆交换机推荐 |
| ANTSDR E200 | 3 | AD9361 SDR |
| 网线 | 4 | 笔记本 + 3台E200 |
| 天线 | 6 | 每台E200需要TX/RX各1根 |

## 第一步：硬件连接

```
笔记本 ──网线──┐
              │
E200-1 ──网线──┼── 交换机
E200-2 ──网线──┤
E200-3 ──网线──┘
```

### 天线安装
- 每台 E200 的 **TX1** 和 **RX1** 端口各接一根天线
- 天线间距保持 > 50cm 避免近场耦合
- 如果是室内测试，可用衰减器降低信号强度

## 第二步：网络配置

### 2.1 配置笔记本 IP
```bash
# 查看网口名称
ip link show

# 配置静态 IP (假设网口是 eth0)
sudo ip addr add 192.168.1.100/24 dev eth0
sudo ip link set eth0 up
```

### 2.2 配置 E200 IP
每台 E200 需要配置不同的 IP：

| 设备 | IP 地址 |
|------|---------|
| E200-1 | 192.168.1.10 |
| E200-2 | 192.168.1.11 |
| E200-3 | 192.168.1.12 |

**配置方法**（通过 USB 串口或 SD 卡）：
```bash
# 编辑 E200 的网络配置文件
# /etc/network/interfaces 或 /etc/systemd/network/
```

### 2.3 验证连接
```bash
ping 192.168.1.10  # E200-1
ping 192.168.1.11  # E200-2
ping 192.168.1.12  # E200-3
```

## 第三步：运行实验

### 3.1 一键启动（推荐）
```bash
cd /home/chuzhitairan/V2V-Raft-SDR
chmod +x scripts/run_3node_hw.sh
./scripts/run_3node_hw.sh
```

### 3.2 自定义参数
```bash
# 调整发射功率和 SNR 阈值
./scripts/run_3node_hw.sh --tx-gain 50 --snr-threshold 10
```

### 3.3 手动启动（调试用）

**终端 1-3：PHY 层**
```bash
# PHY 1 (E200-1)
python3 scripts/core/v2v_hw_phy.py --sdr-ip 192.168.1.10 \
    --app-tx-port 10001 --app-rx-port 20001

# PHY 2 (E200-2)
python3 scripts/core/v2v_hw_phy.py --sdr-ip 192.168.1.11 \
    --app-tx-port 10002 --app-rx-port 20002

# PHY 3 (E200-3)
python3 scripts/core/v2v_hw_phy.py --sdr-ip 192.168.1.12 \
    --app-tx-port 10003 --app-rx-port 20003
```

**终端 4-6：Raft 节点**
```bash
# Node 1
python3 scripts/app/raft_node.py --id 1 --total 3 --tx 10001 --rx 20001

# Node 2
python3 scripts/app/raft_node.py --id 2 --total 3 --tx 10002 --rx 20002

# Node 3
python3 scripts/app/raft_node.py --id 3 --total 3 --tx 10003 --rx 20003
```

## 第四步：观察实验结果

### 4.1 Leader 选举
启动后 1.5-3 秒内，应该看到类似输出：
```
🔥 [选举] 发起 Term 1 (Timeout=2.15s)
✅ [投票] 同意 -> 节点 2
🗳️ [得票] 来自节点 1，当前票数: 2/3
👑 [当选] 成为 Leader (Term 1)
```

### 4.2 提交命令
在 Leader 节点窗口按回车：
```
📝 [提交] 新日志 #1: 向左变道
✨ [执行] 共识达成! 执行操作: 向左变道
```

### 4.3 SNR 监控
如果有低 SNR 消息被过滤：
```
🚫 [过滤] 节点 3 SNR=3.2dB < 5.0dB (累计过滤: 1)
```

## 故障排除

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| ping 不通 E200 | IP 配置错误 | 检查 E200 和笔记本的 IP 配置 |
| PHY 启动失败 | GNU Radio 依赖缺失 | `pip install gnuradio` |
| 无法选举 Leader | 丢包严重 | 降低 TX gain 或调整天线位置 |
| 频繁重新选举 | 选举超时太短 | 增大 `election_timeout_min` |
| 全部消息被过滤 | SNR 阈值太高 | 降低 `--snr-threshold` |

## 实验参数建议

| 场景 | TX Gain | SNR 阈值 | 说明 |
|------|---------|----------|------|
| 室内近距离 (<5m) | 40-50 | 10 dB | 避免信号过强 |
| 室内中距离 (5-20m) | 60 | 5 dB | 默认配置 |
| 室外 | 70-80 | 3 dB | 需要更高功率 |

## 日志位置
```
logs/hw_YYYYMMDD_HHMMSS/
├── phy_1.log
├── phy_2.log
└── phy_3.log
```

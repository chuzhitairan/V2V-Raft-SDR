# 硬件操作指南

本文档介绍如何手动启动和运行 V2V-Raft-SDR 系统，支持 ANTSDR E200 和 USRP U200 混合组网。

## 目录

- [硬件识别](#硬件识别)
- [端口规划](#端口规划)
- [手动启动（2节点示例）](#手动启动2节点示例)
- [手动启动（3节点示例）](#手动启动3节点示例)
- [一键启动脚本](#一键启动脚本)
- [E200 vs U200 注意事项](#e200-vs-u200-注意事项)
- [故障排除](#故障排除)

---

## 硬件识别

### 查找连接的 SDR 设备

```bash
uhd_find_devices
```

**输出示例：**

```
--------------------------------------------------
-- UHD Device 0
--------------------------------------------------
Device Address:
    type: b200
    name: ANTSDR-E200
    serial: 
    addr: 192.168.1.10

--------------------------------------------------
-- UHD Device 1
--------------------------------------------------
Device Address:
    type: b200
    name: B200
    serial: 316B611
```

### 设备识别参数

| 设备类型 | 连接方式 | 识别参数格式 | 示例 |
|----------|----------|--------------|------|
| ANTSDR E200 | 以太网 | `addr=<IP>` | `addr=192.168.1.10` |
| USRP U200/B200 | USB | `serial=<序列号>` | `serial=316B611` |
| USRP N200/N210 | 以太网 | `addr=<IP>` | `addr=192.168.10.2` |

---

## 端口规划

### 单节点端口分配

每个节点需要 3 个端口：

| 端口类型 | 用途 | 数据流向 |
|----------|------|----------|
| UDP Recv (App TX) | 应用层发送数据到 PHY | App → PHY |
| UDP Send (App RX) | PHY 发送数据到应用层 | PHY → App |
| Ctrl Port | 运行时增益调整 | 控制脚本 → PHY |

### 多节点端口规划表

| 节点 | 设备 | SDR Args | App TX | App RX | Ctrl |
|------|------|----------|--------|--------|------|
| Node 1 | E200 | `addr=192.168.1.10` | 10001 | 20001 | 9001 |
| Node 2 | E200 | `addr=192.168.1.11` | 10002 | 20002 | 9002 |
| Node 3 | U200 | `serial=316B611` | 10003 | 20003 | 9003 |

---

## 手动启动（2节点示例）

**场景**：1 台电脑 + 1 台 E200 + 1 台 U200

### 步骤 1：识别设备

```bash
uhd_find_devices
```

记录下：
- E200 的 IP 地址（如 `192.168.1.10`）
- U200 的序列号（如 `316B611`）

### 步骤 2：启动 PHY 层

**终端 1 - Node 1 (E200) PHY：**

```bash
python3 scripts/core/v2v_hw_phy.py \
    --sdr-args "addr=192.168.1.10" \
    --udp-recv-port 10001 \
    --udp-send-port 20001 \
    --ctrl-port 9001 \
    --tx-gain 0.5 \
    --rx-gain 0.5
```

**终端 2 - Node 2 (U200) PHY：**

```bash
# 注意：U200 可能需要 sudo 权限
sudo python3 scripts/core/v2v_hw_phy.py \
    --sdr-args "serial=316B611" \
    --udp-recv-port 10002 \
    --udp-send-port 20002 \
    --ctrl-port 9002 \
    --tx-gain 0.5 \
    --rx-gain 0.5
```

> ⚠️ **注意**：U200 通过 USB 初始化需要加载固件，可能需要 5-10 秒，请耐心等待直到看到 GUI 窗口。

### 步骤 3：启动 Raft 应用层

**终端 3 - Node 1 Raft：**

```bash
python3 scripts/app/raft_node.py \
    --id 1 \
    --total 2 \
    --tx 10001 \
    --rx 20001 \
    --snr-threshold 5.0
```

**终端 4 - Node 2 Raft：**

```bash
python3 scripts/app/raft_node.py \
    --id 2 \
    --total 2 \
    --tx 10002 \
    --rx 20002 \
    --snr-threshold 5.0
```

### 步骤 4：验证运行

启动后 1.5-3 秒内，应该看到：

```
🔥 [选举] 发起 Term 1 (Timeout=2.15s)
✅ [投票] 同意 -> 节点 1
👑 [当选] 成为 Leader (Term 1)
```

在 Leader 节点窗口按 **回车** 提交命令：

```
📝 [提交] 新日志 #1: 向左变道
✨ [执行] 共识达成! 执行操作: 向左变道
```

---

## 手动启动（3节点示例）

**场景**：1 台电脑 + 3 台 E200（以太网交换机连接）

### 端口分配

| 节点 | SDR Args | App TX | App RX |
|------|----------|--------|--------|
| Node 1 | `addr=192.168.1.10` | 10001 | 20001 |
| Node 2 | `addr=192.168.1.11` | 10002 | 20002 |
| Node 3 | `addr=192.168.1.12` | 10003 | 20003 |

### 启动命令

**PHY 层（3 个终端）：**

```bash
# 终端 1
python3 scripts/core/v2v_hw_phy.py --sdr-args "addr=192.168.1.10" \
    --udp-recv-port 10001 --udp-send-port 20001

# 终端 2
python3 scripts/core/v2v_hw_phy.py --sdr-args "addr=192.168.1.11" \
    --udp-recv-port 10002 --udp-send-port 20002

# 终端 3
python3 scripts/core/v2v_hw_phy.py --sdr-args "addr=192.168.1.12" \
    --udp-recv-port 10003 --udp-send-port 20003
```

**Raft 应用层（3 个终端）：**

```bash
# 终端 4
python3 scripts/app/raft_node.py --id 1 --total 3 --tx 10001 --rx 20001

# 终端 5
python3 scripts/app/raft_node.py --id 2 --total 3 --tx 10002 --rx 20002

# 终端 6
python3 scripts/app/raft_node.py --id 3 --total 3 --tx 10003 --rx 20003
```

---

## 一键启动脚本

### 3 节点 E200 网络

编辑 `scripts/run_3node_hw.sh` 中的 SDR 配置：

```bash
# 全部 E200 (以太网)
SDR_ARGS=("addr=192.168.1.10" "addr=192.168.1.11" "addr=192.168.1.12")
```

运行：

```bash
./scripts/run_3node_hw.sh
```

### 混合网络（E200 + U200）

```bash
# 混合配置
SDR_ARGS=("addr=192.168.1.10" "addr=192.168.1.11" "serial=316B611")
```

### 自定义参数

```bash
./scripts/run_3node_hw.sh --tx-gain 0.6 --snr-threshold 10
```

---

## E200 vs U200 注意事项

### 1. 采样率限制

| 设备 | 接口 | 最大采样率 | 推荐采样率 |
|------|------|------------|------------|
| E200 | 千兆以太网 | 20 MHz | 5-10 MHz |
| U200 | USB 3.0 | 10 MHz | 5 MHz |
| U200 | USB 2.0 | ~4 MHz | ⚠️ 不推荐 |

> ⚠️ **重要**：`v2v_hw_phy.py` 默认使用 5 MHz 采样率，适合所有设备。如果使用 USB 2.0 连接 U200，可能会出现 `O` (Overflow) 错误导致丢包。

### 2. 增益差异

| 设备 | 芯片 | TX 增益范围 | RX 增益范围 |
|------|------|-------------|-------------|
| E200 | AD9361 | 0-89.75 dB | 0-76 dB |
| U200 | WBX/SBX | 0-31.5 dB | 0-31.5 dB |

代码使用 `set_normalized_gain(0.0-1.0)`，UHD 会自动映射到硬件支持的范围。

**建议**：
- 如果通信不稳定，使用 `full_auto_benchmark.py` 分别测试每台设备的最佳增益点
- E200 推荐: TX 0.6-0.8, RX 0.5-0.7
- U200 推荐: TX 0.7-0.9, RX 0.6-0.8

### 3. USB 权限

U200/B200 需要 USB 访问权限。

**方法 1：使用 sudo**

```bash
sudo python3 scripts/core/v2v_hw_phy.py --sdr-args "serial=316B611" ...
```

**方法 2：配置 udev 规则（推荐）**

```bash
# 创建规则文件
sudo tee /etc/udev/rules.d/uhd-usrp.rules << EOF
# USRP B200/B210/U200
SUBSYSTEM=="usb", ATTR{idVendor}=="2500", ATTR{idProduct}=="0020", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="2500", ATTR{idProduct}=="0021", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="2500", ATTR{idProduct}=="0022", MODE="0666"
EOF

# 重新加载规则
sudo udevadm control --reload-rules
sudo udevadm trigger
```

配置后无需 sudo 即可访问 USB SDR。

### 4. 初始化时间

| 设备 | 初始化时间 |
|------|------------|
| E200 | 1-2 秒 |
| U200 | 5-10 秒（需加载固件到 FPGA）|

启动脚本中已设置 2 秒间隔，如果使用 U200 可能需要增加等待时间。

---

## 故障排除

### 问题 1：`uhd_find_devices` 找不到设备

| 可能原因 | 解决方案 |
|----------|----------|
| E200 IP 配置错误 | 检查 E200 的 IP 和笔记本在同一网段 |
| U200 USB 未连接好 | 重新插拔 USB，优先使用 USB 3.0 口 |
| 驱动未安装 | `sudo apt install uhd-host libuhd-dev` |

### 问题 2：Overflow (`O`) 错误

```
OOOOOOOOOOOOO
```

| 可能原因 | 解决方案 |
|----------|----------|
| USB 带宽不足 | 降低采样率或使用 USB 3.0 |
| CPU 负载过高 | 关闭其他程序 |
| 采样率过高 | 将 `samp_rate` 降至 5e6 |

### 问题 3：频繁选举超时

| 可能原因 | 解决方案 |
|----------|----------|
| 丢包率过高 | 降低 TX gain，检查天线 |
| SNR 阈值过高 | 降低 `--snr-threshold` |
| 增益设置不当 | 使用 benchmark 工具找最佳增益 |

### 问题 4：Permission denied (USB)

```
Error: usb open failed: LIBUSB_ERROR_ACCESS
```

解决：配置 udev 规则（见上文）或使用 `sudo` 运行。

---

## 快速参考

### PHY 层命令

```bash
python3 scripts/core/v2v_hw_phy.py \
    --sdr-args "addr=192.168.1.10"  # 或 "serial=316B611"
    --udp-recv-port 10001           # 接收来自 App 的数据
    --udp-send-port 20001           # 发送数据到 App
    --ctrl-port 9001                # 控制端口
    --tx-gain 0.5                  # 发射增益 (0.0-1.0)
    --rx-gain 0.5                  # 接收增益 (0.0-1.0)
```

### Raft 应用层命令

```bash
python3 scripts/app/raft_node.py \
    --id 1                          # 节点 ID
    --total 3                       # 集群总节点数
    --tx 10001                      # 发送端口 (对应 PHY 的 recv)
    --rx 20001                      # 接收端口 (对应 PHY 的 send)
    --snr-threshold 5.0             # SNR 过滤阈值 (dB)
```

### 运行时增益调整

```bash
# 调整 TX 增益
echo '{"cmd":"set_tx_gain","value":0.6}' | nc -u 127.0.0.1 9001

# 调整 RX 增益
echo '{"cmd":"set_rx_gain","value":0.5}' | nc -u 127.0.0.1 9001

# 查询当前增益
echo '{"cmd":"get_gains"}' | nc -u -w1 127.0.0.1 9001
```

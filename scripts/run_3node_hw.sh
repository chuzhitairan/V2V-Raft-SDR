#!/bin/bash
# ==============================================
# 三节点硬件实验启动脚本
# ==============================================
# 硬件要求:
#   - 1 台笔记本 (运行本脚本)
#   - 1 个交换机
#   - 3 台 ANTSDR E200
#
# 网络配置:
#   笔记本: 192.168.1.100
#   E200-1: 192.168.1.10
#   E200-2: 192.168.1.11
#   E200-3: 192.168.1.12
# ==============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# SDR 配置
# E200 (以太网): addr=192.168.1.10
# U200 (USB): serial=316B611
SDR_ARGS=("addr=192.168.1.10" "addr=192.168.1.11" "addr=192.168.1.12")
TX_GAIN=60
RX_GAIN=40
FREQ=5.89e9        # 5.89 GHz (802.11p)
SNR_THRESHOLD=5.0  # 邻居筛选阈值 (dB)

# 端口配置 (每个节点独立端口)
# PHY -> App (RX)
APP_RX_PORTS=(20001 20002 20003)
# App -> PHY (TX)
APP_TX_PORTS=(10001 10002 10003)

# 工作目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs/hw_$(date +%Y%m%d_%H%M%S)"

mkdir -p "$LOG_DIR"

# ==============================================
# 函数定义
# ==============================================

check_network() {
    echo -e "${BLUE}[1/4] 检查 SDR 连接...${NC}"
    for i in 0 1 2; do
        args="${SDR_ARGS[$i]}"
        echo -n "  SDR-$((i+1)) ($args): "
        
        # 检查是否为以太网设备 (addr=)
        if [[ "$args" == addr=* ]]; then
            ip="${args#addr=}"
            if ping -c 1 -W 1 "$ip" &> /dev/null; then
                echo -e "${GREEN}✓ 在线 (Ethernet)${NC}"
            else
                echo -e "${RED}✗ 离线${NC}"
                echo -e "${RED}错误: SDR-$((i+1)) 无法连接，请检查网络配置${NC}"
                exit 1
            fi
        # USB 设备 (serial=) 使用 uhd_find_devices 检查
        elif [[ "$args" == serial=* ]]; then
            serial="${args#serial=}"
            if uhd_find_devices --args="$args" 2>/dev/null | grep -q "Device Address"; then
                echo -e "${GREEN}✓ 在线 (USB)${NC}"
            else
                echo -e "${RED}✗ 未找到${NC}"
                echo -e "${RED}错误: SDR-$((i+1)) 无法找到，请检查 USB 连接${NC}"
                exit 1
            fi
        else
            echo -e "${YELLOW}跳过检查 (未知类型)${NC}"
        fi
    done
}

start_phy_layers() {
    echo -e "${BLUE}[2/4] 启动 PHY 层 (GNU Radio)...${NC}"
    
    for i in 0 1 2; do
        node_id=$((i+1))
        sdr_args="${SDR_ARGS[$i]}"
        app_tx="${APP_TX_PORTS[$i]}"
        app_rx="${APP_RX_PORTS[$i]}"
        
        echo -e "  启动 PHY-$node_id (SDR: $sdr_args, 端口: $app_tx/$app_rx)"
        
        python3 "$PROJECT_DIR/scripts/core/v2v_hw_phy.py" \
            --sdr-args "$sdr_args" \
            --tx-gain "$TX_GAIN" \
            --rx-gain "$RX_GAIN" \
            --udp-recv-port "$app_tx" \
            --udp-send-port "$app_rx" \
            > "$LOG_DIR/phy_$node_id.log" 2>&1 &
        
        PHY_PIDS+=($!)
        sleep 2  # 等待 GNU Radio 初始化
    done
    
    echo -e "${GREEN}  PHY 层已启动 (PIDs: ${PHY_PIDS[*]})${NC}"
}

start_raft_nodes() {
    echo -e "${BLUE}[3/4] 启动 Raft 节点...${NC}"
    
    for i in 0 1 2; do
        node_id=$((i+1))
        tx_port="${APP_TX_PORTS[$i]}"
        rx_port="${APP_RX_PORTS[$i]}"
        
        echo -e "  启动 Raft 节点 $node_id (TX:$tx_port, RX:$rx_port, SNR阈值:${SNR_THRESHOLD}dB)"
        
        # 使用 xterm 打开独立终端显示每个节点
        xterm -title "Raft Node $node_id" -e \
            "python3 $PROJECT_DIR/scripts/app/raft_node.py \
                --id $node_id \
                --total 3 \
                --tx $tx_port \
                --rx $rx_port \
                --snr-threshold $SNR_THRESHOLD; \
             echo '按回车退出...'; read" &
        
        RAFT_PIDS+=($!)
        sleep 0.5
    done
    
    echo -e "${GREEN}  Raft 节点已启动 (PIDs: ${RAFT_PIDS[*]})${NC}"
}

show_status() {
    echo -e "${BLUE}[4/4] 实验状态${NC}"
    echo "=============================================="
    echo -e "  日志目录: ${YELLOW}$LOG_DIR${NC}"
    echo "  PHY 层:"
    for i in 0 1 2; do
        echo "    Node $((i+1)): SDR=${SDR_ARGS[$i]}, Port=${APP_TX_PORTS[$i]}/${APP_RX_PORTS[$i]}"
    done
    echo "  Raft 参数:"
    echo "    选举超时: 1.5-3.0s"
    echo "    心跳间隔: 0.15s"
    echo "    SNR 阈值: ${SNR_THRESHOLD} dB"
    echo "=============================================="
    echo -e "${GREEN}实验已启动！${NC}"
    echo ""
    echo "操作说明:"
    echo "  - 在任意 Raft 节点窗口按回车可提交变道指令"
    echo "  - 观察 Leader 选举和日志复制过程"
    echo "  - 按 Ctrl+C 停止所有进程"
}

cleanup() {
    echo -e "\n${YELLOW}正在停止所有进程...${NC}"
    
    # 停止 Raft 节点
    for pid in "${RAFT_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    
    # 停止 PHY 层
    for pid in "${PHY_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    
    # 清理所有相关进程
    pkill -f "v2v_hw_phy.py" 2>/dev/null || true
    pkill -f "raft_node.py" 2>/dev/null || true
    
    echo -e "${GREEN}已停止所有进程${NC}"
    echo -e "日志保存在: $LOG_DIR"
}

# ==============================================
# 主流程
# ==============================================

PHY_PIDS=()
RAFT_PIDS=()

trap cleanup EXIT INT TERM

echo "=============================================="
echo -e "${GREEN}V2V-Raft 三节点硬件实验${NC}"
echo "=============================================="

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --tx-gain)
            TX_GAIN="$2"
            shift 2
            ;;
        --rx-gain)
            RX_GAIN="$2"
            shift 2
            ;;
        --snr-threshold)
            SNR_THRESHOLD="$2"
            shift 2
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  --tx-gain <值>       设置发射增益 (默认: 60)"
            echo "  --rx-gain <值>       设置接收增益 (默认: 40)"
            echo "  --snr-threshold <值> 设置 SNR 阈值 (默认: 5.0)"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            exit 1
            ;;
    esac
done

check_network
start_phy_layers
start_raft_nodes
show_status

# 等待用户中断
echo "按 Ctrl+C 停止实验..."
wait

#!/bin/bash
# ==============================================
# 六节点硬件实验启动脚本
# ==============================================
# 硬件配置:
#   - 1 台笔记本 (运行本脚本)
#   - 4 台 ANTSDR E200 (以太网)
#   - 2 台 USRP U200 (USB)
#
# 设备标识:
#   E200: 192.168.1.10 ~ 192.168.1.13
#   U200: U200100, U200101
# ==============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==============================================
# SDR 配置 (6 节点)
# ==============================================
SDR_ARGS=(
    "addr=192.168.1.10"    # Node 1 - E200
    "addr=192.168.1.11"    # Node 2 - E200
    "addr=192.168.1.12"    # Node 3 - E200
    "addr=192.168.1.13"    # Node 4 - E200
    "serial=U200100"       # Node 5 - U200
    "serial=U200101"       # Node 6 - U200
)

TOTAL_NODES=${#SDR_ARGS[@]}

# 增益配置
TX_GAIN=0.75
RX_GAIN=0.75
SNR_THRESHOLD=5.0  # 邻居筛选阈值 (dB)

# 端口配置 (每个节点独立端口)
APP_TX_PORTS=(10001 10002 10003 10004 10005 10006)
APP_RX_PORTS=(20001 20002 20003 20004 20005 20006)
CTRL_PORTS=(9001 9002 9003 9004 9005 9006)

# 工作目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs/hw_$(date +%Y%m%d_%H%M%S)"

mkdir -p "$LOG_DIR"

# ==============================================
# 函数定义
# ==============================================

check_devices() {
    echo -e "${BLUE}[1/4] 检查 SDR 设备连接...${NC}"
    local failed=0
    
    for i in $(seq 0 $((TOTAL_NODES-1))); do
        args="${SDR_ARGS[$i]}"
        echo -n "  Node $((i+1)) ($args): "
        
        # 检查是否为以太网设备 (addr=)
        if [[ "$args" == addr=* ]]; then
            ip="${args#addr=}"
            if ping -c 1 -W 1 "$ip" &> /dev/null; then
                echo -e "${GREEN}✓ 在线 (Ethernet)${NC}"
            else
                echo -e "${RED}✗ 离线${NC}"
                failed=1
            fi
        # USB 设备 (serial=) 使用 uhd_find_devices 检查
        elif [[ "$args" == serial=* ]]; then
            if uhd_find_devices --args="$args" 2>/dev/null | grep -q "Device Address"; then
                echo -e "${GREEN}✓ 在线 (USB)${NC}"
            else
                echo -e "${RED}✗ 未找到${NC}"
                failed=1
            fi
        else
            echo -e "${YELLOW}⚠ 跳过检查${NC}"
        fi
    done
    
    if [[ $failed -eq 1 ]]; then
        echo -e "${RED}错误: 部分设备未连接，请检查后重试${NC}"
        exit 1
    fi
}

start_phy_layers() {
    echo -e "${BLUE}[2/4] 启动 PHY 层 (GNU Radio)...${NC}"
    
    for i in $(seq 0 $((TOTAL_NODES-1))); do
        node_id=$((i+1))
        sdr_args="${SDR_ARGS[$i]}"
        app_tx="${APP_TX_PORTS[$i]}"
        app_rx="${APP_RX_PORTS[$i]}"
        ctrl="${CTRL_PORTS[$i]}"
        
        echo -e "  启动 PHY-$node_id (SDR: $sdr_args)"
        
        python3 "$PROJECT_DIR/scripts/core/v2v_hw_phy.py" \
            --sdr-args "$sdr_args" \
            --tx-gain "$TX_GAIN" \
            --rx-gain "$RX_GAIN" \
            --udp-recv-port "$app_tx" \
            --udp-send-port "$app_rx" \
            --ctrl-port "$ctrl" \
            --no-gui \
            > "$LOG_DIR/phy_$node_id.log" 2>&1 &
        
        PHY_PIDS+=($!)
        
        # U200 需要更长的初始化时间
        if [[ "$sdr_args" == serial=* ]]; then
            echo -e "    ${YELLOW}(U200 固件加载中，等待 5 秒...)${NC}"
            sleep 5
        else
            sleep 2
        fi
    done
    
    echo -e "${GREEN}  PHY 层已启动 (${#PHY_PIDS[@]} 个进程)${NC}"
}

start_raft_nodes() {
    echo -e "${BLUE}[3/4] 启动 Raft 节点...${NC}"
    
    # 屏幕布局: 3列 x 2行
    # 获取屏幕分辨率 (默认 1920x1080)
    SCREEN_W=$(xdpyinfo 2>/dev/null | grep dimensions | awk '{print $2}' | cut -d'x' -f1)
    SCREEN_H=$(xdpyinfo 2>/dev/null | grep dimensions | awk '{print $2}' | cut -d'x' -f2)
    SCREEN_W=${SCREEN_W:-1920}
    SCREEN_H=${SCREEN_H:-1080}
    
    # 计算每个窗口的位置
    COLS=3
    ROWS=2
    WIN_W=$((SCREEN_W / COLS))
    WIN_H=$((SCREEN_H / ROWS - 30))  # 减去标题栏高度
    
    for i in $(seq 0 $((TOTAL_NODES-1))); do
        node_id=$((i+1))
        tx_port="${APP_TX_PORTS[$i]}"
        rx_port="${APP_RX_PORTS[$i]}"
        
        # 计算窗口位置 (3列 x 2行 网格)
        col=$((i % COLS))
        row=$((i / COLS))
        pos_x=$((col * WIN_W))
        pos_y=$((row * (WIN_H + 30)))
        
        echo -e "  启动 Raft 节点 $node_id (TX:$tx_port, RX:$rx_port) @ 位置 ($col,$row)"
        
        # 使用 xterm 打开独立终端显示每个节点 (自动排列)
        xterm -title "Raft Node $node_id" \
            -geometry 60x20+${pos_x}+${pos_y} \
            -fa 'Monospace' -fs 12 \
            -e \
            "python3 $PROJECT_DIR/scripts/app/raft_node.py \
                --id $node_id \
                --total $TOTAL_NODES \
                --tx $tx_port \
                --rx $rx_port \
                --snr-threshold $SNR_THRESHOLD; \
             echo '按回车退出...'; read" &
        
        RAFT_PIDS+=($!)
        sleep 0.3
    done
    
    echo -e "${GREEN}  Raft 节点已启动 (${#RAFT_PIDS[@]} 个终端)${NC}"
}

show_status() {
    echo -e "${BLUE}[4/4] 实验状态${NC}"
    echo "=============================================="
    echo -e "  节点数量: ${GREEN}$TOTAL_NODES${NC}"
    echo -e "  日志目录: ${YELLOW}$LOG_DIR${NC}"
    echo ""
    echo "  节点配置:"
    echo "  ┌──────┬─────────────────────┬───────────┬───────────┐"
    echo "  │ Node │ SDR Args            │ App Ports │ Ctrl Port │"
    echo "  ├──────┼─────────────────────┼───────────┼───────────┤"
    for i in $(seq 0 $((TOTAL_NODES-1))); do
        printf "  │ %4d │ %-19s │ %5d/%5d │ %9d │\n" \
            $((i+1)) "${SDR_ARGS[$i]}" "${APP_TX_PORTS[$i]}" "${APP_RX_PORTS[$i]}" "${CTRL_PORTS[$i]}"
    done
    echo "  └──────┴─────────────────────┴───────────┴───────────┘"
    echo ""
    echo "  Raft 参数:"
    echo "    选举超时: 1.5-3.0s"
    echo "    心跳间隔: 0.15s"
    echo "    SNR 阈值: ${SNR_THRESHOLD} dB"
    echo "    多数派要求: $((TOTAL_NODES/2+1))/$TOTAL_NODES"
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
echo -e "${GREEN}V2V-Raft 六节点硬件实验${NC}"
echo "=============================================="
echo "  E200 x4: 192.168.1.10 ~ 192.168.1.13"
echo "  U200 x2: U200100, U200101"
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
        --skip-check)
            SKIP_CHECK=1
            shift
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  --tx-gain <值>       设置发射增益 (默认: 0.75)"
            echo "  --rx-gain <值>       设置接收增益 (默认: 0.75)"
            echo "  --snr-threshold <值> 设置 SNR 阈值 (默认: 5.0)"
            echo "  --skip-check         跳过设备连接检查"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$SKIP_CHECK" ]]; then
    check_devices
fi

start_phy_layers
start_raft_nodes
show_status

# 等待用户中断
echo "按 Ctrl+C 停止实验..."
wait

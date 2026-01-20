#!/bin/bash
# ============================================
# 固定领导者 6 节点硬件实验 (串行启动版)
# Node 1 = Leader, Node 2-6 = Follower
# 
# 启动顺序: 先逐个启动所有 PHY，再逐个启动 APP
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# SDR 配置
SDR_ARGS=(
    "addr=192.168.1.10"   # Node 1 (Leader) - E200
    "addr=192.168.1.11"   # Node 2 - E200
    "addr=192.168.1.12"   # Node 3 - E200
    "addr=192.168.1.13"   # Node 4 - E200
    "serial=U200100"      # Node 5 - U200
    "serial=U200101"      # Node 6 - U200
)

# 增益配置
TX_GAIN=0.7
RX_GAIN=0.7

# 端口配置
APP_TX_PORTS=(10001 10002 10003 10004 10005 10006)
APP_RX_PORTS=(20001 20002 20003 20004 20005 20006)
CTRL_PORTS=(9001 9002 9003 9004 9005 9006)

# 节点数
TOTAL_NODES=6
LEADER_ID=1

# 窗口布局 (3x2)
get_screen_size() {
    if command -v xdpyinfo &> /dev/null; then
        xdpyinfo | grep dimensions | awk '{print $2}'
    else
        echo "1920x1080"
    fi
}

SCREEN_SIZE=$(get_screen_size)
SCREEN_W=$(echo $SCREEN_SIZE | cut -d'x' -f1)
SCREEN_H=$(echo $SCREEN_SIZE | cut -d'x' -f2)
COLS=3
ROWS=2

# 像素位置 (用于 +x+y)
WIN_W_PX=$((SCREEN_W / COLS))
WIN_H_PX=$((SCREEN_H / ROWS - 30))  # 减去标题栏高度

# xterm geometry 用字符数 (大约 8px/字符宽, 16px/字符高)
WIN_COLS=$((WIN_W_PX / 8 - 2))
WIN_ROWS=$((WIN_H_PX / 16 - 2))

# 检查控制端口是否响应
check_phy_ready() {
    local port=$1
    local timeout=30
    local count=0
    
    while [ $count -lt $timeout ]; do
        # 发送 ping 命令检查 PHY 是否就绪
        response=$(echo '{"cmd":"ping"}' | timeout 1 nc -u -w1 127.0.0.1 $port 2>/dev/null)
        if [[ "$response" == *"pong"* ]]; then
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

cleanup() {
    echo ""
    echo "🛑 停止所有进程..."
    pkill -f "v2v_hw_phy.py" 2>/dev/null
    pkill -f "raft_fixed_leader.py" 2>/dev/null
    sleep 2
    echo "✅ 清理完成"
}

trap cleanup EXIT INT TERM

echo "============================================"
echo "固定领导者 6 节点硬件实验 (串行启动)"
echo "============================================"
echo "Leader: Node $LEADER_ID"
echo "Follower: Node 2-6"
echo "TX/RX 增益: $TX_GAIN / $RX_GAIN"
echo "============================================"
echo ""

# 清理旧进程
pkill -f "v2v_hw_phy.py" 2>/dev/null
pkill -f "raft_fixed_leader.py" 2>/dev/null
sleep 2

# ============================================
# 第一阶段: 逐个启动 PHY 层
# ============================================
echo "📡 第一阶段: 启动 PHY 层"
echo "--------------------------------------------"

PHY_PIDS=()
READY_NODES=()

for i in $(seq 1 $TOTAL_NODES); do
    idx=$((i - 1))
    sdr_args="${SDR_ARGS[$idx]}"
    tx_port="${APP_TX_PORTS[$idx]}"
    rx_port="${APP_RX_PORTS[$idx]}"
    ctrl_port="${CTRL_PORTS[$idx]}"
    
    echo -n "   Node $i ($sdr_args): "
    
    # 启动 PHY
    python3 "$PROJECT_DIR/scripts/core/v2v_hw_phy.py" \
        --sdr-args "$sdr_args" \
        --tx-gain $TX_GAIN \
        --rx-gain $RX_GAIN \
        --udp-recv-port $tx_port \
        --udp-send-port $rx_port \
        --ctrl-port $ctrl_port \
        --no-gui &
    PHY_PID=$!
    PHY_PIDS+=($PHY_PID)
    
    # 等待 PHY 就绪 (通过控制端口检测)
    sleep 5  # 先等基本初始化
    
    if check_phy_ready $ctrl_port; then
        echo "✓ (PID: $PHY_PID)"
        READY_NODES+=($i)
    else
        echo "❌ (超时)"
    fi
    
    # E200 之间间隔久一点
    if [[ "$sdr_args" == addr=* ]]; then
        sleep 2
    fi
done

echo ""
echo "   就绪节点: ${READY_NODES[*]}"
echo ""

if [ ${#READY_NODES[@]} -lt 2 ]; then
    echo "❌ 就绪节点不足 2 个，无法继续"
    exit 1
fi

# ============================================
# 第二阶段: 启动应用层 (xterm 窗口)
# ============================================
echo "🚀 第二阶段: 启动应用层"
echo "--------------------------------------------"

for i in "${READY_NODES[@]}"; do
    idx=$((i - 1))
    tx_port="${APP_TX_PORTS[$idx]}"
    rx_port="${APP_RX_PORTS[$idx]}"
    
    # 确定角色
    if [ $i -eq $LEADER_ID ]; then
        role="leader"
        title="Node $i [LEADER]"
        color="yellow"
    else
        role="follower"
        title="Node $i [Follower]"
        color="white"
    fi
    
    # 计算窗口位置 (像素)
    col=$(( (i - 1) % COLS ))
    row=$(( (i - 1) / COLS ))
    x=$((col * WIN_W_PX))
    y=$((row * (WIN_H_PX + 30)))  # 加回标题栏高度用于定位
    
    echo "   启动 $title"
    
    # 启动 xterm (字符数x行数+像素位置)
    xterm -bg black -fg $color -title "$title" \
        -geometry ${WIN_COLS}x${WIN_ROWS}+${x}+${y} \
        -e bash -c "
            echo '=== $title ==='
            echo 'PHY 已就绪，启动应用层...'
            python3 $PROJECT_DIR/scripts/app/raft_fixed_leader.py \
                --id $i \
                --role $role \
                --total $TOTAL_NODES \
                --tx $tx_port \
                --rx $rx_port \
                --leader-id $LEADER_ID
            echo '应用层已停止，按回车关闭窗口...'
            read
        " &
    
    sleep 0.5
done

echo ""
echo "============================================"
echo "所有节点已启动！"
echo ""
echo "操作说明:"
echo "  - 在 Leader 窗口 (Node $LEADER_ID) 按回车发送共识请求"
echo "  - 输入自定义命令后按回车也可提交"
echo "  - 按 Ctrl+C 停止所有节点"
echo "============================================"
echo ""
echo "按 Ctrl+C 退出..."

# 等待用户中断
wait

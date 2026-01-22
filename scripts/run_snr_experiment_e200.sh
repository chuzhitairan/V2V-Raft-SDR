#!/bin/bash
# ============================================================================
# SNR-集群规模关系实验启动脚本
# ============================================================================
# 
# 在 PC1 上启动 4 台 E200 (1 个 Leader + 3 个 Follower)
#
# 使用方法:
#   chmod +x run_snr_experiment_e200.sh
#   ./run_snr_experiment_e200.sh
#
# 停止方法:
#   killall python3
#   killall xterm
#
# 实验说明:
#   - Leader 从目标 SNR=20dB 开始，每次降低 2dB
#   - 在每个 SNR 等级进行 100 次集群规模测量
#   - 结果保存到 snr_experiment_results_<timestamp>.json
#   - 当平均集群规模降到 1 时实验结束
#
# ============================================================================

# 脚本目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_DIR="$SCRIPT_DIR/app"
CORE_DIR="$SCRIPT_DIR/core"

echo "=============================================="
echo "  SNR-集群规模关系实验"
echo "=============================================="
echo ""
echo "  4 台 ANTSDR E200 (PC1)"
echo "  - Node 1: Leader (实验控制)"
echo "  - Node 2-4: Follower (增益自动调整)"
echo ""
echo "  实验参数:"
echo "  - 起始目标 SNR: 20 dB"
echo "  - SNR 递减步长: 2 dB"
echo "  - 每 SNR 测量次数: 100"
echo "  - 稳定等待时间: 10 秒"
echo "=============================================="
echo ""

# 端口配置
TX_PORTS=(10001 10002 10003 10004)
RX_PORTS=(20001 20002 20003 20004)
CTRL_PORTS=(9001 9002 9003 9004)

# E200 设备地址
E200_ADDRS=("192.168.1.10" "192.168.1.11" "192.168.1.12" "192.168.1.13")

# 增益配置
RX_GAIN=0.8
TX_GAIN=0.6
INIT_TX_GAIN=0.7  # Follower 初始 TX 增益

# 窗口位置
WIN_X=(50 700 50 700)
WIN_Y=(50 50 450 450)

# 颜色配置
COLORS=("red" "green" "blue" "yellow")

# 检查 PHY 层是否就绪
check_phy_ready() {
    local port=$1
    local timeout=30
    local count=0
    
    while [ $count -lt $timeout ]; do
        response=$(echo '{"cmd":"ping"}' | timeout 1 nc -u -w1 127.0.0.1 $port 2>/dev/null)
        if [[ "$response" == *"pong"* ]]; then
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

# 启动 PHY 层 (后台运行，不用 xterm)
start_phy() {
    local node_id=$1
    local addr=$2
    local tx_port=$3
    local rx_port=$4
    local ctrl_port=$5
    
    echo "🔧 启动 PHY Node $node_id (E200: $addr)..."
    
    python3 $CORE_DIR/v2v_hw_phy.py \
        --sdr-args "addr=$addr" \
        --udp-recv-port $tx_port \
        --udp-send-port $rx_port \
        --ctrl-port $ctrl_port \
        --rx-gain $RX_GAIN --tx-gain $TX_GAIN \
        --no-gui &
    
    echo "   等待 PHY Node $node_id 就绪..."
    if check_phy_ready $ctrl_port; then
        echo "   ✅ PHY Node $node_id 就绪"
    else
        echo "   ❌ PHY Node $node_id 启动超时"
    fi
}

# 启动 Leader
start_leader() {
    local x_pos=$1
    local y_pos=$2
    
    echo "👑 启动实验 Leader (Node 1)..."
    
    # Leader 窗口位置在 PHY 窗口下方
    local leader_y=$((y_pos + 400))
    
    xterm -fa 'Monospace' -fs 14 -bg black -fg white \
          -geometry 100x25+${x_pos}+${leader_y} \
          -title "🔬 EXPERIMENT LEADER (Node 1)" \
          -e "cd $APP_DIR && python3 raft_leader_snr_experiment.py \
              --id 1 --total 6 \
              --tx ${TX_PORTS[0]} --rx ${RX_PORTS[0]} --ctrl ${CTRL_PORTS[0]} \
              --heartbeat-interval 0.2 \
              --snr-broadcast-interval 0.5 \
              --start-snr 20.0 \
              --snr-step 2.0 \
              --measurements 100 \
              --stabilize-time 10.0; bash" &
}

# 启动 Follower
start_follower() {
    local node_id=$1
    local idx=$((node_id - 1))
    local x_pos=$2
    local y_pos=$3
    local color=$4
    
    echo "📡 启动实验 Follower (Node $node_id)..."
    
    # Follower 窗口位置在 PHY 窗口下方
    local follower_y=$((y_pos + 400))
    
    xterm -fa 'Monospace' -fs 14 -bg black -fg $color \
          -geometry 80x20+${x_pos}+${follower_y} \
          -title "🔬 EXPERIMENT FOLLOWER (Node $node_id)" \
          -e "cd $APP_DIR && python3 raft_follower_snr_experiment.py \
              --id $node_id --total 6 \
              --tx ${TX_PORTS[$idx]} --rx ${RX_PORTS[$idx]} --ctrl ${CTRL_PORTS[$idx]} \
              --leader-id 1 \
              --init-gain $INIT_TX_GAIN \
              --status-interval 2.0; bash" &
}

# 主流程
main() {
    # 清理旧进程
    echo "🧹 清理旧进程..."
    pkill -f "v2v_hw_phy.py" 2>/dev/null
    pkill -f "raft_leader_snr_experiment.py" 2>/dev/null
    pkill -f "raft_follower_snr_experiment.py" 2>/dev/null
    sleep 2
    
    echo ""
    echo "📡 启动所有 PHY 层..."
    echo ""
    
    for i in 0 1 2 3; do
        node_id=$((i + 1))
        start_phy $node_id ${E200_ADDRS[$i]} ${TX_PORTS[$i]} ${RX_PORTS[$i]} ${CTRL_PORTS[$i]}
    done
    
    echo ""
    echo "✅ 所有 PHY 层已就绪"
    echo ""
    echo "🚀 启动应用层..."
    echo ""
    
    # 启动 Leader (Node 1)
    start_leader ${WIN_X[0]} ${WIN_Y[0]}
    sleep 2
    
    # 启动 Followers (Node 2, 3, 4)
    for i in 1 2 3; do
        node_id=$((i + 1))
        start_follower $node_id ${WIN_X[$i]} ${WIN_Y[$i]} ${COLORS[$i]}
        sleep 1
    done
    
    echo ""
    echo "=============================================="
    echo "  ✅ PC1 实验节点启动完成!"
    echo "=============================================="
    echo ""
    echo "  📊 Leader 窗口会显示观测到的 SNR"
    echo "  📊 按回车开始 SNR-集群规模实验"
    echo ""
    echo "  ⚠️  可选: 在 PC2 手动启动 U200 节点"
    echo ""
    echo "  停止命令: killall python3 && killall xterm"
    echo "=============================================="
    echo ""
    
    # 等待
    wait
}

# 清理函数
cleanup() {
    echo ""
    echo "🛑 停止所有进程..."
    pkill -f "v2v_hw_phy.py" 2>/dev/null
    pkill -f "raft_leader_snr_experiment.py" 2>/dev/null
    pkill -f "raft_follower_snr_experiment.py" 2>/dev/null
    pkill -f "xterm" 2>/dev/null
    sleep 1
    echo "✅ 清理完成"
}

trap cleanup EXIT INT TERM

main

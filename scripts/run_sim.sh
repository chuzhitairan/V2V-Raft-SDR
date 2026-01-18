#!/bin/bash
# ============================================
# V2V-Raft-SDR 仿真测试启动脚本
# ============================================
# 用法: ./scripts/run_sim.sh [节点数量]
# 示例: ./scripts/run_sim.sh 3   # 启动 3 节点集群
# ============================================

NODES=${1:-3}  # 默认 3 节点
BASE_PORT=50000

echo "============================================"
echo "🚀 V2V-Raft-SDR 仿真测试"
echo "============================================"
echo "节点数量: $NODES"
echo "Hub 端口: $BASE_PORT"
echo "============================================"
echo ""

# 检查 tmux 是否安装
if ! command -v tmux &> /dev/null; then
    echo "❌ 需要安装 tmux: sudo apt install tmux"
    exit 1
fi

# 杀掉旧的会话
tmux kill-session -t raft_sim 2>/dev/null

# 创建新的 tmux 会话
tmux new-session -d -s raft_sim -n hub

# 窗口 0: 启动 Hub
tmux send-keys -t raft_sim:hub "cd $(pwd) && python3 scripts/core/sim_hub_lite.py --nodes $NODES -v" C-m

# 等待 Hub 启动
sleep 1

# 为每个节点创建窗口
for i in $(seq 1 $NODES); do
    RX_PORT=$((BASE_PORT + i))
    tmux new-window -t raft_sim -n "node$i"
    tmux send-keys -t raft_sim:node$i "cd $(pwd) && python3 scripts/app/raft_node.py --id $i --total $NODES --tx $BASE_PORT --rx $RX_PORT" C-m
done

echo "✅ 已在 tmux 会话中启动 $NODES 节点集群"
echo ""
echo "操作指南:"
echo "  tmux attach -t raft_sim    # 进入会话"
echo "  Ctrl+B 然后 N              # 切换到下一个窗口"
echo "  Ctrl+B 然后 P              # 切换到上一个窗口"
echo "  Ctrl+B 然后 数字键         # 跳转到指定窗口 (0=Hub, 1-N=节点)"
echo "  在 Leader 窗口按 Enter     # 提交变道指令"
echo "  Ctrl+B 然后 D              # 退出会话 (后台继续运行)"
echo "  tmux kill-session -t raft_sim  # 停止所有进程"
echo ""

# 自动进入会话
tmux attach -t raft_sim

"""
轻量级仿真集线器 (Sim Hub Lite)
--------------------------------
用途: 纯 UDP 转发，模拟无线广播信道，专门用于测试 Raft 逻辑
无需 GNU Radio，启动快速，适合开发调试

架构:
    节点 1 (TX:50000, RX:50001)  ──┐
    节点 2 (TX:50000, RX:50002)  ──┼──► Hub (监听 50000) ──► 广播到 50001-50005
    节点 3 (TX:50000, RX:50003)  ──┘
    ...

用法:
    python3 scripts/core/sim_hub_lite.py [--nodes 5] [--port 50000]
"""

import socket
import argparse
import time
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="轻量级仿真集线器")
    parser.add_argument("--nodes", type=int, default=5, help="节点数量 (默认 5)")
    parser.add_argument("--port", type=int, default=50000, help="监听端口 (默认 50000)")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    args = parser.parse_args()
    
    # 计算转发目标端口列表
    rx_ports = [args.port + i for i in range(1, args.nodes + 1)]
    
    # 创建 UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', args.port))
    
    print("=" * 60)
    print("🌐 轻量级仿真集线器 (Sim Hub Lite)")
    print("=" * 60)
    print(f"📡 监听端口: {args.port}")
    print(f"📤 广播目标: {rx_ports}")
    print(f"🚗 支持节点: {args.nodes} 个")
    print("=" * 60)
    print("等待消息...\n")
    
    msg_count = 0
    start_time = time.time()
    
    try:
        while True:
            data, addr = sock.recvfrom(4096)
            msg_count += 1
            
            # 广播给所有节点
            for port in rx_ports:
                sock.sendto(data, ('127.0.0.1', port))
            
            if args.verbose:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                # 尝试解析消息类型
                try:
                    import json
                    msg = json.loads(data.decode('utf-8'))
                    msg_type = msg.get('type', 'Unknown')
                    sender_id = msg.get('sender_id', '?')
                    term = msg.get('term', '?')
                    print(f"[{timestamp}] #{msg_count} | {msg_type:20} | Node {sender_id} | Term {term}")
                except:
                    print(f"[{timestamp}] #{msg_count} | RAW: {data[:50]}...")
            else:
                # 简洁模式：每 100 条消息打印一次统计
                if msg_count % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = msg_count / elapsed
                    print(f"📊 已转发 {msg_count} 条消息 ({rate:.1f} msg/s)")
                    
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\n🛑 停止运行")
        print(f"📊 统计: {msg_count} 条消息, 运行 {elapsed:.1f} 秒, 平均 {msg_count/elapsed:.1f} msg/s")


if __name__ == "__main__":
    main()

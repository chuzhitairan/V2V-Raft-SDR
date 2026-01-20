#!/usr/bin/env python3
"""
连通性测试工具
==============
一个节点只收，其他节点发，测试各节点到接收节点的连通性。

使用方法:
    python3 scripts/app/connectivity_test.py --receiver 1
    python3 scripts/app/connectivity_test.py --receiver 1 --senders 2,3,4,5,6
    python3 scripts/app/connectivity_test.py --receiver 1 --tx-gain 0.7 --rx-gain 0.7
"""

import socket
import time
import json
import argparse
import subprocess
import signal
import os
import sys
from typing import List, Dict

# ==========================================
# 配置 - 你的 6 台 SDR
# ==========================================

SDR_CONFIG = {
    1: {"sdr_args": "addr=192.168.1.10", "tx_port": 10001, "rx_port": 20001, "ctrl_port": 9001},
    2: {"sdr_args": "addr=192.168.1.11", "tx_port": 10002, "rx_port": 20002, "ctrl_port": 9002},
    3: {"sdr_args": "addr=192.168.1.12", "tx_port": 10003, "rx_port": 20003, "ctrl_port": 9003},
    4: {"sdr_args": "addr=192.168.1.13", "tx_port": 10004, "rx_port": 20004, "ctrl_port": 9004},
    5: {"sdr_args": "serial=U200100",    "tx_port": 10005, "rx_port": 20005, "ctrl_port": 9005},
    6: {"sdr_args": "serial=U200101",    "tx_port": 10006, "rx_port": 20006, "ctrl_port": 9006},
}

# ==========================================
# PHY 管理
# ==========================================

class PhyManager:
    def __init__(self):
        self.processes = {}
        self.project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    def start_node(self, node_id: int, tx_gain: float, rx_gain: float) -> bool:
        """启动单个节点"""
        cfg = SDR_CONFIG[node_id]
        
        cmd = [
            sys.executable,
            os.path.join(self.project_dir, "scripts/core/v2v_hw_phy.py"),
            "--sdr-args", cfg['sdr_args'],
            "--tx-gain", str(tx_gain),
            "--rx-gain", str(rx_gain),
            "--udp-recv-port", str(cfg['tx_port']),
            "--udp-send-port", str(cfg['rx_port']),
            "--ctrl-port", str(cfg['ctrl_port']),
            "--no-gui"
        ]
        
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
            self.processes[node_id] = proc
            return True
        except Exception as e:
            print(f"❌ Node {node_id} 启动失败: {e}")
            return False
    
    def ping_node(self, node_id: int) -> bool:
        """检查节点是否就绪"""
        cfg = SDR_CONFIG[node_id]
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            cmd = json.dumps({"cmd": "ping"})
            sock.sendto(cmd.encode(), ('127.0.0.1', cfg['ctrl_port']))
            data, _ = sock.recvfrom(1024)
            sock.close()
            resp = json.loads(data.decode())
            return resp.get('msg') == 'pong'
        except:
            return False
    
    def stop_all(self):
        """停止所有节点"""
        for node_id, proc in self.processes.items():
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=3)
            except:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except:
                    pass
        self.processes.clear()
        
        try:
            subprocess.run(['pkill', '-f', 'v2v_hw_phy.py'], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
        time.sleep(2)

# ==========================================
# 连通性测试
# ==========================================

def run_connectivity_test(receiver_id: int, sender_ids: List[int], 
                          duration: float = 10.0, interval: float = 0.2) -> Dict:
    """
    运行连通性测试
    - receiver_id: 接收节点
    - sender_ids: 发送节点列表
    """
    results = {sid: {'sent': 0, 'received': 0, 'snr_list': []} for sid in sender_ids}
    
    receiver_cfg = SDR_CONFIG[receiver_id]
    
    # 创建接收 socket
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx_sock.bind(('127.0.0.1', receiver_cfg['rx_port']))
    rx_sock.setblocking(False)
    
    # 创建发送 socket
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print(f"\n📡 开始连通性测试 (持续 {duration} 秒)")
    print(f"   接收节点: Node {receiver_id}")
    print(f"   发送节点: {sender_ids}")
    print("-" * 50)
    
    start_time = time.time()
    seq = 0
    last_print_time = start_time
    
    try:
        while time.time() - start_time < duration:
            # 每个发送节点发一个包
            for sender_id in sender_ids:
                sender_cfg = SDR_CONFIG[sender_id]
                packet = json.dumps({
                    "type": "CONNECTIVITY_TEST",
                    "seq": seq,
                    "sender_id": sender_id,
                    "term": 0,
                    "ts": time.time(),
                    "phy_state": {"snr": 0.0}
                })
                tx_sock.sendto(packet.encode(), ('127.0.0.1', sender_cfg['tx_port']))
                results[sender_id]['sent'] += 1
                seq += 1
            
            # 接收
            try:
                while True:
                    data, _ = rx_sock.recvfrom(4096)
                    try:
                        msg = json.loads(data.decode())
                        sender_id = msg.get('sender_id', -1)
                        if sender_id in results:
                            results[sender_id]['received'] += 1
                            if 'phy_state' in msg:
                                snr = msg['phy_state'].get('snr', 0)
                                if snr > 0:
                                    results[sender_id]['snr_list'].append(snr)
                    except:
                        pass
            except BlockingIOError:
                pass
            
            # 每 2 秒打印一次实时状态
            if time.time() - last_print_time >= 2.0:
                elapsed = time.time() - start_time
                print(f"   [{elapsed:.0f}s] ", end="")
                for sid in sender_ids:
                    r = results[sid]
                    rate = r['received'] / r['sent'] * 100 if r['sent'] > 0 else 0
                    print(f"Node{sid}:{rate:.0f}% ", end="")
                print()
                last_print_time = time.time()
            
            time.sleep(interval)
    
    finally:
        rx_sock.close()
        tx_sock.close()
    
    return results

def print_results(receiver_id: int, results: Dict):
    """打印测试结果"""
    print("\n" + "=" * 60)
    print(f"连通性测试结果 (接收节点: Node {receiver_id})")
    print("=" * 60)
    print(f"{'发送节点':>10} {'发送数':>8} {'接收数':>8} {'成功率':>8} {'平均SNR':>10}")
    print("-" * 60)
    
    for sender_id, data in sorted(results.items()):
        sent = data['sent']
        received = data['received']
        rate = received / sent * 100 if sent > 0 else 0
        avg_snr = sum(data['snr_list']) / len(data['snr_list']) if data['snr_list'] else 0
        
        # 根据成功率显示状态
        if rate >= 80:
            status = "✅"
        elif rate >= 50:
            status = "⚠️"
        else:
            status = "❌"
        
        print(f"   Node {sender_id:>2} {sent:>8} {received:>8} {rate:>7.1f}% {avg_snr:>9.1f}dB {status}")
    
    print("=" * 60)
    
    # 汇总
    total_sent = sum(d['sent'] for d in results.values())
    total_received = sum(d['received'] for d in results.values())
    overall_rate = total_received / total_sent * 100 if total_sent > 0 else 0
    
    connected = sum(1 for d in results.values() if d['received'] / d['sent'] * 100 >= 50 if d['sent'] > 0)
    print(f"\n📊 汇总: {connected}/{len(results)} 个节点连通")
    print(f"   总体成功率: {overall_rate:.1f}%")

def main():
    parser = argparse.ArgumentParser(description="连通性测试工具")
    parser.add_argument("--receiver", type=int, default=1,
                       help="接收节点 ID [default: 1]")
    parser.add_argument("--senders", type=str, default=None,
                       help="发送节点 ID (逗号分隔) [default: 除接收节点外的所有节点]")
    parser.add_argument("--tx-gain", type=float, default=0.7,
                       help="TX 增益 [default: 0.7]")
    parser.add_argument("--rx-gain", type=float, default=0.7,
                       help="RX 增益 [default: 0.7]")
    parser.add_argument("--duration", type=float, default=10.0,
                       help="测试持续时间(秒) [default: 10.0]")
    args = parser.parse_args()
    
    receiver_id = args.receiver
    
    # 确定发送节点
    if args.senders:
        sender_ids = [int(x.strip()) for x in args.senders.split(',')]
    else:
        sender_ids = [i for i in SDR_CONFIG.keys() if i != receiver_id]
    
    # 验证节点 ID
    all_nodes = [receiver_id] + sender_ids
    for nid in all_nodes:
        if nid not in SDR_CONFIG:
            print(f"❌ 无效的节点 ID: {nid}")
            return
    
    print("=" * 60)
    print("连通性测试工具")
    print("=" * 60)
    print(f"接收节点: Node {receiver_id} ({SDR_CONFIG[receiver_id]['sdr_args']})")
    print(f"发送节点: {sender_ids}")
    print(f"TX/RX 增益: {args.tx_gain}/{args.rx_gain}")
    print(f"测试时长: {args.duration}s")
    print("=" * 60)
    
    phy_manager = PhyManager()
    
    try:
        # 分批启动: 先 E200 再 U200
        e200_nodes = [n for n in all_nodes if 'addr=' in SDR_CONFIG[n]['sdr_args']]
        u200_nodes = [n for n in all_nodes if 'serial=' in SDR_CONFIG[n]['sdr_args']]
        
        ready_nodes = []
        
        # 启动 E200
        if e200_nodes:
            print(f"\n🚀 启动 E200 节点: {e200_nodes}")
            for node_id in e200_nodes:
                print(f"   Node {node_id}: {SDR_CONFIG[node_id]['sdr_args']}", end=" ", flush=True)
                phy_manager.start_node(node_id, args.tx_gain, args.rx_gain)
                time.sleep(8)  # E200 初始化
                
                # 检查就绪
                ok = False
                for attempt in range(5):
                    if phy_manager.ping_node(node_id):
                        ok = True
                        break
                    time.sleep(1)
                
                if ok:
                    print("✓")
                    ready_nodes.append(node_id)
                else:
                    print("❌")
                
                time.sleep(2)  # 节点间间隔
        
        # 启动 U200
        if u200_nodes:
            print(f"\n🚀 启动 U200 节点: {u200_nodes}")
            for node_id in u200_nodes:
                print(f"   Node {node_id}: {SDR_CONFIG[node_id]['sdr_args']}", end=" ", flush=True)
                phy_manager.start_node(node_id, args.tx_gain, args.rx_gain)
            
            print(f"   等待 U200 初始化 (15秒)...", end=" ", flush=True)
            time.sleep(15)
            print("完成")
            
            for node_id in u200_nodes:
                ok = False
                for attempt in range(5):
                    if phy_manager.ping_node(node_id):
                        ok = True
                        break
                    time.sleep(1)
                
                if ok:
                    print(f"     Node {node_id}: ✓")
                    ready_nodes.append(node_id)
                else:
                    print(f"     Node {node_id}: ❌")
        
        print(f"\n📊 就绪节点: {ready_nodes}")
        
        # 检查接收节点是否就绪
        if receiver_id not in ready_nodes:
            print(f"❌ 接收节点 Node {receiver_id} 未就绪，无法测试")
            return
        
        # 过滤出就绪的发送节点
        ready_senders = [s for s in sender_ids if s in ready_nodes]
        if not ready_senders:
            print("❌ 没有就绪的发送节点")
            return
        
        # 运行测试
        results = run_connectivity_test(receiver_id, ready_senders, duration=args.duration)
        print_results(receiver_id, results)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    finally:
        phy_manager.stop_all()

if __name__ == "__main__":
    main()

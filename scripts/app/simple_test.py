import socket
import time
import threading

# 发送目标：发给本地 GNU Radio 监听的端口
GR_IP = "127.0.0.1"
GR_PORT = 12345

# 接收端口：监听 GNU Radio 发回来的端口
MY_LISTEN_PORT = 54321

def receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', MY_LISTEN_PORT))
    print(f"正在监听 {MY_LISTEN_PORT}...")
    while True:
        data, addr = sock.recvfrom(2048)
        print(f"\n[<--] 收到回信: {data.decode()}")

def sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    i = 0
    while True:
        msg = f"Hello V2V {i}".encode()
        print(f"\n[-->] 发送给基站: {msg}")
        # 直接发给 GNU Radio 的 UDP 端口
        sock.sendto(msg, (GR_IP, GR_PORT))
        i += 1
        time.sleep(1)

# 启动
t = threading.Thread(target=receiver)
t.daemon = True
t.start()

time.sleep(1)
sender()
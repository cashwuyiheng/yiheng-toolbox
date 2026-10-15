# -*- coding: utf-8 -*-
"""重启本地网关：只杀占用 8788 的进程，不动监控。
建议【以管理员身份】运行 重启网关.bat（bat 会自己请求提权）。"""
import os
import subprocess
import sys
import time

PORT = 8788
HERE = os.path.dirname(os.path.abspath(__file__))
NO_WIN = subprocess.CREATE_NO_WINDOW


def listeners():
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                           encoding="gbk", errors="replace", creationflags=NO_WIN)
    except Exception:
        return set()
    pids = set()
    for line in (r.stdout or "").splitlines():
        if f":{PORT}" in line and "LISTENING" in line:
            tok = line.split()
            if tok:
                pids.add(tok[-1])
    return pids


def kill(pid):
    r = subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True,
                       encoding="gbk", errors="replace", creationflags=NO_WIN)
    return r.returncode == 0


pids = listeners()
if not pids:
    print("没有正在跑的旧网关，直接起新的。")
else:
    for pid in pids:
        ok = kill(pid)
        print(f"停 PID {pid}: {'成功' if ok else '失败（多半权限不足）'}")

time.sleep(1)
left = listeners()
if left:
    print("")
    print("[!] 还是杀不掉占用 8788 的进程: " + ", ".join(left))
    print("    -> 请【右键 -> 以管理员身份运行】重启网关.bat；")
    print("    -> 或者直接重启电脑，端口就自然空出来了。")
    try:
        input("按回车退出…")
    except Exception:
        pass
    sys.exit(1)

pyw = sys.executable.replace("python.exe", "pythonw.exe")
if not os.path.exists(pyw):
    pyw = sys.executable
subprocess.Popen([pyw, os.path.join(HERE, "ai_relay.py")], creationflags=NO_WIN)
time.sleep(2)
if listeners():
    print("已起新网关。现在 8788 上只有它。")
else:
    print("[!] 新网关没起来，请检查 ai_relay.py。")

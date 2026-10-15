import os
import json
import csv
import time
import datetime
import hashlib
from pathlib import Path

# 配置区域（符合U盘归档结构）
SOURCE_DIR = Path(r".\twitter_data")
PROCESSED_DIR = Path(r".\twitter_monitor\processed")
LOGS_DIR = Path(r".\twitter_monitor\logs")
ARCHIVE_DIR = Path(r".\twitter_monitor\archive")

# 创建必要目录
for d in [PROCESSED_DIR, LOGS_DIR, ARCHIVE_DIR]:
    d.mkdir(exist_ok=True)

# 代理探测优化：基于文件特征自动识别
def detect_data_source(file_path):
    """通过文件特征自动识别数据类型"""
    try:
        # 检查文件头特征
        with open(file_path, 'rb') as f:
            header = f.read(100)
        
        # JSON特征检测
        if b'{' in header and b'}' in header:
            return "json"
        
        # CSV特征检测
        if b',' in header and b'\n' in header:
            return "csv"
        
        # 纯文本特征
        if header.decode('utf-8', errors='ignore').strip():
            return "text"
        
        return "unknown"
    
    except Exception as e:
        log_error(f"代理探测失败: {str(e)}", level="critical")
        return "unknown"

# 告警机制（参考微信监控架构）
def log_error(message, level="error"):
    """三级告警系统实现"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 一级告警：日志记录
    with open(LOGS_DIR / "error.log", "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [{level.upper()}] {message}\n")
    
    # 二级告警：桌面通知（仅当非静默模式）
    if level in ["error", "critical"]:
        os.system(
            f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            f'[System.Windows.Forms.MessageBox]::Show(\'{message.replace("\'", "\\'")}\', '
            f'\'推特监控告警\', \'OK\', \'Error\')"'
        )
    
    # 三级告警：U盘归档（致命错误）
    if level == "critical":
        archive_path = ARCHIVE_DIR / f"alert_{int(time.time())}.log"
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(f"告警级别: {level.upper()}\n时间: {timestamp}\n详情: {message}")

def process_file(file_path):
    """处理单个文件的核心逻辑"""
    try:
        file_type = detect_data_source(file_path)
        
        if file_type == "json":
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 这里添加JSON处理逻辑
            log_error(f"处理JSON文件: {os.path.basename(file_path)}", level="info")
            
        elif file_type == "csv":
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                # 这里添加CSV处理逻辑
                log_error(f"处理CSV文件: {os.path.basename(file_path)}", level="info")
                
        elif file_type == "text":
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # 这里添加文本处理逻辑
            log_error(f"处理文本文件: {os.path.basename(file_path)}", level="info")
            
        else:
            log_error(f"无法识别文件类型: {os.path.basename(file_path)}", level="warning")
            return
        
        # 成功处理后移动到processed目录
        target_path = PROCESSED_DIR / os.path.basename(file_path)
        file_path.rename(target_path)
        
    except Exception as e:
        log_error(f"处理失败: {str(e)}", level="error")

def main():
    """主监控循环"""
    log_error("推特监控系统已启动", level="info")
    
    while True:
        try:
            # 扫描源目录
            for item in SOURCE_DIR.iterdir():
                if item.is_file():
                    process_file(item)
            
            # 每分钟检查一次
            time.sleep(60)
            
        except Exception as e:
            log_error(f"监控系统异常: {str(e)}", level="critical")

if __name__ == "__main__":
    main()
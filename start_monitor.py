#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
CPU监控器启动脚本
确保以管理员权限运行程序
"""

import os
import sys
import ctypes
import subprocess
import logging

def is_admin():
    """检查是否具有管理员权限"""
    try:
        # Unix/Linux/Mac
        return os.getuid() == 0
    except AttributeError:
        # Windows
        return ctypes.windll.shell32.IsUserAnAdmin() != 0

def restart_with_admin():
    """以管理员权限重启程序"""
    if sys.platform == 'win32':
        # Windows
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
    else:
        # Unix/Linux/Mac
        if os.path.exists('/usr/bin/pkexec'):
            args = ['/usr/bin/pkexec', sys.executable] + sys.argv
        else:
            args = ['sudo', sys.executable] + sys.argv
        
        subprocess.Popen(args)
    
    sys.exit(0)

def main():
    """主函数"""
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('cpu_monitor_launcher.log'),
            logging.StreamHandler()
        ]
    )
    
    # 检查管理员权限
    if not is_admin():
        print("需要管理员权限来运行CPU监控器。")
        print("请授予权限以获得完整功能。")
        
        try:
            restart_with_admin()
        except Exception as e:
            logging.error(f"无法以管理员权限重启: {str(e)}")
            print("无法自动获取管理员权限。")
            print("请右键点击程序，选择'以管理员身份运行'。")
            input("按Enter键退出...")
            sys.exit(1)
    
    # 以管理员权限运行
    try:
        print("正在启动CPU监控器...")
        
        # 导入并运行主程序
        from cpu_monitor_ui import main as run_monitor
        run_monitor()
        
    except ImportError:
        logging.error("无法导入CPU监控器模块")
        print("错误: 无法找到CPU监控器模块。")
        print("请确保cpu_monitor_ui.py在同一目录下。")
        input("按Enter键退出...")
        sys.exit(1)
    except Exception as e:
        logging.error(f"启动失败: {str(e)}")
        print(f"错误: {str(e)}")
        input("按Enter键退出...")
        sys.exit(1)

if __name__ == "__main__":
    main() 
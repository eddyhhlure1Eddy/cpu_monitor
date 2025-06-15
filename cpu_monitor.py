import psutil
import time
from datetime import datetime
import os
import sys
from prettytable import PrettyTable
import threading
import logging

class CPUMonitor:
    def __init__(self, threshold=70):
        """
        Initialize CPU Monitor
        :param threshold: CPU usage threshold percentage to highlight high usage
        """
        self.threshold = threshold
        self.running = True
        self.setup_logging()
        
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('cpu_monitor.log'),
                logging.StreamHandler()
            ]
        )
        
    def get_process_info(self, process):
        """
        Get information about a specific process
        """
        try:
            with process.oneshot():
                cpu_percent = process.cpu_percent(interval=0.1)
                memory_percent = process.memory_percent()
                name = process.name()
                pid = process.pid
                username = process.username()
                return name, pid, cpu_percent, memory_percent, username
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
            
    def kill_process(self, pid):
        """
        Terminate a process by PID
        """
        try:
            process = psutil.Process(pid)
            process.terminate()
            logging.info(f"Process {pid} terminated successfully")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            logging.error(f"Failed to terminate process {pid}")
            return False
            
    def monitor_processes(self):
        """
        Monitor and display system processes
        """
        while self.running:
            table = PrettyTable()
            table.field_names = ["Name", "PID", "CPU %", "Memory %", "User", "Status"]
            
            processes = []
            for proc in psutil.process_iter(['name', 'pid', 'cpu_percent', 'memory_percent', 'username']):
                try:
                    info = self.get_process_info(proc)
                    if info:
                        name, pid, cpu, mem, user = info
                        status = "HIGH" if cpu > self.threshold else "Normal"
                        processes.append([name, pid, f"{cpu:.1f}", f"{mem:.1f}", user, status])
                        
                        if cpu > self.threshold:
                            logging.warning(f"High CPU usage detected - Process: {name} (PID: {pid}) - CPU: {cpu:.1f}%")
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            # Sort by CPU usage (descending)
            processes.sort(key=lambda x: float(x[2]), reverse=True)
            
            # Add top processes to table
            for proc in processes[:15]:  # Show top 15 processes
                table.add_row(proc)
            
            # Clear screen and show updated table
            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"\nCPU Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"System CPU Usage: {psutil.cpu_percent()}%")
            print(f"Threshold: {self.threshold}%\n")
            print(table)
            print("\nCommands: 'k <pid>' to kill process, 'q' to quit")
            
            time.sleep(2)  # Update every 2 seconds
            
    def start(self):
        """
        Start the monitoring process
        """
        monitor_thread = threading.Thread(target=self.monitor_processes)
        monitor_thread.start()
        
        while True:
            command = input().strip().lower()
            if command == 'q':
                self.running = False
                break
            elif command.startswith('k '):
                try:
                    pid = int(command.split()[1])
                    if self.kill_process(pid):
                        print(f"Process {pid} terminated successfully")
                    else:
                        print(f"Failed to terminate process {pid}")
                except (ValueError, IndexError):
                    print("Invalid command. Use 'k <pid>' to kill a process")

if __name__ == "__main__":
    try:
        monitor = CPUMonitor()
        print("Starting CPU Monitor...")
        monitor.start()
    except KeyboardInterrupt:
        print("\nShutting down CPU Monitor...") 
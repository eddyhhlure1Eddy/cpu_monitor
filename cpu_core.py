import psutil
import time
from datetime import datetime
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from threading import Thread, Lock, Event
import queue
import sys
import traceback
import os

@dataclass
class ProcessInfo:
    name: str
    pid: int
    cpu_percent: float
    memory_percent: float
    username: str
    status: str
    command: str
    create_time: float
    threads: int
    avg_cpu_percent: float = 0.0  # 3分钟平均CPU使用率

class CPUMonitorCore:
    def __init__(self, threshold: float = 70, update_interval: float = 2.0):
        self.threshold = threshold
        self.running = True
        self.update_interval = update_interval
        self._setup_logging()
        self.data_lock = Lock()
        self.update_event = Event()
        self.process_data: List[ProcessInfo] = []
        self.system_data = {
            'cpu_percent': 0,
            'memory_percent': 0,
            'cpu_freq': 0,
            'cpu_count': psutil.cpu_count(),
            'cpu_stats': {},
            'memory_stats': {}
        }
        self.history_data = {
            'cpu': [],
            'memory': [],
            'timestamps': []
        }
        self.history_max_points = 100
        self.update_queue = queue.Queue()
        
        # 进程CPU使用历史记录
        self.process_cpu_history = {}  # {pid: [(timestamp, cpu_percent), ...]}
        self.history_window = 180  # 3分钟 = 180秒
        
        # 进程缓存，减少重复获取
        self.process_cache = {}
        self.cache_ttl = 5  # 缓存有效期（秒）
        self.last_cache_cleanup = time.time()
        
        # 验证系统访问权限
        self._verify_system_access()
        
        # 预热系统，确保进程信息可用
        self._warmup_system()
        
        self._start_monitor_thread()
        logging.info("CPUMonitorCore initialized successfully")

    def _verify_system_access(self):
        """验证是否有足够的系统访问权限"""
        try:
            # 测试进程访问
            test_process = psutil.Process()
            test_process.cpu_percent()
            test_process.memory_percent()
            
            # 测试系统信息访问
            psutil.cpu_percent()
            psutil.virtual_memory()
            
            logging.info("System access verification successful")
        except psutil.AccessDenied:
            logging.error("Insufficient permissions to access system information")
            raise PermissionError("需要管理员权限才能访问系统信息")
        except Exception as e:
            logging.error(f"System access verification failed: {str(e)}")
            raise
            
    def _warmup_system(self):
        """预热系统，确保进程信息可用"""
        try:
            # 预热CPU百分比计算
            psutil.cpu_percent(interval=0.1)
            
            # 获取所有进程列表，预热进程信息
            process_count = 0
            for _ in psutil.process_iter(['pid']):
                process_count += 1
                
            logging.info(f"System warmup complete - detected {process_count} processes")
        except Exception as e:
            logging.error(f"System warmup failed: {str(e)}")

    def _setup_logging(self):
        """设置日志记录"""
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('cpu_monitor_core.log'),
                logging.StreamHandler()
            ]
        )

    def _cleanup_process_history(self):
        """清理过期的进程CPU使用历史记录"""
        current_time = time.time()
        cutoff_time = current_time - self.history_window
        
        with self.data_lock:
            # 清理过期数据
            for pid in list(self.process_cpu_history.keys()):
                history = self.process_cpu_history[pid]
                # 保留最近3分钟的数据
                history = [(t, c) for t, c in history if t >= cutoff_time]
                if history:
                    self.process_cpu_history[pid] = history
                else:
                    del self.process_cpu_history[pid]

    def _update_process_cpu_history(self, pid: int, cpu_percent: float):
        """更新进程CPU使用历史"""
        current_time = time.time()
        with self.data_lock:
            if pid not in self.process_cpu_history:
                self.process_cpu_history[pid] = []
            self.process_cpu_history[pid].append((current_time, cpu_percent))

    def _calculate_average_cpu(self, pid: int) -> float:
        """计算进程的3分钟平均CPU使用率"""
        with self.data_lock:
            if pid not in self.process_cpu_history:
                return 0.0
            
            history = self.process_cpu_history[pid]
            current_time = time.time()
            cutoff_time = current_time - self.history_window
            
            # 只计算最近3分钟的数据
            recent_history = [(t, c) for t, c in history if t >= cutoff_time]
            if not recent_history:
                return 0.0
            
            total_cpu = sum(cpu for _, cpu in recent_history)
            return total_cpu / len(recent_history)

    def _get_process_info(self, process: psutil.Process) -> Optional[ProcessInfo]:
        """获取进程信息（优化版本）"""
        pid = process.pid
        
        # 检查缓存
        current_time = time.time()
        if pid in self.process_cache:
            cache_entry = self.process_cache[pid]
            # 如果缓存未过期，直接返回
            if current_time - cache_entry['timestamp'] < self.cache_ttl:
                # 仅更新CPU和内存使用率
                try:
                    cpu_percent = process.cpu_percent()
                    cache_entry['info'].cpu_percent = cpu_percent
                    cache_entry['info'].memory_percent = process.memory_percent()
                    cache_entry['info'].status = "HIGH" if cpu_percent > self.threshold else "Normal"
                    # 更新CPU历史并计算平均值
                    self._update_process_cpu_history(pid, cpu_percent)
                    cache_entry['info'].avg_cpu_percent = self._calculate_average_cpu(pid)
                    return cache_entry['info']
                except:
                    # 如果更新失败，删除缓存
                    del self.process_cache[pid]
        
        # 缓存未命中，获取完整信息
        try:
            # 使用oneshot减少系统调用
            with process.oneshot():
                try:
                    # 基本信息
                    name = process.name()
                    
                    # CPU和内存使用
                    cpu_percent = process.cpu_percent()
                    memory_percent = process.memory_percent()
                    
                    # 更新CPU历史
                    self._update_process_cpu_history(pid, cpu_percent)
                    avg_cpu_percent = self._calculate_average_cpu(pid)
                    
                    # 用户信息 - 可能耗时，简化处理
                    try:
                        username = process.username()
                    except:
                        username = "N/A"
                    
                    # 状态
                    status = "HIGH" if cpu_percent > self.threshold else "Normal"
                    
                    # 命令行 - 可能耗时，简化处理
                    try:
                        cmdline = process.cmdline()
                        command = ' '.join(cmdline) if cmdline else process.exe()
                    except:
                        command = name
                    
                    # 创建时间
                    try:
                        create_time = process.create_time()
                    except:
                        create_time = 0
                    
                    # 线程数
                    try:
                        threads = process.num_threads()
                    except:
                        threads = 0

                    # 创建进程信息对象
                    info = ProcessInfo(
                        name=name,
                        pid=pid,
                        cpu_percent=cpu_percent,
                        memory_percent=memory_percent,
                        username=username,
                        status=status,
                        command=command,
                        create_time=create_time,
                        threads=threads,
                        avg_cpu_percent=avg_cpu_percent
                    )
                    
                    # 更新缓存
                    self.process_cache[pid] = {
                        'info': info,
                        'timestamp': current_time
                    }
                    
                    return info
                    
                except psutil.NoSuchProcess:
                    # 进程不存在，从缓存中删除
                    if pid in self.process_cache:
                        del self.process_cache[pid]
                    return None
                except psutil.AccessDenied:
                    # 对于无法访问的进程，使用有限信息
                    try:
                        info = ProcessInfo(
                            name=process.name() if hasattr(process, 'name') else "Access Denied",
                            pid=pid,
                            cpu_percent=0.0,
                            memory_percent=0.0,
                            username="N/A",
                            status="N/A",
                            command="Access Denied",
                            create_time=0,
                            threads=0
                        )
                        
                        # 更新缓存
                        self.process_cache[pid] = {
                            'info': info,
                            'timestamp': current_time
                        }
                        
                        return info
                    except:
                        return None
                except Exception as e:
                    logging.debug(f"Error getting process info: {str(e)}")
                    return None
        except Exception as e:
            logging.debug(f"Error in process oneshot context: {str(e)}")
            return None
    
    def _cleanup_process_cache(self):
        """清理过期的进程缓存"""
        current_time = time.time()
        if current_time - self.last_cache_cleanup > 30:  # 每30秒清理一次
            expired_pids = []
            for pid, cache_entry in self.process_cache.items():
                if current_time - cache_entry['timestamp'] > self.cache_ttl:
                    expired_pids.append(pid)
            
            for pid in expired_pids:
                del self.process_cache[pid]
                
            self.last_cache_cleanup = current_time
            logging.debug(f"Cache cleanup: removed {len(expired_pids)} expired entries")

    def _update_system_stats(self):
        """更新系统统计信息"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            cpu_freq = psutil.cpu_freq()
            
            with self.data_lock:
                self.system_data.update({
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'cpu_freq': cpu_freq.current if cpu_freq else 0,
                    'cpu_stats': {
                        'user': psutil.cpu_times_percent().user,
                        'system': psutil.cpu_times_percent().system,
                        'idle': psutil.cpu_times_percent().idle
                    },
                    'memory_stats': {
                        'total': memory.total,
                        'available': memory.available,
                        'used': memory.used
                    }
                })
                
                # Update history
                self.history_data['cpu'].append(cpu_percent)
                self.history_data['memory'].append(memory.percent)
                self.history_data['timestamps'].append(datetime.now())
                
                # Keep only last N points
                if len(self.history_data['cpu']) > self.history_max_points:
                    self.history_data['cpu'] = self.history_data['cpu'][-self.history_max_points:]
                    self.history_data['memory'] = self.history_data['memory'][-self.history_max_points:]
                    self.history_data['timestamps'] = self.history_data['timestamps'][-self.history_max_points:]
            
            logging.debug(f"System stats updated - CPU: {cpu_percent}%, Memory: {memory.percent}%")
        except Exception as e:
            logging.error(f"Error updating system stats: {str(e)}")
            logging.debug(traceback.format_exc())

    def _monitor_loop(self):
        """监控循环"""
        last_full_update = 0
        while self.running:
            try:
                current_time = time.time()
                
                # 更新系统统计信息
                self._update_system_stats()
                
                # 清理过期缓存和历史记录
                self._cleanup_process_cache()
                self._cleanup_process_history()
                
                # 是否需要完整更新
                full_update_needed = self.update_event.is_set() or (current_time - last_full_update >= 5)
                
                if full_update_needed:
                    # 重置更新事件
                    self.update_event.clear()
                    last_full_update = current_time
                    
                    # 更新进程列表
                    processes = []
                    
                    # 获取进程列表
                    try:
                        # 限制获取的进程数量，提高性能
                        process_iter = list(psutil.process_iter(['pid', 'name', 'cpu_percent']))
                        
                        # 按CPU使用率预排序，只处理前100个进程
                        process_iter.sort(key=lambda p: p.info['cpu_percent'] if p.info['cpu_percent'] is not None else 0, reverse=True)
                        process_iter = process_iter[:100]
                        
                        # 获取详细信息
                        for proc in process_iter:
                            info = self._get_process_info(proc)
                            if info:
                                processes.append(info)
                    except Exception as e:
                        logging.error(f"Error getting process list: {str(e)}")
                    
                    # 如果没有获取到进程，尝试备用方法
                    if not processes:
                        logging.warning("No processes found with standard method, trying alternative approach")
                        try:
                            for pid in psutil.pids()[:100]:  # 限制处理的进程数量
                                try:
                                    proc = psutil.Process(pid)
                                    info = self._get_process_info(proc)
                                    if info:
                                        processes.append(info)
                                except:
                                    continue
                        except Exception as e:
                            logging.error(f"Alternative process list retrieval failed: {str(e)}")
                    
                    # 按CPU使用率排序
                    processes.sort(key=lambda x: x.avg_cpu_percent, reverse=True)
                    
                    # 更新进程数据
                    with self.data_lock:
                        self.process_data = processes
                    
                    # 通知监听器
                    try:
                        self.update_queue.put(True, block=False)
                    except queue.Full:
                        pass
                    
                    logging.debug(f"Full monitor update completed - {len(processes)} processes found")
                
                # 休眠直到下一个更新周期
                time.sleep(self.update_interval)
                
            except Exception as e:
                logging.error(f"Error in monitor loop: {str(e)}")
                logging.debug(traceback.format_exc())
                time.sleep(self.update_interval)

    def _start_monitor_thread(self):
        """启动监控线程"""
        try:
            self.monitor_thread = Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            logging.info("Monitor thread started successfully")
        except Exception as e:
            logging.error(f"Failed to start monitor thread: {str(e)}")
            raise

    def get_process_list(self) -> List[ProcessInfo]:
        """获取进程列表"""
        with self.data_lock:
            return self.process_data.copy()

    def request_update(self):
        """请求立即更新进程信息"""
        self.update_event.set()
        logging.debug("Immediate update requested")

    def get_system_stats(self) -> Dict:
        """获取系统统计信息"""
        with self.data_lock:
            return self.system_data.copy()

    def get_history_data(self) -> Dict:
        """获取历史数据"""
        with self.data_lock:
            return {
                'cpu': self.history_data['cpu'].copy(),
                'memory': self.history_data['memory'].copy(),
                'timestamps': self.history_data['timestamps'].copy()
            }

    def kill_process(self, pid: int) -> bool:
        """终止进程"""
        try:
            process = psutil.Process(pid)
            process.terminate()
            
            # 从缓存中移除
            if pid in self.process_cache:
                del self.process_cache[pid]
                
            logging.info(f"Process {pid} terminated successfully")
            return True
        except psutil.NoSuchProcess:
            logging.error(f"Process {pid} not found")
            return False
        except psutil.AccessDenied:
            logging.error(f"Access denied when trying to terminate process {pid}")
            # 在Windows上尝试使用taskkill命令
            if sys.platform == 'win32':
                try:
                    os.system(f"taskkill /F /PID {pid}")
                    
                    # 从缓存中移除
                    if pid in self.process_cache:
                        del self.process_cache[pid]
                        
                    logging.info(f"Process {pid} terminated using taskkill")
                    return True
                except:
                    return False
            return False
        except Exception as e:
            logging.error(f"Error terminating process {pid}: {str(e)}")
            return False

    def set_threshold(self, threshold: float):
        """设置CPU阈值"""
        self.threshold = threshold
        logging.info(f"CPU threshold set to {threshold}%")

    def set_update_interval(self, interval: float):
        """设置更新间隔"""
        self.update_interval = max(0.5, interval)  # 最小0.5秒
        logging.info(f"Update interval set to {self.update_interval} seconds")

    def shutdown(self):
        """关闭监控"""
        logging.info("Shutting down CPU Monitor Core")
        self.running = False
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join(timeout=2) 
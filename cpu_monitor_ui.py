import sys
import os
import logging
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QLabel, QPushButton, QTableWidget,
                           QTableWidgetItem, QHeaderView, QMessageBox, QSpinBox,
                           QStyle, QStyleFactory, QFrame, QSplitter, QProgressBar,
                           QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QThread, pyqtSignal
from PyQt6.QtGui import QPalette, QColor, QFont
import pyqtgraph as pg
from datetime import datetime
import traceback
import time
from cpu_core import CPUMonitorCore, ProcessInfo

# 设置日志记录
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cpu_monitor_debug.log'),
        logging.StreamHandler()
    ]
)

class ProcessUpdateThread(QThread):
    """进程数据更新线程，避免UI阻塞"""
    update_ready = pyqtSignal(list, dict)
    
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.running = True
    
    def run(self):
        while self.running:
            try:
                # 等待更新信号
                try:
                    self.core.update_queue.get(timeout=1)
                except:
                    continue
                
                # 获取数据
                processes = self.core.get_process_list()
                stats = self.core.get_system_stats()
                
                # 发送信号到UI线程
                self.update_ready.emit(processes, stats)
                
            except Exception as e:
                logging.error(f"Error in update thread: {str(e)}")
    
    def stop(self):
        self.running = False
        self.wait()

class CPUMonitorUI(QMainWindow):
    def __init__(self):
        super().__init__()
        logging.info("Initializing CPU Monitor UI")
        try:
            # 创建核心监控对象
            self.core = CPUMonitorCore(update_interval=2.0)
            
            # 创建更新线程
            self.update_thread = ProcessUpdateThread(self.core)
            self.update_thread.update_ready.connect(self.on_data_update)
            self.update_thread.start()
            
            # 初始化UI
            self.init_ui()
            
            # 性能相关设置
            self.last_ui_update = 0
            self.min_update_interval = 1.0  # 最小UI更新间隔（秒）
            self.auto_refresh = True
            self.table_needs_update = False
            
            logging.info("UI initialization completed")
        except Exception as e:
            logging.error(f"Error during initialization: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to initialize: {str(e)}")
        
    def init_ui(self):
        try:
            self.setWindowTitle('CPU Process Monitor')
            self.setMinimumSize(1200, 800)
            
            # Create main widget and layout
            main_widget = QWidget()
            self.setCentralWidget(main_widget)
            layout = QVBoxLayout(main_widget)
            
            # Status bar for messages
            self.statusBar().showMessage("Ready")
            
            # Create splitter for resizable sections
            splitter = QSplitter(Qt.Orientation.Vertical)
            layout.addWidget(splitter)
            
            # Top section - System Overview
            top_widget = QWidget()
            top_layout = QVBoxLayout(top_widget)
            
            # System stats panel
            stats_widget = QWidget()
            stats_layout = QHBoxLayout(stats_widget)
            
            # CPU Usage Card
            self.cpu_card = self._create_stat_card("CPU Usage", "0%")
            stats_layout.addWidget(self.cpu_card)
            
            # Memory Usage Card
            self.memory_card = self._create_stat_card("Memory Usage", "0%")
            stats_layout.addWidget(self.memory_card)
            
            # CPU Frequency Card
            self.freq_card = self._create_stat_card("CPU Frequency", "0 MHz")
            stats_layout.addWidget(self.freq_card)
            
            # Thread Count Card
            self.thread_card = self._create_stat_card("Total Threads", "0")
            stats_layout.addWidget(self.thread_card)
            
            stats_widget.setLayout(stats_layout)
            top_layout.addWidget(stats_widget)
            
            # Graphs
            graphs_widget = QWidget()
            graphs_layout = QHBoxLayout(graphs_widget)
            
            # CPU History Graph
            self.cpu_graph = self._create_graph("CPU History (%)")
            graphs_layout.addWidget(self.cpu_graph)
            
            # Memory History Graph
            self.memory_graph = self._create_graph("Memory History (%)")
            graphs_layout.addWidget(self.memory_graph)
            
            graphs_widget.setLayout(graphs_layout)
            top_layout.addWidget(graphs_widget)
            
            top_widget.setLayout(top_layout)
            splitter.addWidget(top_widget)
            
            # Bottom section - Process List
            bottom_widget = QWidget()
            bottom_layout = QVBoxLayout(bottom_widget)
            
            # Controls
            controls_widget = QWidget()
            controls_layout = QHBoxLayout(controls_widget)
            
            # Threshold control
            threshold_label = QLabel("CPU Alert Threshold (%):")
            self.threshold_spin = QSpinBox()
            self.threshold_spin.setRange(1, 100)
            self.threshold_spin.setValue(70)
            self.threshold_spin.valueChanged.connect(self._on_threshold_changed)
            
            # Auto-refresh checkbox
            self.auto_refresh_check = QCheckBox("自动刷新")
            self.auto_refresh_check.setChecked(True)
            self.auto_refresh_check.stateChanged.connect(self._on_auto_refresh_changed)
            
            # Refresh button
            self.refresh_button = QPushButton("刷新进程列表")
            self.refresh_button.clicked.connect(self._force_refresh)
            self.refresh_button.setStyleSheet("""
                QPushButton {
                    background-color: #4444ff;
                    color: white;
                    padding: 5px 15px;
                    border: none;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #6666ff;
                }
            """)
            
            # Kill Process button
            self.kill_button = QPushButton("结束选中进程")
            self.kill_button.clicked.connect(self._on_kill_process)
            self.kill_button.setStyleSheet("""
                QPushButton {
                    background-color: #ff4444;
                    color: white;
                    padding: 5px 15px;
                    border: none;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #ff6666;
                }
            """)
            
            controls_layout.addWidget(threshold_label)
            controls_layout.addWidget(self.threshold_spin)
            controls_layout.addWidget(self.auto_refresh_check)
            controls_layout.addWidget(self.refresh_button)
            controls_layout.addStretch()
            controls_layout.addWidget(self.kill_button)
            
            controls_widget.setLayout(controls_layout)
            bottom_layout.addWidget(controls_widget)
            
            # Process count label
            self.process_count_label = QLabel("进程数量: 0")
            bottom_layout.addWidget(self.process_count_label)
            
            # Process table
            self.process_table = QTableWidget()
            self.process_table.setColumnCount(10)  # 增加一列
            self.process_table.setHorizontalHeaderLabels([
                "进程名", "PID", "CPU %", "3分钟平均CPU %", "内存 %", "用户",
                "状态", "命令行", "启动时间", "线程数"
            ])
            
            # 优化表格性能
            self.process_table.setRowCount(100)  # 预分配行
            self.process_table.verticalHeader().setVisible(False)  # 隐藏行号
            self.process_table.setShowGrid(False)  # 隐藏网格线
            
            # 设置列宽
            header = self.process_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # 名称
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # PID
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # CPU
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 3分钟平均CPU
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # 内存
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # 用户
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # 状态
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # 命令行
            header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)  # 时间
            header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)  # 线程
            
            # 设置固定宽度的列
            self.process_table.setColumnWidth(1, 60)   # PID
            self.process_table.setColumnWidth(2, 60)   # CPU
            self.process_table.setColumnWidth(3, 100)  # 3分钟平均CPU
            self.process_table.setColumnWidth(4, 60)   # 内存
            self.process_table.setColumnWidth(5, 100)  # 用户
            self.process_table.setColumnWidth(6, 60)   # 状态
            self.process_table.setColumnWidth(8, 150)  # 时间
            self.process_table.setColumnWidth(9, 60)   # 线程
            
            # 允许排序，但默认关闭（按需启用）
            self.process_table.setSortingEnabled(False)
            
            bottom_layout.addWidget(self.process_table)
            bottom_widget.setLayout(bottom_layout)
            splitter.addWidget(bottom_widget)
            
            # Setup update timer - 仅用于图表更新
            self.update_timer = QTimer()
            self.update_timer.timeout.connect(self.update_graphs)
            self.update_timer.start(1000)  # 每秒更新图表
            
            # Setup graphs
            self.cpu_plot_data = self.cpu_graph.plot(pen='r')
            self.memory_plot_data = self.memory_graph.plot(pen='b')
            
            # Apply dark theme
            self.apply_dark_theme()
            
            # Initial update
            self._force_refresh()
            
            logging.info("UI components initialized successfully")
            
        except Exception as e:
            logging.error(f"Error in init_ui: {str(e)}")
            logging.debug(traceback.format_exc())
            raise
        
    def _create_stat_card(self, title, value):
        try:
            card = QFrame()
            card.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
            card.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                    border-radius: 5px;
                    padding: 10px;
                }
            """)
            
            layout = QVBoxLayout(card)
            
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #888888; font-size: 12px;")
            layout.addWidget(title_label)
            
            value_label = QLabel(value)
            value_label.setStyleSheet("color: #ffffff; font-size: 24px; font-weight: bold;")
            layout.addWidget(value_label)
            
            # 添加进度条
            if title in ["CPU Usage", "Memory Usage"]:
                progress = QProgressBar()
                progress.setRange(0, 100)
                progress.setValue(0)
                progress.setTextVisible(False)
                progress.setStyleSheet("""
                    QProgressBar {
                        background-color: #444444;
                        border-radius: 2px;
                        height: 4px;
                    }
                    QProgressBar::chunk {
                        background-color: #44aaff;
                        border-radius: 2px;
                    }
                """)
                layout.addWidget(progress)
                card.progress = progress
            
            card.value_label = value_label  # Store reference for updates
            return card
        except Exception as e:
            logging.error(f"Error creating stat card: {str(e)}")
            raise
        
    def _create_graph(self, title):
        try:
            graph = pg.PlotWidget()
            graph.setBackground('#2d2d2d')
            graph.setTitle(title, color='#888888')
            graph.showGrid(x=True, y=True, alpha=0.3)
            graph.setYRange(0, 100)  # Set y-axis range from 0 to 100%
            
            # 减少重绘频率
            graph.setDownsampling(auto=True, mode='peak')
            graph.setClipToView(True)
            graph.setAntialiasing(False)
            
            return graph
        except Exception as e:
            logging.error(f"Error creating graph: {str(e)}")
            raise
        
    def apply_dark_theme(self):
        self.setStyle(QStyleFactory.create("Fusion"))
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        
        self.setPalette(dark_palette)
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: #2d2d2d;
                border: none;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #888888;
                padding: 5px;
                border: none;
            }
            QTableWidget::item {
                padding: 5px;
            }
        """)
        
    def _format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def _force_refresh(self):
        """强制刷新UI和进程列表"""
        try:
            self.statusBar().showMessage("正在刷新进程列表...")
            self.refresh_button.setEnabled(False)
            self.refresh_button.setText("刷新中...")
            
            # 请求核心模块立即更新
            self.core.request_update()
            
            # 启用定时器检查更新是否完成
            check_timer = QTimer(self)
            check_timer.timeout.connect(lambda: self._check_refresh_complete(check_timer))
            check_timer.start(100)  # 每100ms检查一次
            
        except Exception as e:
            logging.error(f"Force refresh failed: {str(e)}")
            self.statusBar().showMessage(f"刷新失败: {str(e)}", 5000)
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("刷新进程列表")
    
    def _check_refresh_complete(self, timer):
        """检查刷新是否完成"""
        if self.table_needs_update:
            timer.stop()
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("刷新进程列表")
            self.statusBar().showMessage("刷新完成", 3000)
    
    def _on_auto_refresh_changed(self, state):
        """自动刷新状态改变"""
        self.auto_refresh = (state == Qt.CheckState.Checked.value)
        if self.auto_refresh:
            self.statusBar().showMessage("自动刷新已启用", 3000)
        else:
            self.statusBar().showMessage("自动刷新已禁用，需手动刷新", 3000)
    
    @pyqtSlot(list, dict)
    def on_data_update(self, processes, stats):
        """处理来自更新线程的数据更新"""
        try:
            # 检查是否应该更新UI
            current_time = time.time()
            if not self.auto_refresh and not self.table_needs_update:
                return
                
            if current_time - self.last_ui_update < self.min_update_interval:
                # 标记需要更新，但不立即更新
                self.table_needs_update = True
                return
                
            # 更新系统状态卡片
            cpu_percent = stats['cpu_percent']
            memory_percent = stats['memory_percent']
            
            self.cpu_card.value_label.setText(f"{cpu_percent:.1f}%")
            self.memory_card.value_label.setText(f"{memory_percent:.1f}%")
            self.freq_card.value_label.setText(f"{stats['cpu_freq']:.0f} MHz")
            
            # 更新进度条
            if hasattr(self.cpu_card, 'progress'):
                self.cpu_card.progress.setValue(int(cpu_percent))
                
            if hasattr(self.memory_card, 'progress'):
                self.memory_card.progress.setValue(int(memory_percent))
            
            # 更新进程表格
            self._update_process_table(processes)
            
            # 重置更新标志
            self.table_needs_update = False
            self.last_ui_update = current_time
            
        except Exception as e:
            logging.error(f"Error handling data update: {str(e)}")
            logging.debug(traceback.format_exc())
    
    def update_graphs(self):
        """仅更新图表，与进程表格分离"""
        try:
            # 更新图表
            history = self.core.get_history_data()
            if history['cpu']:
                self.cpu_plot_data.setData(history['cpu'])
            if history['memory']:
                self.memory_plot_data.setData(history['memory'])
                
        except Exception as e:
            logging.error(f"Error updating graphs: {str(e)}")
            logging.debug(traceback.format_exc())
    
    def _update_process_table(self, processes):
        """更新进程表格（优化版本）"""
        try:
            # 更新进程计数
            self.process_count_label.setText(f"进程数量: {len(processes)}")
            
            # 临时禁用排序以提高性能
            was_sorting_enabled = self.process_table.isSortingEnabled()
            self.process_table.setSortingEnabled(False)
            
            # 保存当前滚动位置
            scrollbar = self.process_table.verticalScrollBar()
            scroll_pos = scrollbar.value()
            
            # 清空表格并设置行数
            self.process_table.clearContents()
            self.process_table.setRowCount(len(processes))
            
            # 批量更新表格内容
            total_threads = 0
            for i, proc in enumerate(processes):
                if i >= len(processes):
                    break
                    
                total_threads += proc.threads
                self._update_table_row(i, proc)
            
            # 恢复排序
            self.process_table.setSortingEnabled(was_sorting_enabled)
            
            # 恢复滚动位置
            scrollbar.setValue(scroll_pos)
            
            # 更新线程计数
            self.thread_card.value_label.setText(str(total_threads))
            
        except Exception as e:
            logging.error(f"Error updating process table: {str(e)}")
            logging.debug(traceback.format_exc())
    
    def show_error_message(self, title, message):
        QMessageBox.critical(self, title, message)
            
    def _update_table_row(self, row, proc):
        try:
            def set_item(col, value, align=Qt.AlignmentFlag.AlignLeft):
                if self.process_table.item(row, col) is None:
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(align)
                    self.process_table.setItem(row, col, item)
                else:
                    self.process_table.item(row, col).setText(str(value))
                    self.process_table.item(row, col).setTextAlignment(align)
                
            set_item(0, proc.name)
            set_item(1, proc.pid, Qt.AlignmentFlag.AlignRight)
            set_item(2, f"{proc.cpu_percent:.1f}", Qt.AlignmentFlag.AlignRight)
            set_item(3, f"{proc.avg_cpu_percent:.1f}", Qt.AlignmentFlag.AlignRight)
            set_item(4, f"{proc.memory_percent:.1f}", Qt.AlignmentFlag.AlignRight)
            set_item(5, proc.username)
            
            # 状态列特殊处理 - 根据平均CPU使用率判断
            status = "HIGH" if proc.avg_cpu_percent > self.core.threshold else "Normal"
            if self.process_table.item(row, 6) is None:
                status_item = QTableWidgetItem(status)
                status_item.setForeground(
                    QColor("#ff4444") if status == "HIGH" else QColor("#44ff44")
                )
                self.process_table.setItem(row, 6, status_item)
            else:
                self.process_table.item(row, 6).setText(status)
                self.process_table.item(row, 6).setForeground(
                    QColor("#ff4444") if status == "HIGH" else QColor("#44ff44")
                )
            
            set_item(7, proc.command)
            
            # 处理创建时间
            if proc.create_time > 0:
                time_str = datetime.fromtimestamp(proc.create_time).strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = "N/A"
            set_item(8, time_str)
            
            set_item(9, proc.threads, Qt.AlignmentFlag.AlignRight)
            
            # 根据平均CPU使用率设置行背景色
            if proc.avg_cpu_percent > self.core.threshold:
                for col in range(self.process_table.columnCount()):
                    if self.process_table.item(row, col):
                        self.process_table.item(row, col).setBackground(QColor(40, 0, 0))
                        
        except Exception as e:
            logging.error(f"Error updating table row {row}: {str(e)}")
            logging.debug(traceback.format_exc())
        
    def _on_threshold_changed(self, value):
        self.core.set_threshold(value)
        
    def _on_kill_process(self):
        selected_rows = self.process_table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请先选择一个进程")
            return
            
        row = selected_rows[0].row()
        pid = int(self.process_table.item(row, 1).text())
        name = self.process_table.item(row, 0).text()
        
        reply = QMessageBox.question(
            self,
            "确认终止进程",
            f"确定要终止进程 {name} (PID: {pid})?\n\n警告: 终止系统进程可能导致系统不稳定。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.statusBar().showMessage(f"正在终止进程 {pid}...")
            if self.core.kill_process(pid):
                QMessageBox.information(self, "成功", f"进程 {pid} 已成功终止")
                self.statusBar().showMessage(f"进程 {pid} 已终止", 3000)
                # 刷新进程列表
                self._force_refresh()
            else:
                QMessageBox.warning(self, "错误", f"无法终止进程 {pid}")
                self.statusBar().showMessage(f"无法终止进程 {pid}", 3000)
                
    def closeEvent(self, event):
        # 停止更新线程
        if hasattr(self, 'update_thread'):
            self.update_thread.stop()
        
        # 关闭核心监控
        if hasattr(self, 'core'):
            self.core.shutdown()
            
        event.accept()

def check_admin():
    try:
        return os.getuid() == 0
    except AttributeError:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0

def main():
    try:
        # 检查是否具有管理员权限
        if not check_admin():
            logging.warning("Application not running with administrator privileges")
            if sys.platform == 'win32':
                message = ("建议使用管理员权限运行此程序以获取完整功能。\n"
                         "请右键点击程序 -> '以管理员身份运行'")
            else:
                message = ("建议使用root权限运行此程序以获取完整功能。\n"
                         "请使用 'sudo' 命令运行程序")
            
            if QMessageBox.warning(None, "权限提示", message,
                                 QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Cancel:
                sys.exit(0)
        
        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create("Fusion"))
        
        window = CPUMonitorUI()
        window.show()
        
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Critical error in main: {str(e)}")
        logging.debug(traceback.format_exc())
        QMessageBox.critical(None, "严重错误", f"程序启动失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
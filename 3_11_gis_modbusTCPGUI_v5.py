import sys
import time
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.gridspec import GridSpec
from mpl_toolkits.axes_grid1 import make_axes_locatable
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, 
                            QToolBar, QGroupBox, QGridLayout, QPushButton, QStatusBar, QFrame, 
                            QSplitter, QTabWidget, QComboBox, QLCDNumber, QFileDialog, QMessageBox,
                            QSlider, QCheckBox, QRadioButton, QSpinBox, QDoubleSpinBox, QProgressBar,
                            QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                            QDateTimeEdit, QToolButton, QMenu, QAction)
from PyQt5.QtCore import QTimer, Qt, QDateTime, QSize, QDate
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QPixmap, QTextCursor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.transaction import ModbusSocketFramer
from pymodbus.pdu import ModbusRequest
from pymodbus.exceptions import ModbusIOException
import struct
import csv
import os
from datetime import datetime
import io
import requests
import resources_rc

# 设置默认字体为SimHei（或其他支持中文的字体）
plt.rcParams['font.sans-serif'] = ['SimHei']
# 解决负号"-"显示为方块的问题
plt.rcParams['axes.unicode_minus'] = False

# 自定义 Modbus TCP 请求
class CustomModbusRequest(ModbusRequest):
    function_code = 4

    def __init__(self, address, count, unit):
        ModbusRequest.__init__(self)
        self.address = address
        self.count = count
        self.unit_id = unit

    def encode(self):
        return struct.pack('>HH', self.address, self.count)

    def decode(self, data):
        self.address, self.count = struct.unpack('>HH', data)

    def execute(self, context):
        raise NotImplementedError("Custom request not implemented")

# 配置 Modbus TCP 客户端
client = ModbusTcpClient('192.168.0.150', port=6789, framer=ModbusSocketFramer)

# 连接到 Modbus 服务器
client.connect()

# 全局变量存储放电次数，uhf_db和相位数据
discharge_counts = []
uhf_db_values = []
phase_values = []


# 配置50组寄存器
TELEMETRY_REGISTERS = []
for i in range(50):
    base_addr = 100 + i * 6
    TELEMETRY_REGISTERS.append({
        '放电次数': {'addr': base_addr, 'type': 'int16'},
        'reserve': {'addr': base_addr + 1, 'type': 'int16'},
        'uhf_db': {'addr': base_addr + 2, 'type': 'float32', 'endian': 'big'},
        '相位': {'addr': base_addr + 4, 'type': 'float32', 'endian': 'big'},
    })

def send_wake_up_sequence(client):
    """
    发送唤醒指令 0xFF, 0xFE, 0xFF, 0xFE，并等待5秒。
    """
    wake_up_sequence = bytes([0xFF, 0xFE, 0xFF, 0xFE])
    try:
        client.socket.sendall(wake_up_sequence)
        print("唤醒指令发送成功")
        print("等待5秒...")
        time.sleep(5)  # 等待5秒
        response = client.socket.recv(1024)  # 接收回复内容
        print(f"收到回复: {response.hex()}")
        
    except Exception as e:
        print(f"发送唤醒指令失败: {e}")
        client.close()  # 发送失败时关闭连接
        client.connect()  # 重新连接

def parse_registers(data):
    for group in TELEMETRY_REGISTERS:
        for name, config in group.items():
            addr = config['addr']
            try:
                if config['type'] == 'int16':
                    value = int.from_bytes(data[(addr-100)*2:(addr-100)*2+2], byteorder='big')
                    if name == '放电次数':
                        discharge_counts.append(value)
                elif config['type'] == 'float32':
                    # 处理浮点数寄存器数据
                    result = struct.unpack('>HH', data[(addr-100)*2:(addr-100)*2+4])
                    adjusted_bytes = struct.pack('>HH', result[1], result[0])
                    value = struct.unpack('>f', adjusted_bytes)[0]
                    if name == 'uhf_db':
                        uhf_db_values.append(round(value,2))
                    elif name == '相位':
                        phase_values.append(value)
                raw_data = data[(addr-100)*2:(addr-100)*2+4] if config['type'] == 'float32' else data[(addr-100)*2:(addr-100)*2+2]
                print(f"寄存器地址 {addr}: {value} ({name}), 原始报文: {raw_data.hex()}")
            except struct.error:
                print(f"寄存器地址 {addr}: 数据不足，无法解析, 原始报文: {data[(addr-100)*2:].hex()}")

def read_data(client):
    # 清空全局变量列表，避免数据不断累积
    global discharge_counts, uhf_db_values, phase_values
    discharge_counts = []
    uhf_db_values = []
    phase_values = []
    
    send_wake_up_sequence(client)
    time.sleep(1)
    request = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x02, 0x04, 0x00, 0x64, 0x01, 0x8F])
    client.socket.sendall(request)
    response = client.socket.recv(1024)
    print(f"收到回复: {response}")
    if len(response) > 9:
        data = response[9:]  # 跳过前9个字节
        parse_registers(data)
    else:
        print("回复内容长度不足，无法解析")

# 自定义输出重定向类
class OutputRedirector(io.StringIO):
    def __init__(self, text_widget, out_type):
        super(OutputRedirector, self).__init__()
        self.text_widget = text_widget
        self.out_type = out_type
        self.buf = ""

    def write(self, text):
        self.buf += text
        if text.endswith('\n'):
            self.text_widget.append(self.buf.rstrip())
            self.text_widget.moveCursor(QTextCursor.End)
            self.buf = ""
        return len(text)

    def flush(self):
        if self.buf:
            self.text_widget.append(self.buf)
            self.text_widget.moveCursor(QTextCursor.End)
            self.buf = ""

# 自定义 Matplotlib 画布类
class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.fig.set_facecolor('#f0f0f0')
        # 使用GridSpec来控制子图的大小和位置
        gs = GridSpec(1, 2, width_ratios=[1, 1])  # 1行2列，宽度比例1:1
        self.ax1 = self.fig.add_subplot(gs[0, 0])  # 左侧PRPD图
        self.ax2 = self.fig.add_subplot(gs[0, 1], projection='3d')  # 右侧PRPS图
        self.colorbar = None  # 添加colorbar属性以便跟踪和管理
        super(MplCanvas, self).__init__(self.fig)
        self.setStyleSheet("background-color: #f0f0f0;")
        
        # 初始化图表显示
        self.setup_prpd_plot()
        self.setup_prps_plot()
        
        # 调整布局
        self.fig.tight_layout()
        self.fig.subplots_adjust(wspace=0.3)
        
    def setup_prpd_plot(self):
        """设置PRPD图的基本显示信息"""
        self.ax1.set_xlabel('相位 (°)', fontsize=12)
        self.ax1.set_ylabel('幅值 (dB)', fontsize=12)
        self.ax1.set_xlim(0, 360)
        self.ax1.set_ylim(0, 80)
        self.ax1.set_title('PRPD图 (相位分辨局部放电)', fontsize=14, fontweight='bold')
        self.ax1.grid(True, linestyle='--', alpha=0.7)
        
        # 添加参考波形
        x = np.linspace(0, 360, 1000)
        y = 40 + 40 * np.sin(np.radians(x))
        self.ax1.plot(x, y, 'r-', label='参考波形', linewidth=2, alpha=0.5)
        self.ax1.legend(loc='upper right')
        
    def setup_prps_plot(self):
        """设置PRPS图的基本显示信息"""
        self.ax2.set_title('PRPS图 (相位分辨局部放电谱)', fontsize=14, fontweight='bold')
        self.ax2.set_xlabel('相位 (°)', fontsize=12)
        self.ax2.set_ylabel('周期', fontsize=12)
        self.ax2.set_zlabel('幅值 (dB)', fontsize=12)
        self.ax2.set_xlim(0, 360)
        self.ax2.set_ylim(0, 50)
        self.ax2.set_zlim(0, 80)

# 局部放电类型识别函数
def recognize_pd_type(image_path):
    """
    发送图像到FastAPI服务进行局部放电类型识别
    """
    url = 'http://127.0.0.1:9000/api/v1/predict'  # FastAPI服务地址
    
    try:
        with open(image_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(url, files=files)
            response.raise_for_status()  # 如果请求失败则抛出异常
            data = response.json()
            return data
    except FileNotFoundError:
        print(f"错误：文件未找到，请检查路径 '{image_path}' 是否正确。")
        return {"error": "文件未找到"}
    except requests.exceptions.ConnectionError:
        print(f"错误：无法连接到服务器 {url}。请确保API服务正在运行并且地址正确。")
        return {"error": "连接服务器失败"}
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP错误：{http_err}")
        return {"error": f"HTTP错误：{http_err}"}
    except Exception as e:
        print(f"发生未知错误：{e}")
        return {"error": f"未知错误：{e}"}

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GIS局放监测系统 v1.2")
        # 设置窗口图标
        self.setWindowIcon(QIcon(':images/GIS_PD.ico'))
        self.setGeometry(100, 100, 1280, 720)
        
        # 初始化局放类型识别相关变量
        self.pd_image_path = "temp_pd_image.jpg"
        self.api_url = "http://127.0.0.1:9000/api/v1/predict"
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QLabel {
                font-family: 'Microsoft YaHei';
                font-size: 14px;
                color: #333333;
            }
            QGroupBox {
                font-family: 'Microsoft YaHei';
                font-size: 14px;
                font-weight: bold;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
                color: #3498db;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QLCDNumber {
                background-color: #2c3e50;
                color: #ecf0f1;
                border: 2px solid #34495e;
                border-radius: 5px;
            }
            QTabWidget::pane {
                border: 1px solid #3498db;
                background-color: #f8f9fa;
                border-radius: 5px;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                border: 1px solid #b4b4b4;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 100px;
                padding: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #3498db;
                color: white;
            }
            QTabBar::tab:!selected {
                margin-top: 2px;
            }
            QProgressBar {
                border: 2px solid #2c3e50;
                border-radius: 5px;
                text-align: center;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                width: 10px;
                margin: 0.5px;
            }
            QCheckBox, QRadioButton {
                font-family: 'Microsoft YaHei';
                font-size: 14px;
            }
            QSpinBox, QDoubleSpinBox, QComboBox {
                border: 1px solid #3498db;
                border-radius: 3px;
                padding: 3px;
                background-color: white;
            }
            QTextEdit {
                font-family: 'Consolas', 'Microsoft YaHei';
                font-size: 12px;
                background-color: #f8f9fa;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
            }
            QTableWidget {
                font-family: 'Microsoft YaHei';
                font-size: 12px;
                gridline-color: #d0d0d0;
                selection-background-color: #3498db;
                selection-color: white;
            }
            QHeaderView::section {
                background-color: #e0e0e0;
                padding: 4px;
                border: 1px solid #bdc3c7;
                font-weight: bold;
            }
        """)

        # 创建中央部件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 创建主布局
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # 初始化数据记录
        self.recording = False
        self.record_data = []
        
        # 初始化进度条值
        self.progress_value = 0
        
        # 初始化日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        
        # 添加PRPD历史数据存储
        self.prpd_history = []  # 用于存储历史数据
        self.max_history = 5    # 最大历史记录数
        
        # 重定向标准输出到文本区域
        self.stdout_redirector = OutputRedirector(self.log_text, "stdout")
        self.stderr_redirector = OutputRedirector(self.log_text, "stderr")
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stderr_redirector
        
        # 创建顶部信息面板
        self.create_info_panel()
        
        # 创建中间内容区域
        self.create_content_area()
        
        # 创建底部状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("系统状态: 正常运行中")
        
        # 创建定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(1000)  # 每秒更新一次
        
        # 创建时间更新定时器
        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)  # 每秒更新一次
        
        # 初始化时间显示
        self.update_time()

    def create_info_panel(self):
        # 创建顶部信息面板
        info_panel = QGroupBox("系统信息")
        info_layout = QGridLayout()
        
        # 添加时间显示
        self.time_label = QLabel("当前时间: ")
        self.time_value = QLabel()
        self.time_value.setStyleSheet("font-weight: bold; color: #2c3e50;")
        info_layout.addWidget(self.time_label, 0, 0)
        info_layout.addWidget(self.time_value, 0, 1)
        
        # 添加连接状态
        connection_label = QLabel("连接状态: ")
        self.connection_value = QLabel("已连接")
        self.connection_value.setStyleSheet("font-weight: bold; color: green;")
        info_layout.addWidget(connection_label, 0, 2)
        info_layout.addWidget(self.connection_value, 0, 3)
        
        # 添加IP地址显示
        ip_label = QLabel("服务器IP: ")
        ip_value = QLabel("192.168.0.150:6789")
        ip_value.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(ip_label, 0, 4)
        info_layout.addWidget(ip_value, 0, 5)
        
        # 添加数据面板
        data_panel = QGroupBox("监测数据")
        data_layout = QGridLayout()
        
        # 放电次数显示
        discharge_label = QLabel("放电次数总和:")
        self.discharge_lcd = QLCDNumber()
        self.discharge_lcd.setDigitCount(8)
        self.discharge_lcd.setSegmentStyle(QLCDNumber.Flat)
        data_layout.addWidget(discharge_label, 0, 0)
        data_layout.addWidget(self.discharge_lcd, 0, 1)
        
        # UHF_DB最大值显示
        uhf_db_label = QLabel("UHF_DB最大值:")
        self.uhf_db_lcd = QLCDNumber()
        self.uhf_db_lcd.setDigitCount(8)
        self.uhf_db_lcd.setSegmentStyle(QLCDNumber.Flat)
        data_layout.addWidget(uhf_db_label, 0, 2)
        data_layout.addWidget(self.uhf_db_lcd, 0, 3)
        
        # 设置数据面板
        data_panel.setLayout(data_layout)
        
        # 设置信息面板
        info_panel.setLayout(info_layout)
        
        # 添加到主布局
        self.main_layout.addWidget(info_panel)
        self.main_layout.addWidget(data_panel)

    def create_content_area(self):
        # 创建中间内容区域
        content_splitter = QSplitter(Qt.Horizontal)
        
        # 创建左侧控制面板
        control_panel = self.create_control_panel()
        
        # 创建右侧图表区域
        chart_panel = self.create_chart_area()
        
        # 添加到分割器
        content_splitter.addWidget(control_panel)
        content_splitter.addWidget(chart_panel)
        
        # 设置分割比例
        content_splitter.setSizes([250, 750])
        
        # 添加到主布局
        self.main_layout.addWidget(content_splitter)

    def create_control_panel(self):
        # 创建左侧控制面板
        control_panel = QGroupBox("控制面板")
        control_layout = QVBoxLayout()
        
        # 创建连接控制
        connection_group = QGroupBox("连接控制")
        connection_layout = QVBoxLayout()
        
        # 添加连接按钮
        connect_button = QPushButton("连接设备")
        connect_button.clicked.connect(self.connect_device)
        connection_layout.addWidget(connect_button)
        
        # 添加断开按钮
        disconnect_button = QPushButton("断开连接")
        disconnect_button.clicked.connect(self.disconnect_device)
        connection_layout.addWidget(disconnect_button)
        
        # 设置连接控制组
        connection_group.setLayout(connection_layout)
        control_layout.addWidget(connection_group)
        
        # 创建显示设置
        display_group = QGroupBox("显示设置")
        display_layout = QVBoxLayout()
        
        # 添加显示选项
        self.show_prpd = QCheckBox("显示PRPD图")
        self.show_prpd.setChecked(True)
        display_layout.addWidget(self.show_prpd)
        
        self.show_accumulated_prpd = QCheckBox("显示累加PRPD图")
        self.show_accumulated_prpd.setChecked(False)
        display_layout.addWidget(self.show_accumulated_prpd)
        
        self.show_prps = QCheckBox("显示PRPS图")
        self.show_prps.setChecked(True)
        display_layout.addWidget(self.show_prps)
        
        # self.show_reference = QCheckBox("显示参考波形")
        # self.show_reference.setChecked(True)
        # display_layout.addWidget(self.show_reference)
        
        # 设置显示设置组
        display_group.setLayout(display_layout)
        control_layout.addWidget(display_group)
        
        # 添加刷新率控制
        refresh_group = QGroupBox("刷新率设置")
        refresh_layout = QVBoxLayout()
        
        refresh_label = QLabel("刷新间隔 (ms):")
        refresh_layout.addWidget(refresh_label)
        
        self.refresh_rate = QSpinBox()
        self.refresh_rate.setRange(100, 5000)
        self.refresh_rate.setValue(1000)
        self.refresh_rate.setSingleStep(100)
        self.refresh_rate.valueChanged.connect(self.change_refresh_rate)
        refresh_layout.addWidget(self.refresh_rate)
        
        # 设置刷新率组
        refresh_group.setLayout(refresh_layout)
        control_layout.addWidget(refresh_group)
        
        # 创建局部放电类型识别模块
        recognition_group = QGroupBox("局放类型识别")
        recognition_layout = QVBoxLayout()
        
        # 添加识别按钮
        self.recognize_button = QPushButton("识别当前局放类型")
        self.recognize_button.clicked.connect(self.recognize_pd_type)
        recognition_layout.addWidget(self.recognize_button)
        
        # 添加识别结果显示
        result_label = QLabel("识别结果:")
        recognition_layout.addWidget(result_label)
        
        self.pd_type_label = QLabel("未识别")
        self.pd_type_label.setStyleSheet("font-weight: bold; color: #e74c3c; font-size: 16px;")
        recognition_layout.addWidget(self.pd_type_label)
        
        # 添加置信度显示
        confidence_label = QLabel("置信度:")
        recognition_layout.addWidget(confidence_label)
        
        self.confidence_label = QLabel("0%")
        self.confidence_label.setStyleSheet("font-weight: bold; color: #2980b9; font-size: 16px;")
        recognition_layout.addWidget(self.confidence_label)
        
        # 添加API服务器状态
        api_status_label = QLabel("API服务状态:")
        recognition_layout.addWidget(api_status_label)
        
        self.api_status = QLabel("未连接")
        self.api_status.setStyleSheet("color: #e74c3c;")
        recognition_layout.addWidget(self.api_status)
        
        # 添加API服务器连接按钮
        self.check_api_button = QPushButton("检查API服务")
        self.check_api_button.clicked.connect(self.check_api_connection)
        recognition_layout.addWidget(self.check_api_button)
        
        # 设置识别模块组
        recognition_group.setLayout(recognition_layout)
        control_layout.addWidget(recognition_group)
        
        # 添加关于按钮
        about_button = QPushButton("关于系统")
        about_button.clicked.connect(self.show_about)
        control_layout.addWidget(about_button)
        
        # 添加弹性空间
        control_layout.addStretch()
        
        # 设置控制面板
        control_panel.setLayout(control_layout)
        
        return control_panel

    def create_chart_area(self):
        # 创建图表区域
        chart_panel = QGroupBox("图表显示")
        chart_layout = QVBoxLayout()
        
        # 创建PRPD图表区域
        prpd_container = QWidget()
        prpd_layout = QVBoxLayout()
        
        # 创建自定义画布
        self.canvas = MplCanvas(self, width=10, height=6, dpi=100)
        self.ax1 = self.canvas.ax1
        self.ax2 = self.canvas.ax2
        
        # 创建工具栏
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # 添加到PRPD布局
        prpd_layout.addWidget(self.toolbar)
        prpd_layout.addWidget(self.canvas)
        
        # 添加日志区域
        log_group = QGroupBox("系统日志")
        log_layout = QVBoxLayout()
        
        # 添加日志工具栏
        log_toolbar = QHBoxLayout()
        
        # 添加清除日志按钮
        clear_log_button = QPushButton("清除日志")
        clear_log_button.clicked.connect(self.clear_log)
        log_toolbar.addWidget(clear_log_button)
        
        # 添加保存日志按钮
        save_log_button = QPushButton("保存日志")
        save_log_button.clicked.connect(self.save_log)
        log_toolbar.addWidget(save_log_button)
        
        # 添加自动滚动选项
        self.auto_scroll = QCheckBox("自动滚动")
        self.auto_scroll.setChecked(True)
        log_toolbar.addWidget(self.auto_scroll)
        
        log_toolbar.addStretch()
        
        # 添加日志工具栏到布局
        log_layout.addLayout(log_toolbar)
        
        # 添加日志文本区域到布局
        log_layout.addWidget(self.log_text)
        
        # 设置日志组
        log_group.setLayout(log_layout)
        
        # 设置PRPD容器
        prpd_container.setLayout(prpd_layout)
        
        # 创建垂直分割器
        chart_splitter = QSplitter(Qt.Vertical)
        chart_splitter.addWidget(prpd_container)
        chart_splitter.addWidget(log_group)
        chart_splitter.setSizes([600, 200])
        
        # 添加到图表布局
        chart_layout.addWidget(chart_splitter)
        
        # 设置图表面板
        chart_panel.setLayout(chart_layout)
        
        return chart_panel

    def update_time(self):
        current_time = QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')
        self.time_value.setText(current_time)

    def update_plot(self):
        try:
            # 调用原始的read_data函数，输出会被重定向到日志区域
            read_data(client)
            discharge_counts_sum = sum(discharge_counts)
            uhf_db_max = max(uhf_db_values) if uhf_db_values else 0.0
            print(f"放电次数总和: {discharge_counts_sum}")
            print(f"uhf_db最大值: {uhf_db_max}")

            # 更新LCD显示
            self.discharge_lcd.display(discharge_counts_sum)
            self.uhf_db_lcd.display(f"{uhf_db_max:.2f}")

            # 如果正在记录，添加数据
            if self.recording and phase_values and uhf_db_values:
                current_time = QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')
                for i in range(min(len(phase_values), len(uhf_db_values))):
                    self.record_data.append({
                        '时间': current_time,
                        '相位': phase_values[i],
                        '幅值': uhf_db_values[i],
                        '放电次数': discharge_counts_sum
                    })

            # 更新PRPD图
            if self.show_prpd.isChecked():
                self.ax1.clear()
                # 重新设置PRPD图的基本显示信息
                self.canvas.setup_prpd_plot()
                
                # 如果存在之前的colorbar，先移除它
                if hasattr(self.canvas, 'colorbar') and self.canvas.colorbar is not None:
                    try:
                        self.canvas.colorbar.remove()
                    except:
                        pass  # 如果移除失败，忽略错误
                    self.canvas.colorbar = None
                
                if phase_values and uhf_db_values:
                    # 更新历史数据
                    if self.show_accumulated_prpd.isChecked():
                        # 添加新数据到历史记录
                        self.prpd_history.append((phase_values.copy(), uhf_db_values.copy()))
                        # 保持历史记录在指定长度内
                        if len(self.prpd_history) > self.max_history:
                            self.prpd_history.pop(0)
                        
                        # 合并所有历史数据
                        all_phases = []
                        all_uhf_dbs = []
                        for hist_phase, hist_uhf in self.prpd_history:
                            all_phases.extend(hist_phase)
                            all_uhf_dbs.extend(hist_uhf)
                        
                        # 绘制累加的散点图
                        scatter = self.ax1.scatter(all_phases, all_uhf_dbs, c=all_uhf_dbs, 
                                                 cmap='viridis', alpha=0.7, s=50, edgecolors='w')
                        # 更新标题显示累加次数
                        self.ax1.set_title(f'PRPD图 (相位分辨局部放电) - 累加模式 ({len(self.prpd_history)}次)', 
                                         fontsize=14, fontweight='bold')
                    else:
                        # 清空历史数据
                        self.prpd_history = []
                        # 只绘制当前数据
                        scatter = self.ax1.scatter(phase_values, uhf_db_values, c=uhf_db_values, 
                                                 cmap='viridis', alpha=0.7, s=50, edgecolors='w')
                    
                    # 使用固定位置创建colorbar，避免挤压主图
                    divider = make_axes_locatable(self.ax1)
                    cax = divider.append_axes("right", size="5%", pad=0.05)
                    self.canvas.colorbar = self.canvas.fig.colorbar(scatter, cax=cax, label='幅值 (dB)')
                
            # 更新PRPS图
            if self.show_prps.isChecked():
                self.ax2.clear()
                # 重新设置PRPS图的基本显示信息
                self.canvas.setup_prps_plot()
                
                if phase_values and uhf_db_values:
                    colors = plt.cm.viridis(np.array(uhf_db_values) / max(uhf_db_values) if max(uhf_db_values) > 0 else 0)
                    self.ax2.bar3d(
                        phase_values, 
                        np.arange(len(phase_values)) % 50, 
                        np.zeros(len(uhf_db_values)), 
                        5, 1, uhf_db_values, 
                        shade=True, 
                        color=colors,
                        alpha=0.8
                    )
            
            # 调整图表布局，使用固定的布局比例
            self.canvas.fig.tight_layout()
            # 确保两个子图的宽度比例保持不变
            self.canvas.fig.subplots_adjust(wspace=0.3)  # 增加子图之间的间距
            self.canvas.draw()
        except Exception as e:
            import traceback
            print(f"更新图表时发生错误: {str(e)}")
            print(traceback.format_exc())
            self.status_bar.showMessage(f"更新图表时发生错误: {str(e)}")
    
    # 数据视图相关功能已移除
    def clear_log(self):
        # 清空日志
        self.log_text.clear()
        self.status_bar.showMessage("日志已清空")
    
    def save_log(self):
        # 保存日志到文本文件
        file_name, _ = QFileDialog.getSaveFileName(self, "保存日志", 
                                                  f"GIS局放日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", 
                                                  "文本文件 (*.txt)")
        if file_name:
            try:
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                self.status_bar.showMessage(f"日志已成功保存到 {file_name}")
            except Exception as e:
                QMessageBox.critical(self, "保存错误", f"保存日志时发生错误: {str(e)}")

    def connect_device(self):
        try:
            if not client.connect():
                client.close()
                client.connect()
            self.connection_value.setText("已连接")
            self.connection_value.setStyleSheet("font-weight: bold; color: green;")
            self.status_bar.showMessage("设备连接成功")
        except Exception as e:
            self.connection_value.setText("连接失败")
            self.connection_value.setStyleSheet("font-weight: bold; color: red;")
            self.status_bar.showMessage(f"设备连接失败: {str(e)}")

    def disconnect_device(self):
        try:
            client.close()
            self.connection_value.setText("已断开")
            self.connection_value.setStyleSheet("font-weight: bold; color: red;")
            self.status_bar.showMessage("设备已断开连接")
        except Exception as e:
            self.status_bar.showMessage(f"断开连接失败: {str(e)}")

    def toggle_recording(self):
        if not self.recording:
            self.recording = True
            self.record_button.setText("停止记录")
            self.record_button.setStyleSheet("background-color: #e74c3c; color: white;")
            self.record_data = []
            self.status_bar.showMessage("开始记录数据...")
        else:
            self.recording = False
            self.record_button.setText("开始记录")
            self.record_button.setStyleSheet("")
            self.status_bar.showMessage(f"数据记录已停止，共记录 {len(self.record_data)} 条数据")

    def export_data(self):
        if not self.record_data:
            QMessageBox.warning(self, "导出失败", "没有可导出的数据，请先记录数据")
            return
            
        file_name, _ = QFileDialog.getSaveFileName(self, "导出数据", 
                                                  f"GIS局放数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                                  "CSV文件 (*.csv)")
        if file_name:
            try:
                with open(file_name, 'w', newline='', encoding='utf-8-sig') as csvfile:
                    fieldnames = ['时间', '相位', '幅值', '放电次数']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    for data in self.record_data:
                        writer.writerow(data)
                self.status_bar.showMessage(f"数据已成功导出到 {file_name}")
            except Exception as e:
                QMessageBox.critical(self, "导出错误", f"导出数据时发生错误: {str(e)}")

    def change_refresh_rate(self, value):
        self.timer.stop()
        self.timer.start(value)
        self.status_bar.showMessage(f"刷新率已更新为 {value} 毫秒")

    def show_about(self):
        QMessageBox.about(self, "关于系统", 
                         "GIS局放监测系统 v1.2\n\n"
                         "本系统用于监测GIS设备的局部放电情况，提供实时数据显示和分析功能。\n\n"
                         "集成了局部放电类型识别功能。\n\n"
                         "© 2025 南京固攀电力设备监测团队")
        
    def check_api_connection(self):
        """检查API服务连接状态"""
        try:
            response = requests.get(self.api_url.replace('/api/v1/predict', '/docs'))
            if response.status_code == 200:
                self.api_status.setText("已连接")
                self.api_status.setStyleSheet("color: green;")
                return True
            else:
                self.api_status.setText("连接失败")
                self.api_status.setStyleSheet("color: #e74c3c;")
                return False
        except requests.exceptions.ConnectionError:
            self.api_status.setText("未连接")
            self.api_status.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "连接错误", "无法连接到API服务，请确保服务已启动。")
            return False
        except Exception as e:
            self.api_status.setText("连接错误")
            self.api_status.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "连接错误", f"连接API服务时发生错误: {str(e)}")
            return False
    
    def recognize_pd_type(self):
        """识别当前局放类型"""
        # 首先检查API连接
        if not self.check_api_connection():
            return
        
        # 保存当前PRPD图像
        try:
            # 获取当前图表并保存为图像
            self.canvas.fig.savefig(self.pd_image_path, dpi=100, bbox_inches='tight')
            print(f"已保存PRPD图像到: {self.pd_image_path}")
            
            # 调用识别函数
            result = recognize_pd_type(self.pd_image_path)
            
            if 'error' in result:
                QMessageBox.warning(self, "识别错误", f"识别过程中发生错误: {result['error']}")
                return
            
            # 更新UI显示识别结果
            pd_type = result.get('predicted_category', '未知')
            confidence = result.get('predicted_probability', '0%')
            
            # 转换英文类型为中文显示
            pd_type_map = {
                'corona': '电晕放电',
                'particle': '颗粒放电',
                'floating': '悬浮放电',
                'surface': '沿面放电',
                'void': '气隙放电'
            }
            
            pd_type_cn = pd_type_map.get(pd_type, pd_type)
            
            self.pd_type_label.setText(pd_type_cn)
            self.confidence_label.setText(confidence)
            
            # 根据不同类型设置不同颜色
            type_colors = {
                '电晕放电': '#3498db',  # 蓝色
                '颗粒放电': '#e74c3c',  # 红色
                '悬浮放电': '#2ecc71',  # 绿色
                '沿面放电': '#f39c12',  # 橙色
                '气隙放电': '#9b59b6'   # 紫色
            }
            
            color = type_colors.get(pd_type_cn, '#e74c3c')
            self.pd_type_label.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 16px;")
            
            # 在状态栏显示识别成功信息
            self.status_bar.showMessage(f"局放类型识别成功: {pd_type_cn}，置信度: {confidence}")
            
        except Exception as e:
            QMessageBox.warning(self, "识别错误", f"识别过程中发生错误: {str(e)}")
            print(f"识别错误: {str(e)}")
            self.status_bar.showMessage("局放类型识别失败")
        
    def closeEvent(self, event):
        # 恢复标准输出
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # 使用Fusion风格
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

# 关闭连接
client.close()

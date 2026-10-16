# 在线解析雷达数据

## 准备

复制示例配置文件并修改参数：
```bash
cp config/sample_config.example.ini config/sample_config.ini
```

编辑 `config/sample_config.ini` 配置数据源及参数。

#### 以太网连接式激光雷达

设置 `source_type = network` 并配置 `[network]` 节：

```ini
[source_type]
source_type = network

[network]
device_ip_address = 192.168.1.201       # 激光雷达IP
ptc_port = 9347                          # PTC协议端口
udp_port = 2368                          # 点云数据目的端口
multicast_ip_address =                   # 可选项：如果目的IP为组播IP
use_ptc_connected = true                 # 是否使用PTC连接
correction_file_path = /path/to/correction.csv   # 角度修正文件（建议使用雷达自身的角度修正文件）
firetimes_path = /path/to/firetimes.csv          # 可选项：通道发光时序（发光时刻修正文件）
host_ip_address =                        # 雷达ip地址，如果与点云源IP相同，则忽略
fault_message_port = 0                   # fault message目的端口，如果与udp_port相同，则忽略
ptc_mode = tcp                           # PTC通信类型，如果不使用基于TLS/mTLS的PTCS，可忽略
certFile =                               # PTCS的一些配置，如果不使用则忽略
privateKeyFile =
caFile =
```

#### 串口连接式激光雷达 (JT16)

设置 `source_type = serial` 并配置 `[serial]` 节：

```ini
[source_type]
source_type = serial

[serial]
rs485_com = /dev/ttyUSB0                 # RS485 点云串口 (在Windows系统中是COM0)，串口号以实际为准
rs232_com = /dev/ttyUSB1                 # RS232 控制串口 (在Windows系统中是COM1)，串口号以实际为准
point_cloud_baudrate = 3125000           # 点云波特率
correction_save_path =                   # 雷达内部角度校准文件保存路径，如果设置232端口且成功从雷达获取角度校准文件
correction_file_path = /path/to/correction.csv  # 角度修正文件（建议使用雷达自身的角度修正文件）
```

## 操作
```bash
# 1. 构建可执行示例程序 (从build文件夹下)：成功编译后，生成可执行程序
make -j$(nproc)

# 2. 执行示例程序：开始解析数据（必须指定配置文件）
./sample /path/to/sample_config.ini
```

## 更多参考

完整配置文件参数请参考 [sample_config.example.ini](../config/sample_config.example.ini)

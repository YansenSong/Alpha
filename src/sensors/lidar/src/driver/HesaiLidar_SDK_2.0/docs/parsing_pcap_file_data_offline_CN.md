# 离线解析PCAP点云数据

## 准备

复制示例配置文件并修改参数：
```bash
cp config/sample_config.example.ini config/sample_config.ini
```

编辑 `config/sample_config.ini`，设置 `source_type = pcap` 并配置 `[pcap]` 节：

```ini
[source_type]
source_type = pcap

[pcap]
pcap_path = /path/to/your.pcap                   # 离线PCAP点云数据路径
correction_file_path = /path/to/correction.csv   # 校准文件（角度修正文件），建议使用雷达自身的校准文件
firetimes_path = /path/to/firetimes.csv          # 可选项：通道发光时序（发光时刻修正文件）

[decoder]
pcap_play_synchronization = true                 # 根据点云时间戳同步解析，模拟雷达实际频率
pcap_play_in_loop = false                        # 循环解析PCAP
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

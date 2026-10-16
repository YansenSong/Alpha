# 可视化点云数据
本文档展示如何利用PCL可视化点云

## 准备

复制示例配置文件并修改参数：
```bash
cp config/tool_sample_config.example.ini config/tool_sample_config.ini
```

编辑 `config/tool_sample_config.ini` 配置数据源及可视化选项。

### 1 启用可视化查看工具

配置 `[pcl]` 节启用可视化：

```ini
[pcl]
save_pcd_ascii = false
save_pcd_binary = false
save_pcd_binary_compressed = false
save_ply = false
enable_viewer = true    # 启用可视化查看器
```

### 2 配置数据源

数据源配置参考 **[如何在线解析激光雷达数据](../docs/parsing_lidar_data_online_CN.md)** 和 **[如何离线解析PCAP文件数据](../docs/parsing_pcap_file_data_offline_CN.md)**

以PCAP解析为例：

```ini
[source_type]
source_type = pcap

[pcap]
pcap_path = /path/to/your.pcap
correction_file_path = /path/to/correction.csv
firetimes_path = /path/to/firetimes.csv

[decoder]
pcap_play_synchronization = true
pcap_play_in_loop = false
```


## 操作
### 1 编译
在HesaiLidar_SDK_2.0文件夹下，启动Terminal终端，执行以下指令。
```bash
cd HesaiLidar_SDK_2.0/tool
mkdir build
cd build
cmake ..
make
```

### 2 运行
成功编译后，在build文件夹下运行生成的pcl_tool可执行文件，需指定配置文件。系统会有可视化窗口。
```bash
./pcl_tool /path/to/tool_sample_config.ini
```

## 配置文件参考

完整配置文件参数请参考 [tool_sample_config.example.ini](../config/tool_sample_config.example.ini)

# PCAP转PCD
HesaiLidar_SDK_2.0提供了将PCAP格式文件转换为PCD格式点云的示例代码。

## 准备

复制示例配置文件并修改参数：
```bash
cp config/tool_sample_config.example.ini config/tool_sample_config.ini
```

编辑 `config/tool_sample_config.ini` 配置数据源及PCD选项。

#### 1 配置数据源

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

#### 2 选择需要保存的PCD格式

配置 `[pcl]` 节选择输出格式和选项：

```ini
[pcl]
save_pcd_ascii = true              # 以ASCII格式保存PCD文件
save_pcd_binary = false            # 以二进制格式保存PCD文件
save_pcd_binary_compressed = false # 以压缩二进制格式保存PCD文件
save_ply = false                   # 保存PLY文件
enable_viewer = false              # 启用可视化查看器
pcd_ascii_precision = 16           # ASCII格式数据精度
output_dir = out_pcd               # 输出目录（默认：out_pcd）
output_dir_with_timestamp = false  # 目录名是否带时间后缀（如：out_pcd_2026-05-31_10-12-01）
```

**格式说明：**

1. **`save_pcd_ascii`**  
   以ASCII格式保存PCD文件。ASCII格式是一种文本格式，数据以可读的形式存储，便于调试和查看，但文件体积通常较大，读取和写入速度较慢。

2. **`save_pcd_binary`**  
   以二进制格式保存PCD文件。二进制格式相比ASCII格式更高效，文件体积更小，读写速度更快，但数据不可直接阅读。

3. **`save_pcd_binary_compressed`**  
   以压缩的二进制格式保存PCD文件。这种格式在二进制的基础上进一步压缩数据，进一步减小文件体积。

4. **`save_ply`**  
   保存PLY文件（Polygon File Format或Stanford Triangle Format）。PLY文件是一种常用于存储三维数据的文件格式。

#### 3 选择需要保存的成员变量

当前除默认保存的x y z之外，共支持六种成员变量。这些由 `pcl_tool.cc` 中的代码定义控制。详见后续更多参考。

> 注意：部分成员变量需要先确认雷达是否支持，否则为全0。

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
成功编译后，在build文件夹下运行生成的pcl_tool可执行文件，需指定配置文件。系统会有可视化窗口（如启用）且在build文件夹下生成对应的每帧点云。
```bash
./pcl_tool /path/to/tool_sample_config.ini
```

## 更多参考
#### 1 如何定义ASCII格式的PCD文件数据精度
`writeASCII` 是 `pcl::PCDWriter` 类的一个方法，以下是其常见用法：
```cpp
pcl::PCDWriter writer;
writer.writeASCII("output.pcd", cloud);
```
按默认的方法保存的PCD文件数据精度有限，例如时间戳会表示为科学计数法。

如何更改PCD文件数据精度？在配置文件中设置 `pcd_ascii_precision`：
```ini
[pcl]
pcd_ascii_precision = 16
```

#### 2 如何定义PCD文件名的时间戳
- 以帧头第一个点的时间戳作为PCD文件名显示的时间戳
```cpp
  std::string file_name1 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".pcd";
  std::string file_name2 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".bin";
  std::string file_name3 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".ply";
  std::string file_name4 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ "_compress" + ".bin";
```

- 以该帧内最后一个点的时间戳作为PCD文件名显示的时间戳
```cpp
  std::string file_name1 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ ".pcd";
  std::string file_name2 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ ".bin";
  std::string file_name3 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ ".ply";
  std::string file_name4 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ "_compress" + ".bin";
```

#### 3 如何确认保存的成员变量是否支持

- 确认 `struct PointXYZIT` 中需要的成员变量，例如 `weightFactor`，则其赋值函数为 `set_weightFactor`

- 确认您使用雷达的点云UDP版本号，可通过`wireshark`抓包查看，一般情况下，点云UDP包中前两个字节为0xEE 0xFF，后续两个字节即为版本号(转化为十进制)，我们以 `Pandar128E3X` 为例，版本号为 `1.4`

- 进入文件 [udp1_4_parser.cc](../libhesai/UdpParser/src/udp1_4_parser.cc) 中，搜索 `set_weightFactor` 函数，如果存在代码该雷达支持该字段。

#### 4 如何新增保存的成员变量

以新增成员变量 `addFlag` ，数据类型为 `uint8_t` 为例

- 在本文件中的 `struct PointXYZIT` 中添加需要的成员变量 `uint8_t addFlag;`。在 `POINT_CLOUD_REGISTER_POINT_STRUCT` 中添加 `(std::uint8_t, addFlag, addFlag)`

- 确认您使用雷达的点云UDP版本号，可通过`wireshark`抓包查看，一般情况下，点云UDP包中前两个字节为0xEE 0xFF，后续两个字节即为版本号(转化为十进制)，我们以 `Pandar128E3X` 为例，版本号为 `1.4`

- 进入文件 [general_parser.h](../libhesai/UdpParser/include/general_parser.h) 中，搜索 `DEFINE_MEMBER_CHECKER`，在下方同步添加 `DEFINE_MEMBER_CHECKER(addFlag)` 和 `DEFINE_SET_GET(addFlag, uint8_t)`

- 进入文件 [udp1_4_parser.cc](../libhesai/UdpParser/src/udp1_4_parser.cc) 中，搜索 `ComputeXYZI` 函数，在其中调用`set_addFlag` 函数实现对 `frame.points[point_index_rerank]` 的赋值

#### 5 使用enable_viewer可视化时，出现闪退问题

- 现象

   ```
   当开启enable_viewer时，可视化点云数据时，出现一些VTK相关警告，且程序直接出现core dumped错误，导致程序直接退出。

   一般出现在ubuntu22.04及其以上系统。
   ```

- 解决方法

   ```
   该问题原因为VTK版本与PCL版本不兼容导致的，请使用匹配的版本进行编译。

   以下为一些匹配版本的例子：
      vtk7.1 + pcl1.10.0
      vtk9.1 + pcl1.14.1
   ```

## 配置文件参考

完整配置文件参数请参考 [tool_sample_config.example.ini](../config/tool_sample_config.example.ini)

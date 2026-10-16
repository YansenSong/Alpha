# PCAP 转 LAS/LAZ 格式
HesaiLidar_SDK_2.0 提供了将 PCAP 格式文件转换为 LAS/LAZ 格式点云的示例代码。

## 准备工作

复制示例配置文件并修改参数：
```bash
cp config/tool_sample_config.example.ini config/tool_sample_config.ini
```

编辑 `config/tool_sample_config.ini` 以配置数据源和 LAS 选项。

#### 1 配置数据源

数据源配置请参考 **[如何在线解析雷达数据](../docs/parsing_lidar_data_online_CN.md)** 和 **[如何离线解析 PCAP 文件数据](../docs/parsing_pcap_file_data_offline_CN.md)**

以 PCAP 解析为例：

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

#### 2 配置 LAS 输出选项

配置 `[las]` 部分以选择输出格式和选项：

```ini
[las]
save_las = false                   # 保存 LAS 文件（未压缩）
save_laz = true                    # 保存 LAZ 文件（压缩）
output_dir = out_las               # 输出目录（默认：out_las）
output_dir_with_timestamp = false  # 在目录名后添加时间戳后缀（例如：out_las_2026-05-31_10-12-01）
```

**格式说明：**

1. **`save_las`**  
   以 LAS 格式保存点云文件。LAS（LASer）是存储机载激光雷达数据的行业标准二进制文件格式。它保持完整精度，但文件较大。

2. **`save_laz`**  
   以 LAZ 格式保存点云文件。LAZ 是 LAS 格式的压缩版本，通常可将文件大小减少 7-20 倍，同时保持无损数据压缩。这是推荐的存储高效格式。

**保存的点属性：**

| 属性 | 描述 |
|:-----|:-----|
| X, Y, Z | 点坐标（为保证精度缩放 10000 倍） |
| Intensity | 反射强度值 |
| Point Source ID | 环号/通道号 |
| GPS Time | 点时间戳 |

## 步骤
### 1 编译
在 HesaiLidar_SDK_2.0 文件夹中，打开终端并执行以下命令：
```bash
cd HesaiLidar_SDK_2.0/tool
mkdir build
cd build
cmake ..
make
```

### 2 运行
编译成功后，在 build 文件夹中使用配置文件运行生成的 las_tool 可执行文件。系统将在指定的输出目录中为每帧生成 LAS/LAZ 文件。
```bash
./las_tool /path/to/tool_sample_config.ini
```

启用 GPU 加速（如果编译时支持 CUDA）：
```bash
./las_tool /path/to/tool_sample_config.ini 1
```

## 输出文件

输出文件使用以下命名模式：
```
PointCloudFrame{帧索引}_{帧起始时间戳}.las
PointCloudFrame{帧索引}_{帧起始时间戳}.laz
```

例如：
- `PointCloudFrame0_1609459200.123456.laz`
- `PointCloudFrame1_1609459200.223456.laz`

## 附加参考

#### 1 关于 LAS/LAZ 格式

LAS 是一种开放的二进制格式规范，用于交换三维点云数据。它广泛用于：
- GIS 应用
- 测量和制图
- 自动驾驶
- 点云处理软件（CloudCompare、QGIS、ArcGIS 等）

LAZ 是 LAS 的无损压缩格式，使用针对激光雷达数据优化的专用算法，在不丢失数据的情况下实现显著的压缩比。

#### 2 LAS 文件头信息

生成的 LAS 文件包含以下头信息：
- 点数据格式：1（包含 GPS 时间）
- 点数据记录长度：28 字节
- 缩放因子：X、Y、Z 均为 0.00001
- 生成软件："Hesai SDK"
- 边界框：根据点云数据自动计算

#### 3 查看 LAS/LAZ 文件

您可以使用各种软件查看生成的 LAS/LAZ 文件：

- **CloudCompare**（免费，跨平台）：https://www.cloudcompare.org/
- **QGIS**（免费，GIS 软件）：https://qgis.org/
- **LAStools**（命令行工具）：https://rapidlasso.de/lastools/
- **Potree**（基于 Web 的查看器）：https://potree.github.io/

#### 4 依赖项与 LASlib 安装

las_tool 使用 LASlib 库来读写 LAS/LAZ 文件。**LASlib 是外部依赖，需要单独安装。**

##### 4.1 安装方法

**从源码编译安装 LAStools（推荐）**

```bash
# 克隆仓库
git clone https://github.com/LAStools/LAStools.git
cd LAStools

# 如需特定版本，可以切换到对应 tag
# git checkout v2.0.0

# 编译安装
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install

# 更新动态库缓存
sudo ldconfig
```


##### 4.2 版本兼容性说明

| LAStools 版本 | LAS 格式支持 | API 兼容性 | 备注 |
|:--------------|:-------------|:-----------|:-----|
| v2.0.0+ | LAS 1.0-1.4, LAZ | ✅ 完全兼容 | 推荐版本，CMake 支持完善 |
| v1.8.x | LAS 1.0-1.4, LAZ | ✅ 兼容 | 稳定版本 |
| < v1.8 | LAS 1.0-1.3 | ⚠️ 部分兼容 | 可能缺少某些 API |

**注意事项：**

1. **API 变更**：LAStools 不同版本之间可能存在 API 变更。las_tool 使用的 API 包括：
   - `LASwriteOpener` / `LASreader` - 文件打开器
   - `LASheader` - 文件头操作
   - `LASpoint` - 点数据操作
   - `LASwriter` - 文件写入器

2. **CMake 支持**：早期版本的 LAStools 可能没有提供 `LASlib-config.cmake` 文件，导致 `find_package(LASlib)` 失败。建议使用 v2.0.0 或更新版本。

3. **LAZ 压缩支持**：LAZ 压缩功能需要 LASzip 支持，通常已包含在 LAStools 中。如果单独安装 LASlib，请确保同时安装 LASzip。

##### 4.3 验证安装

编译时如果看到以下信息，说明 LASlib 已正确找到：
```
-- LASlib found, las_tool will be built
```

如果看到以下信息，说明 LASlib 未安装或未被 CMake 找到：
```
-- LASlib not found, las_tool will be skipped
```

##### 4.4 常见问题

**Q: 编译时提示找不到 `lasreader.hpp` 或 `laswriter.hpp`**

A: 检查 LASlib 是否正确安装，头文件通常位于 `/usr/local/include/LASlib/` 或 `/usr/include/LASlib/`。

**Q: 链接时提示 `undefined reference to LASwriter`**

A: 确保 LASlib 库文件已正确安装。可以尝试：
```bash
# 查找库文件
find /usr -name "libLAS*" 2>/dev/null

# 如果库在非标准路径，设置 LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/path/to/LASlib/lib:$LD_LIBRARY_PATH
```

**Q: 运行时提示动态库找不到**

A: 运行 `sudo ldconfig` 更新动态库缓存，或将库路径添加到 `LD_LIBRARY_PATH`。

## 配置文件参考

完整的配置文件参数请参见 [tool_sample_config.example.ini](../config/tool_sample_config.example.ini)

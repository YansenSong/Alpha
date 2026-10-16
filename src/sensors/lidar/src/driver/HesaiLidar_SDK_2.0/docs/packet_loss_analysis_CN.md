# 丢包率统计
丢包率统计功能实现了针对禾赛激光雷达UDP数据的实时丢包统计，基于每个UDP点云数据包中的序列号（UDP Sequence） 字段进行丢包检测和统计


## 准备

统计SDK解析的激光雷达UDP数据的丢包率一共有三种方式。

#### 方法1：统计一段时间内的丢包率和时间戳跳变率

复制示例配置文件并修改参数：
```bash
cp config/sample_config.example.ini config/sample_config.ini
```

编辑 `config/sample_config.ini` 配置数据源并启用丢包检测：

```ini
[source_type]
source_type = network

[network]
device_ip_address = 192.168.1.201
# ... 其他网络参数

[decoder]
enable_packet_loss_tool = true           # 启用丢包统计
enable_packet_timeloss_tool = true       # 启用时间戳跳变检测
packet_timeloss_tool_continue = false    # 时间跳变检测后继续

[packet_loss]
run_time = 15                            # 统计时间（秒），必须 > 0 才启用检测模式
```

数据源配置参考 **[如何在线解析激光雷达数据](../docs/parsing_lidar_data_online_CN.md)** 和 **[如何离线解析PCAP文件数据](../docs/parsing_pcap_file_data_offline_CN.md)**

## 操作
### 1 编译
在HesaiLidar_SDK_2.0文件夹下，启动Terminal终端，执行以下指令。
```bash
cd HesaiLidar_SDK_2.0
mkdir -p build
cd build
cmake ..
make
```

### 2 运行
成功编译后，在build文件夹下运行生成的sample可执行文件，需指定配置文件：
```bash
./sample /path/to/sample_config.ini
```

输出示例：
```log
======== Packet Loss Report ========
Statistics time: 15000 ms
Total received packets: 93229
Sequence loss count: 0
Timestamp loss count: 0
=====================================
```


## 更多参考
#### 方法2：统计1s内两次丢包之间总共的丢包率

编辑配置文件：
```ini
[decoder]
enable_packet_loss_tool = true

[packet_loss]
run_time = 0                             # 设置为0使用持续监控模式
```

当出现丢包时，终端会打印类似如下警告信息：
```log
[WARNING] pkt loss freq: 3 / 56268
```
表示在统计周期1s内，从上一次丢包开始，到下一次新的丢包之间，共丢失了3个包，应收到包的总数为56268

#### 方法3：用户自行增加功能统计丢包率
根据用户自己需求，可增加回调函数，用于在终端输出当前帧丢包率和累计丢包率，例如在[test.cc](../test/test.cc)中增加如下回调函数：
```cpp
void packetLossCallback(const uint32_t& total_packets, const uint32_t& lost_packets) {
  static uint32_t last_total = 0;
  static uint32_t last_loss = 0;

  // Compute packet count and loss since last frame
  uint32_t frame_total = total_packets - last_total;
  uint32_t frame_loss  = lost_packets - last_loss;

  // Update static tracking variables
  last_total = total_packets;
  last_loss  = lost_packets;

  // Calculate loss rates
  double frame_loss_rate = frame_total == 0 ? 0.0 :
                           static_cast<double>(frame_loss) / frame_total * 100.0;
  double total_loss_rate = total_packets == 0 ? 0.0 :
                           static_cast<double>(lost_packets) / total_packets * 100.0;

  // Print results
  printf("[Frame Loss Rate]  %.2f%% (%u / %u)\n", frame_loss_rate, frame_loss, frame_total);
  printf("[Total Loss Rate]  %.2f%% (%u / %u)\n", total_loss_rate, lost_packets, total_packets);
}
```
并调用该回调函数：
```cpp
sample.RegRecvCallback(packetLossCallback);
```
编译和运行方式参考**方法1**。

输出示例:
```log
[Frame Loss Rate]  97.47% (20241 / 20767)
[Total Loss Rate]  2.12% (20241 / 956569)
```

## 配置文件参考

完整配置文件参数请参考 [sample_config.example.ini](../config/sample_config.example.ini)

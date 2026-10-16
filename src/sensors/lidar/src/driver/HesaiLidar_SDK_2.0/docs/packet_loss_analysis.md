# Packet Loss Statistics
The packet loss statistics function implements real-time packet loss statistics for Hesai lidar UDP data, based on packet loss detection and statistics using the sequence number (UDP Sequence) field in each UDP point cloud data packet.


## Preparation

There are three methods to count the packet loss rate of lidar UDP data parsed by the SDK.

#### Method 1: Count packet loss rate and timestamp jump rate within a time period

Copy the example configuration file and modify the parameters:
```bash
cp config/sample_config.example.ini config/sample_config.ini
```

Edit `config/sample_config.ini` to configure data source and enable packet loss detection:

```ini
[source_type]
source_type = network

[network]
device_ip_address = 192.168.1.201
# ... other network parameters

[decoder]
enable_packet_loss_tool = true           # Enable packet loss statistics
enable_packet_timeloss_tool = true       # Enable timestamp jump detection
packet_timeloss_tool_continue = false    # Continue after time loss detection

[packet_loss]
run_time = 15                            # Statistics time in seconds (must be > 0 to enable detection mode)
```

For data source configuration, refer to **[How to Parse Lidar Data Online](../docs/parsing_lidar_data_online.md)** and **[How to Parse PCAP File Data Offline](../docs/parsing_pcap_file_data_offline.md)**

## Steps
### 1 Compilation
In the HesaiLidar_SDK_2.0 folder, open a terminal and execute the following commands:
```bash
cd HesaiLidar_SDK_2.0
mkdir -p build
cd build
cmake ..
make
```

### 2 Run
After successful compilation, run the generated sample executable file in the build folder with the configuration file:
```bash
./sample /path/to/sample_config.ini
```

Output example:
```log
======== Packet Loss Report ========
Statistics time: 15000 ms
Total received packets: 93229
Sequence loss count: 0
Timestamp loss count: 0
=====================================
```


## Additional References
#### Method 2: Count total packet loss rate between two packet losses within 1s

Edit the configuration file:
```ini
[decoder]
enable_packet_loss_tool = true

[packet_loss]
run_time = 0                             # Set to 0 to use continuous monitoring mode
```

When packet loss occurs, the terminal will print warning information similar to the following:
```log
[WARNING] pkt loss freq: 3 / 56268
```
This indicates that within the 1s statistical period, from the last packet loss to the next new packet loss, a total of 3 packets were lost, and the total number of packets that should have been received was 56268.

#### Method 3: Users add functionality to count packet loss rate themselves
According to user requirements, callback functions can be added to output current frame packet loss rate and cumulative packet loss rate in the terminal. For example, add the following callback function in [test.cc](../test/test.cc):
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
And call this callback function:
```cpp
sample.RegRecvCallback(packetLossCallback);
```
Compilation and execution methods refer to **Method 1**.

Output example:
```log
[Frame Loss Rate]  97.47% (20241 / 20767)
[Total Loss Rate]  2.12% (20241 / 956569)
```

## Configuration File Reference

For complete configuration file parameters, see [sample_config.example.ini](../config/sample_config.example.ini)

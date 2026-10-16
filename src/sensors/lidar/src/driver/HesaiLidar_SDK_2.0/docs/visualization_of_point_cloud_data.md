# Point Cloud Data Visualization
This document shows how to visualize point clouds using PCL

## Preparation

Copy the example configuration file and modify the parameters:
```bash
cp config/tool_sample_config.example.ini config/tool_sample_config.ini
```

Edit `config/tool_sample_config.ini` to configure data source and visualization options.

### 1 Enable Visualization Viewer Tool

Configure the `[pcl]` section to enable viewer:

```ini
[pcl]
save_pcd_ascii = false
save_pcd_binary = false
save_pcd_binary_compressed = false
save_ply = false
enable_viewer = true    # Enable visualization viewer
```

### 2 Configure Data Source

For data source configuration, refer to **[How to Parse Lidar Data Online](../docs/parsing_lidar_data_online.md)** and **[How to Parse PCAP File Data Offline](../docs/parsing_pcap_file_data_offline.md)**

Using PCAP parsing as an example:

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


## Steps
### 1 Compilation
In the HesaiLidar_SDK_2.0 folder, open a terminal and execute the following commands:
```bash
cd HesaiLidar_SDK_2.0/tool
mkdir build
cd build
cmake ..
make
```

### 2 Run
After successful compilation, run the generated pcl_tool executable file in the build folder with the configuration file. The system will have a visualization window.
```bash
./pcl_tool /path/to/tool_sample_config.ini
```

## Configuration File Reference

For complete configuration file parameters, see [tool_sample_config.example.ini](../config/tool_sample_config.example.ini)

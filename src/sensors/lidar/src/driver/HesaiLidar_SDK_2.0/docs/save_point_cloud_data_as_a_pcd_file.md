# PCAP to PCD Conversion
HesaiLidar_SDK_2.0 provides sample code for converting PCAP format files to PCD format point clouds.

## Preparation

Copy the example configuration file and modify the parameters:
```bash
cp config/tool_sample_config.example.ini config/tool_sample_config.ini
```

Edit `config/tool_sample_config.ini` to configure data source and PCD options.

#### 1 Configure Data Source

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

#### 2 Select the Required PCD Format

Configure the `[pcl]` section to select output format and options:

```ini
[pcl]
save_pcd_ascii = true              # Save PCD files in ASCII format
save_pcd_binary = false            # Save PCD files in binary format
save_pcd_binary_compressed = false # Save PCD files in compressed binary format
save_ply = false                   # Save PLY files
enable_viewer = false              # Enable visualization viewer
pcd_ascii_precision = 16           # ASCII format data precision
output_dir = out_pcd               # Output directory (default: out_pcd)
output_dir_with_timestamp = false  # Add timestamp suffix to directory name (e.g., out_pcd_2026-05-31_10-12-01)
```

**Format descriptions:**

1. **`save_pcd_ascii`**  
   Saves PCD files in ASCII format. ASCII format is a text format where data is stored in readable form, convenient for debugging and viewing, but usually results in larger file sizes and slower read/write speeds.

2. **`save_pcd_binary`**  
   Saves PCD files in binary format. Binary format is more efficient than ASCII format, with smaller file sizes and faster read/write speeds, but the data is not directly readable.

3. **`save_pcd_binary_compressed`**  
   Saves PCD files in compressed binary format. This format further compresses data based on binary format, further reducing file size.

4. **`save_ply`**  
   Saves PLY files (Polygon File Format or Stanford Triangle Format). PLY files are a file format commonly used for storing three-dimensional data.

#### 3 Select Member Variables to Save

Currently, besides the default saved x, y, z coordinates, six member variables are supported. These are controlled by code definitions in `pcl_tool.cc`. See additional references below for details.

> Note: Some member variables need to be confirmed whether the lidar supports them, otherwise they will be all zeros.

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
After successful compilation, run the generated pcl_tool executable file in the build folder with the configuration file. The system will have a visualization window (if enabled) and generate corresponding point clouds for each frame.
```bash
./pcl_tool /path/to/tool_sample_config.ini
```

## Additional References
#### 1 How to Define Data Precision for ASCII Format PCD Files
`writeASCII` is a method of the `pcl::PCDWriter` class. Here's its common usage:
```cpp
pcl::PCDWriter writer;
writer.writeASCII("output.pcd", cloud);
```
PCD files saved using the default method have limited data precision, for example, timestamps will be represented in scientific notation.

How to change PCD file data precision? Set `pcd_ascii_precision` in the configuration file:
```ini
[pcl]
pcd_ascii_precision = 16
```

#### 2 How to Define Timestamp in PCD Filename
- Use the timestamp of the first point in the frame header as the timestamp displayed in the PCD filename:
```cpp
  std::string file_name1 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".pcd";
  std::string file_name2 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".bin";
  std::string file_name3 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ ".ply";
  std::string file_name4 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_start_timestamp)+ "_compress" + ".bin";
```

- Use the timestamp of the last point in the frame as the timestamp displayed in the PCD filename:
```cpp
  std::string file_name1 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ ".pcd";
  std::string file_name2 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ ".bin";
  std::string file_name3 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ ".ply";
  std::string file_name4 = "./PointCloudFrame" + std::to_string(frame.frame_index) + "_" + std::to_string(frame.frame_end_timestamp)+ "_compress" + ".bin";
```

#### 3 How to Confirm Whether Saved Member Variables are Supported

- Confirm the required member variables in `struct PointXYZIT`, for example `weightFactor`, then its assignment function is `set_weightFactor`

- Confirm the point cloud UDP version number of your lidar, which can be viewed through `wireshark` packet capture. Generally, the first two bytes in point cloud UDP packets are 0xEE 0xFF, and the following two bytes are the version number (converted to decimal). Using `Pandar128E3X` as an example, the version number is `1.4`

- Navigate to file [udp1_4_parser.cc](../libhesai/UdpParser/src/udp1_4_parser.cc), search for the `set_weightFactor` function. If the code exists, the lidar supports this field.

#### 4 How to Add New Saved Member Variables

Taking the addition of member variable `addFlag` with data type `uint8_t` as an example:

- Add the required member variable `uint8_t addFlag;` in `struct PointXYZIT` in this file. Add `(std::uint8_t, addFlag, addFlag)` in `POINT_CLOUD_REGISTER_POINT_STRUCT`

- Confirm the point cloud UDP version number of your lidar, which can be viewed through `wireshark` packet capture. Generally, the first two bytes in point cloud UDP packets are 0xEE 0xFF, and the following two bytes are the version number (converted to decimal). Using `Pandar128E3X` as an example, the version number is `1.4`

- Navigate to file [general_parser.h](../libhesai/UdpParser/include/general_parser.h), search for `DEFINE_MEMBER_CHECKER`, and add `DEFINE_MEMBER_CHECKER(addFlag)` and `DEFINE_SET_GET(addFlag, uint8_t)` below

- Navigate to file [udp1_4_parser.cc](../libhesai/UdpParser/src/udp1_4_parser.cc), search for the `ComputeXYZI` function, and call the `set_addFlag` function within it to implement assignment to `frame.points[point_index_rerank]` 

#### 5 When using enable_viewer for visualization, the program crashes

- Phenomenon

   ```
   When enable_viewer is enabled, while visualizing point cloud data, some VTK-related warnings appear, and the program directly encounters a core dumped error, causing the program to exit immediately.

   This issue usually occurs on Ubuntu 22.04 and above systems.
   ```

- Solution

   ```
   This issue is caused by incompatibility between VTK and PCL versions. Please compile using compatible versions.

   Below are some examples of compatible versions:
      vtk7.1 + pcl1.10.0
      vtk9.1 + pcl1.14.1
   ```

## Configuration File Reference

For complete configuration file parameters, see [tool_sample_config.example.ini](../config/tool_sample_config.example.ini)

# PCAP to LAS/LAZ Conversion
HesaiLidar_SDK_2.0 provides sample code for converting PCAP format files to LAS/LAZ format point clouds.

## Preparation

Copy the example configuration file and modify the parameters:
```bash
cp config/tool_sample_config.example.ini config/tool_sample_config.ini
```

Edit `config/tool_sample_config.ini` to configure data source and LAS options.

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

#### 2 Configure LAS Output Options

Configure the `[las]` section to select output format and options:

```ini
[las]
save_las = false                   # Save LAS files (uncompressed)
save_laz = true                    # Save LAZ files (compressed)
output_dir = out_las               # Output directory (default: out_las)
output_dir_with_timestamp = false  # Add timestamp suffix to directory name (e.g., out_las_2026-05-31_10-12-01)
```

**Format descriptions:**

1. **`save_las`**  
   Saves point cloud files in LAS format. LAS (LASer) is an industry-standard binary file format for storing airborne lidar data. It maintains full precision but results in larger file sizes.

2. **`save_laz`**  
   Saves point cloud files in LAZ format. LAZ is the compressed version of LAS format, typically reducing file sizes by 7-20x while maintaining lossless data compression. This is the recommended format for storage efficiency.

**Point attributes saved:**

| Attribute | Description |
|:----------|:------------|
| X, Y, Z | Point coordinates (scaled by 10000 for precision) |
| Intensity | Return intensity value |
| Point Source ID | Ring/channel number |
| GPS Time | Point timestamp |

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
After successful compilation, run the generated las_tool executable file in the build folder with the configuration file. The system will generate LAS/LAZ files for each frame in the specified output directory.
```bash
./las_tool /path/to/tool_sample_config.ini
```

To enable GPU acceleration (if compiled with CUDA support):
```bash
./las_tool /path/to/tool_sample_config.ini 1
```

## Output Files

The output files are named using the following pattern:
```
PointCloudFrame{frame_index}_{frame_start_timestamp}.las
PointCloudFrame{frame_index}_{frame_start_timestamp}.laz
```

For example:
- `PointCloudFrame0_1609459200.123456.laz`
- `PointCloudFrame1_1609459200.223456.laz`

## Additional References

#### 1 About LAS/LAZ Format

LAS is an open, binary format specification for the interchange of 3-dimensional point cloud data. It is widely used in:
- GIS applications
- Surveying and mapping
- Autonomous driving
- Point cloud processing software (CloudCompare, QGIS, ArcGIS, etc.)

LAZ is a lossless compression of LAS that uses specialized algorithms optimized for lidar data, achieving significant compression ratios without data loss.

#### 2 LAS File Header Information

The generated LAS files include the following header information:
- Point data format: 1 (includes GPS time)
- Point data record length: 28 bytes
- Scale factor: 0.00001 for X, Y, Z
- Generating software: "Hesai SDK"
- Bounding box: Automatically calculated from point cloud data

#### 3 Viewing LAS/LAZ Files

You can view the generated LAS/LAZ files using various software:

- **CloudCompare** (free, cross-platform): https://www.cloudcompare.org/
- **QGIS** (free, GIS software): https://qgis.org/
- **LAStools** (command-line tools): https://rapidlasso.de/lastools/
- **Potree** (web-based viewer): https://potree.github.io/

#### 4 Dependencies and LASlib Installation

The las_tool uses LASlib library for reading and writing LAS/LAZ files. **LASlib is an external dependency and needs to be installed separately.**

##### 4.1 Installation Methods

**Build and install from source (Recommended)**

```bash
# Clone the repository
git clone https://github.com/LAStools/LAStools.git
cd LAStools

# Checkout a specific version if needed
# git checkout v2.0.0

# Build and install
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install

# Update dynamic library cache
sudo ldconfig
```


##### 4.2 Version Compatibility

| LAStools Version | LAS Format Support | API Compatibility | Notes |
|:-----------------|:-------------------|:------------------|:------|
| v2.0.0+ | LAS 1.0-1.4, LAZ | ✅ Fully compatible | Recommended, good CMake support |
| v1.8.x | LAS 1.0-1.4, LAZ | ✅ Compatible | Stable version |
| < v1.8 | LAS 1.0-1.3 | ⚠️ Partial | May lack some APIs |

**Important Notes:**

1. **API Changes**: Different versions of LAStools may have API changes. The APIs used by las_tool include:
   - `LASwriteOpener` / `LASreader` - File openers
   - `LASheader` - Header operations
   - `LASpoint` - Point data operations
   - `LASwriter` - File writer

2. **CMake Support**: Earlier versions of LAStools may not provide `LASlib-config.cmake`, causing `find_package(LASlib)` to fail. It's recommended to use v2.0.0 or newer.

3. **LAZ Compression Support**: LAZ compression requires LASzip support, which is typically included in LAStools. If installing LASlib separately, ensure LASzip is also installed.

##### 4.3 Verify Installation

During compilation, if you see the following message, LASlib has been found correctly:
```
-- LASlib found, las_tool will be built
```

If you see the following message, LASlib is not installed or not found by CMake:
```
-- LASlib not found, las_tool will be skipped
```

##### 4.4 Troubleshooting

**Q: Compilation error: cannot find `lasreader.hpp` or `laswriter.hpp`**

A: Check if LASlib is properly installed. Header files are usually located at `/usr/local/include/LASlib/` or `/usr/include/LASlib/`.

**Q: Linking error: `undefined reference to LASwriter`**

A: Ensure LASlib library files are properly installed. Try:
```bash
# Find library files
find /usr -name "libLAS*" 2>/dev/null

# If library is in non-standard path, set LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/path/to/LASlib/lib:$LD_LIBRARY_PATH
```

**Q: Runtime error: shared library not found**

A: Run `sudo ldconfig` to update the dynamic library cache, or add the library path to `LD_LIBRARY_PATH`.

## Configuration File Reference

For complete configuration file parameters, see [tool_sample_config.example.ini](../config/tool_sample_config.example.ini)

# Parsing PCAP Point Cloud Data Offline

## Preparation

Copy the example configuration file and modify the parameters:
```bash
cp config/sample_config.example.ini config/sample_config.ini
```

Edit `config/sample_config.ini`, set `source_type = pcap` and configure the `[pcap]` section:

```ini
[source_type]
source_type = pcap

[pcap]
pcap_path = /path/to/your.pcap                   # Offline PCAP point cloud data path
correction_file_path = /path/to/correction.csv   # Calibration file (angle correction file), recommend using the lidar's own calibration file
firetimes_path = /path/to/firetimes.csv          # Optional: Channel firing timing (firing moment correction file)

[decoder]
pcap_play_synchronization = true                 # Synchronize parsing according to point cloud timestamp, simulating actual lidar frequency
pcap_play_in_loop = false                        # Loop parsing PCAP
```

## Steps
```bash
# 1. Build executable sample program (from build folder): After successful compilation, generate executable program
make -j$(nproc)

# 2. Execute sample program: Start parsing data (must specify configuration file)
./sample /path/to/sample_config.ini
```

## Additional References

For complete configuration file parameters, see [sample_config.example.ini](../config/sample_config.example.ini)

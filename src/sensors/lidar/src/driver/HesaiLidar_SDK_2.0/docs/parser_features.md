# LiDAR Model Feature Support

## Feature Support

| Series | Model | Correction | Firetime | Distance Correction |
|------|------|:---:|:---:|:---:|
| Pandar | Pandar128E3X | ✅ | ✅ | ✅ |
| Pandar | Pandar40M | ✅ | ✅ | ✅ |
| Pandar | Pandar40P | ✅ | ✅ | ✅ |
| Pandar | Pandar64 | ✅ | ✅ | ✅ |
| Pandar | Pandar90E3X | ✅ | ✅ | ✅ |
| OT | OT128 | ✅ | ✅ | ✅ |
| OT | OT128_40 | ✅ | ✅ | ✅ |
| QT | PandarQT | ✅ | ✅ | ✅ |
| QT | QT128C2X | ✅ | ✅ | ✅ |
| XT | PandarXT | ✅ | ✅ | ✅ |
| XT | PandarXT-16 | ✅ | ✅ | ✅ |
| XT | XT32M2X | ✅ | ✅ | ✅ |
| AT | AT128E2X | ✅ | ❌ | ❌ |
| AT | AT128P | ✅ | ❌ | ❌ |
| AT | ATX | ✅ | ✅ | ❌ |
| FT | FT120 | ✅ | ❌ | ❌ |
| FT | FTX | ✅ | ❌ | ❌ |
| JT | JT128 | ✅ | ✅ | ✅ |
| JT | JT16 | ✅ | ❌ | ✅ |
| JT | JT64P | ✅ | ✅ | ✅ |

### Feature Description

| Feature | Description |
|------|------|
| **Correction** | Angle calibration file (.dat/.csv format) |
| **Firetime** | Fire time calibration file for motion compensation |
| **Distance Correction** | Optical center to geometric center coordinate transformation |

## Frame Mode and Point Cloud Capacity

> **Note**: maxPacket, maxPoint, and Max Points/Frame are **pre-allocated memory limits** in the code. Actual points per frame will be less than these values.

| Series | Model | Frame Mode | maxPacket | maxPoint | Max Points/Frame |
|------|------|----------|----------:|----------:|-------------:|
| Pandar | Pandar128E3X | Azimuth | 4000 | 400 | 1.6M |
| Pandar | Pandar40M | Azimuth | 1800 | 400 | 720K |
| Pandar | Pandar40P | Azimuth | 1800 | 400 | 720K |
| Pandar | Pandar64 | Azimuth | 1800 | 384 | 691K |
| Pandar | Pandar90E3X | Azimuth | 4000 | 400 | 1.6M |
| OT | OT128 | Azimuth | 4000 | 400 | 1.6M |
| OT | OT128_40 | Azimuth | 4000 | 400 | 1.6M |
| QT | PandarQT | Azimuth | 2000 | 256 | 512K |
| QT | QT128C2X | Azimuth | 1800 | 512 | 922K |
| XT | PandarXT | Azimuth | 2000 | 256 | 512K |
| XT | PandarXT-16 | Azimuth | 2000 | 256 | 512K |
| XT | XT32M2X | Azimuth | 2000 | 256 | 512K |
| AT | AT128E2X | Azimuth | 1800 | 256 | 461K |
| AT | AT128P | Azimuth | 1800 | 256 | 461K |
| AT | ATX | Frame ID | 2500 | 256 | 640K |
| FT | FT120 | Column ID | 2000 | 128 | 256K |
| FT | FTX | Frame ID | 3000 | 192 | 576K |
| JT | JT128 | Azimuth | 4000 | 400 | 1.6M |
| JT | JT16 | Azimuth | 1800 | 16 | 29K |
| JT | JT64P | Azimuth | 4000 | 400 | 1.6M |

### Frame Mode Description

| Frame Mode | Description |
|----------|------|
| **Azimuth** | Azimuth-based framing, split when angle difference exceeds threshold (rotating LiDAR) |
| **Frame ID** | Frame ID-based framing, split when frame number changes (solid-state LiDAR) |
| **Column ID** | Column ID-based framing, split on column index wrap-around (FT120 solid-state LiDAR) |

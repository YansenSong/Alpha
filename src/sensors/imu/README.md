# LPMS-IG1 RS232

ROS 2 driver for binary LP-BUS over USB/RS232, using Linux termios (8N1).
Default: `/dev/ttyUSB0`, 921600 baud, sensor ID 1. CANopen support has been removed.

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select imu
source install/setup.bash
ros2 launch imu lpms_ig1.launch.py port:=/dev/ttyUSB0 baudrate:=921600
```

Use `/dev/serial/by-id/...` for a stable port path. Parameters `port`, `baudrate`
and `sensor_id` are launch arguments. No hardware settings are changed or saved:
the driver queries commands 31, 35, 37 and 137 on connection to discover the
transmit mask, configured rate, angular units and precision. Missing replies
prevent publishing; the driver reconnects after `data_timeout_sec`.
Only 32-bit floating point LP-BUS mode is currently supported. Required enabled
fields are calibrated acceleration (bit 1), aligned Gyro II (bit 7), calibrated
magnetometer (bit 9) and quaternion (bit 11). Other known fields are skipped
according to the queried mask; payload length and finite values are checked.

Topics: `/imu/data`, `/imu/data_raw`, `/imu/mag`, `/imu/connected`.
Raw means converted SI data before user calibration, not uncalibrated chip data.
Acceleration defaults to sign inversion and g -> m/s²; gyro respects queried
rad/degree mode; magnetometer converts µT -> T. LPMS quaternion WXYZ is
conjugated following the IG1 ROS example, then optionally rotated NWU -> ENU.
Confirm physical axes and heading with controlled rotations before navigation.
ROS timestamps use host reception time, not the device counter.

Reconnect is controlled by `auto_reconnect`, `reconnect_interval_sec`,
`data_timeout_sec`, and `/imu/enable_auto_reconnect` (SetBool).
The launch uses neutral user calibration by default. Pass `params_file:=...`
to load newly measured calibration. Previous device calibration was removed.

References: [IG1 protocol registers](https://github.com/GPrathap/lpmsig1opensourcelib/blob/main/LpmsIG1Registers.h),
[payload decoding](https://github.com/GPrathap/lpmsig1opensourcelib/blob/main/SensorData.h),
[quaternion convention example](https://github.com/GPrathap/lpmsig1opensourcelib/blob/main/ros2_example/src/lpms_ig1_node.cpp).

## Static gyroscope calibration

Place the IMU on a stable surface, keep it completely stationary, and leave the
driver running. In another sourced terminal run:

```bash
ros2 run imu gyro_calibration
```

The default procedure waits 5 seconds, samples `/imu/data_raw` for 30 seconds,
checks gyroscope motion and acceleration magnitude, and writes a loadable ROS 2
parameter file to:

```text
~/.ros/lpms_ig1_gyro_calibration.yaml
```

Durations and the output path can be changed, for example:

```bash
ros2 run imu gyro_calibration --ros-args \
  -p warmup_duration:=10.0 \
  -p calibration_duration:=60.0 \
  -p output_file:=/tmp/lpms_ig1_gyro_calibration.yaml
```

Load the generated bias file on the next driver start:

```bash
ros2 launch imu lpms_ig1.launch.py \
  params_file:=$HOME/.ros/lpms_ig1_gyro_calibration.yaml
```

With calibration loaded, `/imu/data_raw` retains the converted, uncorrected
gyro readings. Bias subtraction is applied only to `/imu/data`.

## Accelerometer calibration

Run the six-position calibration while the uncalibrated driver is publishing
`/imu/data_raw`:

```bash
ros2 run imu accel_calibration
```

Follow the prompts and place the sensor in this order, pressing Enter only
after it is stable:

1. +X up
2. -X up
3. +Y up
4. -Y up
5. +Z up
6. -Z up

Each orientation is sampled for 8 seconds by default. A failed motion,
gravity-magnitude, or orientation check repeats only the current position.
The result is written to `~/.ros/lpms_ig1_calibration.yaml`; existing gyro bias
parameters in that file, or in the earlier gyro calibration file, are retained.
A detailed report is written separately to
`~/.ros/lpms_ig1_accel_calibration_report.yaml`.

Load the unified calibration with:

```bash
ros2 launch imu lpms_ig1.launch.py \
  params_file:=$HOME/.ros/lpms_ig1_calibration.yaml
```

Calibration is specific to the physical sensor. Generate new calibration for this RS232 unit.

The topic semantics are:

- `/imu/data_raw`: SI-unit IMU data without user gyro or accelerometer calibration.
- `/imu/data`: gyro bias removed and accelerometer offset/gain applied.

Accelerometer correction is `corrected = (raw - offset) * gain`. It affects
only the ROS acceleration values and does not change the LPMS internal AHRS or
its fused quaternion. Perform magnetometer calibration only after final vehicle
installation, where the local magnetic environment is representative.

## Vehicle mounting calibration

After permanently installing the IMU, park the normally loaded vehicle on the
flattest available ground and keep it stationary. Run the calibrated driver,
then execute:

```bash
ros2 run imu mounting_calibration --ros-args \
  -p mount_x:=0.0 -p mount_y:=0.0 -p mount_z:=0.0 \
  -p mount_yaw_deg:=0.0
```

The XYZ parameters are the measured `imu_link` position relative to
`base_link`, in metres (+X forward, +Y left, +Z up). Yaw must come from the
physical installation measurement and follows the ROS +Z right-hand rule.
Static gravity can estimate roll and pitch but **cannot determine yaw**.

The result is written to `~/.ros/lpms_ig1_mounting.yaml`. The launch file can
publish `base_link -> imu_link` from it:

```bash
ros2 launch imu lpms_ig1.launch.py \
  mounting_file:=$HOME/.ros/lpms_ig1_mounting.yaml
ros2 run tf2_ros tf2_echo base_link imu_link
```

If the mounting file is absent, the driver still starts and emits a warning;
no static TF is published. Ground slope is indistinguishable from mounting
tilt, so roll/pitch accuracy is limited by how level the vehicle and floor are.

A stationary, Z-up sensor should show approximately:

```text
linear_acceleration.z ~= +9.8
angular_velocity.x/y/z ~= 0
```

## Mounting frame

Measurements remain expressed in the LPMS sensor axes. `frame_id` defaults to
`imu_link`.

Describe the physical IMU mounting relative to the robot with a static TF, e.g.
from `base_link` to `imu_link`. For a ROS-standard robot body frame use:

- +X forward
- +Y left
- +Z up

Do not fake the mounting orientation by permuting sensor axes unless you have a
specific reason; represent mounting with TF or LPMS Object Reset.

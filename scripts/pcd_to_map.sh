#!/usr/bin/env bash
# Convert a LIO-SAM GlobalMap.pcd into map.pgm + map.yaml.
#
# LIO-SAM's save_map service appends its own timestamp directory, so the input
# here is normally the timestamped directory it just created:
#
#   ros2 service call /lio_sam/save_map lio_sam/srv/SaveMap \
#     "{resolution: 0.2, destination: ${PROJECT_DIR}/maps}"
#   bash scripts/pcd_to_map.sh maps/20261016_231500
#
# Usage: bash scripts/pcd_to_map.sh <maps/relative-directory>

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAPS_DIR="$PROJECT_DIR/maps"
CONVERTER="$PROJECT_DIR/third_party/pcd2pgm/build/pcd2gridmap"

if [[ ! -x "$CONVERTER" ]]; then
  echo "PCD converter is not built. Build it first (plain CMake, not ament):" >&2
  echo "  cmake -S third_party/pcd2pgm -B third_party/pcd2pgm/build" >&2
  echo "  cmake --build third_party/pcd2pgm/build" >&2
  exit 1
fi

if [[ $# -ne 1 ]]; then
  echo "Usage: bash scripts/pcd_to_map.sh <maps/relative-directory>" >&2
  echo "Example: bash scripts/pcd_to_map.sh maps/20261016_231500" >&2
  exit 1
fi

if [[ "$1" = /* ]]; then
  echo "Map directory must be relative to the project, for example: maps/mini" >&2
  exit 1
fi

MAP_DIR="$(realpath -m "$PROJECT_DIR/$1")"
if [[ "$MAP_DIR" != "$MAPS_DIR"/* || ! -f "$MAP_DIR/GlobalMap.pcd" ]]; then
  echo "No GlobalMap.pcd found at $MAP_DIR/GlobalMap.pcd" >&2
  echo "Save a LIO-SAM map first, then pass the timestamped directory it created:" >&2
  echo "  ros2 service call /lio_sam/save_map lio_sam/srv/SaveMap \\" >&2
  echo "    \"{resolution: 0.2, destination: ${MAPS_DIR}}\"" >&2
  exit 1
fi

echo "Converting: $MAP_DIR/GlobalMap.pcd"
exec "$CONVERTER" "$MAP_DIR/GlobalMap.pcd" -o "$MAP_DIR/map"

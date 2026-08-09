#!/usr/bin/env bash
# One-time OSRM preprocessing for the ambulance-desert analysis.
#
# Prereq: Docker Desktop running (no other host dependencies -- even the
# OSM filtering step runs inside a container, so no osmium install needed).
#
# Input:  data/raw/geofabrik_new-york-latest.osm.pbf   (Geofabrik NY extract)
# Output: data/raw/osrm/ny-car.osrm*                   (gitignored artifacts)
#
# The pbf is first filtered to the drivable network (highway ways + turn
# restriction relations). This shrinks the extract by roughly two thirds,
# which keeps osrm-extract's memory use within reach of an 8 GB machine --
# feeding it the full extract risks an OOM inside the Docker VM.
#
# After this completes, launch the routing server with:
#   docker run --rm -t -i -p 5001:5000 -v "$(pwd)/data/raw/osrm:/data" \
#     osrm/osrm-backend osrm-routed --algorithm mld \
#     --max-table-size 20000 /data/ny-car.osrm
# (Host port 5001: macOS AirPlay squats on 5000.)

set -euo pipefail
cd "$(dirname "$0")/.."

PBF=geofabrik_new-york-latest.osm.pbf
mkdir -p data/raw/osrm
cp -n "data/raw/$PBF" data/raw/osrm/ 2>/dev/null || true

echo "==> Filtering to drivable network (osmium, in-container)..."
docker run --rm -v "$(pwd)/data/raw/osrm:/data" stefda/osmium-tool \
  osmium tags-filter "/data/$PBF" w/highway r/type=restriction \
  -o /data/ny-car.osm.pbf --overwrite

echo "==> osrm-extract (car profile)..."
docker run --rm -t -v "$(pwd)/data/raw/osrm:/data" osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/ny-car.osm.pbf

echo "==> osrm-partition + osrm-customize (MLD)..."
docker run --rm -t -v "$(pwd)/data/raw/osrm:/data" osrm/osrm-backend \
  osrm-partition /data/ny-car.osrm
docker run --rm -t -v "$(pwd)/data/raw/osrm:/data" osrm/osrm-backend \
  osrm-customize /data/ny-car.osrm

echo "==> Done. Start the server with the docker run command in this script's header."

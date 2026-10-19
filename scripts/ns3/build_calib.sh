#!/usr/bin/env bash
set -e
cd ~/sectwin-ns3/ns-3-dev
nice -n 19 ./ns3 configure -d optimized --enable-examples --disable-tests --disable-werror --enable-modules="nr;lte;flow-monitor;stats" 2>&1 | tail -3
nice -n 19 ./ns3 build cttc-nr-3gpp-calibration-user 2>&1 | tail -3
ls build/contrib/nr/examples/ | grep calibration
echo CALIB_BUILD_DONE

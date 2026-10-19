#!/usr/bin/env bash
# Build ns-3 + CTTC 5G-LENA (nr) inside WSL Ubuntu. Official sources only:
#   https://gitlab.com/nsnam/ns-3-dev  and  https://gitlab.com/cttc-lena/nr
set -e
mkdir -p ~/sectwin-ns3 && cd ~/sectwin-ns3
if [ ! -d nr ]; then git clone -q https://gitlab.com/cttc-lena/nr.git; fi
cd nr
BR=$(git branch -r | grep -oE "origin/5g-lena-v[0-9]+\.[0-9]+\.y" | sort -V | tail -1)
git checkout -q -B local "$BR"
echo "nr branch: $BR"
NS=$(grep -oE "ns-3\.[0-9]+" RELEASE_NOTES.md | head -1)
echo "nr declares: $NS"
cd ..
if [ ! -d ns-3-dev ]; then git clone -q --depth 1 --branch "$NS" https://gitlab.com/nsnam/ns-3-dev.git; fi
rm -rf ns-3-dev/contrib/nr && cp -r nr ns-3-dev/contrib/nr
cd ns-3-dev
./ns3 configure -d optimized --enable-examples --disable-tests --disable-werror --enable-modules="nr" 2>&1 | tail -8
./ns3 build 2>&1 | tail -5
echo BUILD_DONE

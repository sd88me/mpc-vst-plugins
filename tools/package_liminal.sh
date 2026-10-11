#!/bin/bash
set -ex

PY='/opt/venv/bin/python'
PLUGINS='/a0/usr/workdir/mpc-vst-plugins/tools'
BASE='/a0/usr/workdir/LiminalHz-1.0.0/Liminal Hz for MPC OS'
PLUGIN_DIR="$BASE/Gm0rb - VST - Liminal Hz"
SO_PATH="$PLUGIN_DIR/liminal_hz.so"
SKIN_PATH="$PLUGIN_DIR/Plugin Skins"
ENTRY_PATH="$PLUGIN_DIR/plugin-meta.xml"
BENCH_PATH="$PLUGIN_DIR/bench.json"
DIST_DIR=/tmp/liminal_hz_dist

# Verify files exist
test -f 
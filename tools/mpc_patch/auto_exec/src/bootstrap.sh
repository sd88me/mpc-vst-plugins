#!/bin/sh
set -eu
# Reload after the writable /etc overlay appears; schedule work without waiting for SSD. (Original: timomacquis, 0.1.3.)
systemctl daemon-reload
systemctl --no-block start auto-exec.timer

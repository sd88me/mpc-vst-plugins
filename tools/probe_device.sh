#!/bin/sh
# Read-only report of what an MPC OS device offers plugins: CPU, architecture, audio worker layout and which
# plugin formats MPC's JUCE host has compiled in (VST2 / VST3 / LV2). Changes nothing.
#   ssh root@<device-ip> sh -s < tools/probe_device.sh
# Please post the output for devices not listed in docs/NOTES.md (especially Gen2 units).
B=${MPC_BIN:-/usr/bin/MPC}
echo "== device"
uname -m; grep -m1 -E "^VERSION=" /etc/os-release 2>/dev/null
echo "cores: $(grep -c ^processor /proc/cpuinfo), parts: $(grep 'CPU part' /proc/cpuinfo | sort -u | awk '{print $4}' | tr '\n' ' ')"
echo "max MHz: $(cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq 2>/dev/null | sed 's/...$//')"
grep -o 'isolcpus=[^ ]*' /proc/cmdline
echo "MPC binary: $(dd if="$B" bs=1 skip=4 count=1 2>/dev/null | od -b | awk 'NR==1{print ($2=="002" ? "64-bit" : "32-bit")}')"
p=$(pidof MPC)
if [ -n "$p" ]; then
    echo "== MPC audio threads (name cpu policy)"
    for t in /proc/$p/task/*; do
        case "$(cat $t/comm)" in Audio*) echo "$(cat $t/comm) $(awk '{print $39, $41}' $t/stat)" ;; esac
    done
fi
echo "== plugin formats compiled into MPC"
S=/tmp/.mpcstrings.$$
strings -n 4 "$B" > $S
has() { grep -q "$1" $S && echo "yes" || echo "no"; }
echo "VST2 (juce::VSTPluginFormat):  $(has 'N4juce15VSTPluginFormatE')"
echo "VST3 (juce::VST3PluginFormat): $(has 'VST3PluginFormat')   GetPluginFactory: $(has '^GetPluginFactory$')"
echo "LV2  (juce::LV2PluginFormat):  $(has 'LV2PluginFormat')"
echo "settings key parts: $(grep -xE -- 'pluginList|-arm|-arm64|-aarch64' $S | sort -u | tr '\n' ' ')"
rm -f $S
ls /media/az01-internal/Settings/*/MPC.settings /data/Settings/*/MPC.settings 2>/dev/null

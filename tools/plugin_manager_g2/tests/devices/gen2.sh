set -e
# Any Gen2 device (aarch64: Live III, MPC One G2, MPC Key(s) G2, ...), MPC OS 3.9.1 verity rootfs. Confirmed on a
# Live III: no /media/az01-internal, no /sdcard; Settings is under /data and the writable+exec internal drive is
# /nvme (exFAT). Plugin list key is pluginList-arm-64bit. Other Gen2 models are assumed to share this layout (same
# platform/OS) but not yet confirmed individually -- update this fixture if one differs.
S=/data/Settings/MPC; mkdir -p $S /nvme/Synths/"sd88me - VST - JV-880"; touch /nvme/Synths/"sd88me - VST - JV-880"/jv880.so
printf '<PROPERTIES>\n<VALUE name="SynthContentLocations"><SynthContentLocations><Location>/nvme/Synths</Location><Location>/usr/share/Akai/Content/Synths</Location></SynthContentLocations></VALUE>\n<VALUE name="pluginList-arm-64bit"><KNOWNPLUGINS>\n<PLUGIN name="JV-880" descriptiveName="JV-880" format="VST" category="Synth" manufacturer="sd88me" version="1.0" file="/nvme/Synths/sd88me - VST - JV-880/jv880.so" uid="4a563838" isInstrument="1"/>\n</KNOWNPLUGINS></VALUE>\n</PROPERTIES>\n' > $S/MPC.settings
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

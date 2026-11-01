# MPC Key 37, MPC OS 3.9.1: internal storage is /storage (ext4), with Synths and Expansions as separate locations
# and no /media/az01-internal/Synths; settings still live under /media/az01-internal/Settings/MPC. Addins in
# /data/mpc-addins (one installed by hand, without uninstall.sh). From the device.txt of a real Key 37 (docs/tests/).
set -e
S=/media/az01-internal/Settings/MPC; mkdir -p $S /storage/Expansions /storage/Synths /data/mpc-addins/usb-audio
Y=/storage/Synths
mkdir -p "$Y/jacob-sabella - VST - Chordsmith" "$Y/poloq - VST - Plugin Manager"
touch "$Y/jacob-sabella - VST - Chordsmith/chordsmith.so" "$Y/poloq - VST - Plugin Manager/plugin_manager.so"
echo '{"schema":1,"id":"chordsmith","version":"0.3.0"}' > "$Y/jacob-sabella - VST - Chordsmith/mpc-plugin.json"
echo '{"schema":1,"id":"plugin-manager","version":"1.0.0"}' > "$Y/poloq - VST - Plugin Manager/mpc-plugin.json"
printf 'ADDIN_ID=usb-audio\nADDIN_VERSION=0.1.0\n' > /data/mpc-addins/usb-audio/addin.manifest
: > /media/az01-internal/.openmpcpm-installed
printf '<?xml version="1.0"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/storage/Expansions</Location>\r\n      <Location>/storage/Synths</Location>\r\n      <Location>/usr/share/Akai/Content/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS>\r\n      <PLUGIN name="Chordsmith" descriptiveName="Chordsmith" format="VST" category="Synth" manufacturer="jacob-sabella" version="1.0" file="/storage/Synths/jacob-sabella - VST - Chordsmith/chordsmith.so" uid="4368536d" isInstrument="1"/>\r\n      <PLUGIN name="Plugin Manager" descriptiveName="Plugin Manager" format="VST" category="Synth" manufacturer="poloq" version="1.0" file="/storage/Synths/poloq - VST - Plugin Manager/plugin_manager.so" uid="506c4d67" isInstrument="1"/>\r\n    </KNOWNPLUGINS>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf "#!/bin/sh
exit 0
" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

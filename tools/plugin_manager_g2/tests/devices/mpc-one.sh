set -e
S=/media/az01-internal/Settings/MPC; mkdir -p $S /media/acvs-content/Expansions /media/az01-internal/Synths /media/az01-internal/vst
Y=/media/az01-internal/Synths
mkdir -p "$Y/poloq - VST - MPC Plaits" "$Y/sd88me - VST - Acid" "$Y/sd88me - VST - Machinedrum Module"
touch "$Y/poloq - VST - MPC Plaits/plaits.so" "$Y/sd88me - VST - Acid/acid.so" /media/az01-internal/vst/maze_voice.so
echo '{"schema":1,"id":"mpc-plaits","version":"1.0.0"}' > "$Y/poloq - VST - MPC Plaits/mpc-plugin.json"
echo 'acid 1.0.1' > /media/az01-internal/.pluginmgr-installed
printf '<?xml version="1.0"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/media/CARD/Synths</Location>\r\n      <Location>/media/acvs-content/Expansions</Location>\r\n      <Location>/usr/share/Akai/Content/Synths</Location>\r\n      <Location>/media/az01-internal/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS>\r\n      <PLUGIN name="MPC Plaits" descriptiveName="MPC Plaits" format="VST"\r\n              category="Synth" manufacturer="poloq" version="1.0" file="/media/az01-internal/Synths/poloq - VST - MPC Plaits/plaits.so"\r\n              uid="4d69506c" isInstrument="1"/>\r\n      <PLUGIN name="Acid" descriptiveName="Acid" format="VST" category="Synth" manufacturer="sd88me" version="1.0" file="/media/az01-internal/Synths/sd88me - VST - Acid/acid.so" uid="41634964" isInstrument="1"/>\r\n      <PLUGIN name="Maze Voice" descriptiveName="Maze Voice" format="VST" category="Synth" manufacturer="sd88me" version="1.0" file="/media/az01-internal/vst/maze_voice.so" uid="4d7a5663" isInstrument="1"/>\r\n      <PLUGIN name="Machinedrum One" descriptiveName="Machinedrum One" format="VST" category="Synth" manufacturer="sd88me" version="1.0" file="/media/az01-internal/Synths/sd88me - VST - Machinedrum Module/machinedrum_one.so" uid="4d644f6e" isInstrument="1"/>\r\n    </KNOWNPLUGINS>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf "#!/bin/sh
exit 0
" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

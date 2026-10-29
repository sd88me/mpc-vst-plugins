set -e
S=/media/az01-internal/Settings/Force; mkdir -p $S /sdcard/Synths/"sd88me - VST - JV-880"; touch /sdcard/Synths/"sd88me - VST - JV-880"/jv880.so
mkdir -p /media/USB/Synths
printf '<PROPERTIES>\n<VALUE name="SynthContentLocations"><SynthContentLocations><Location>/media/USB/Synths</Location><Location>/sdcard/Synths</Location><Location>/media/662522/Synths</Location><Location>/usr/share/Akai/Content/Synths</Location></SynthContentLocations></VALUE>\n<VALUE name="pluginList-arm"><KNOWNPLUGINS>\n<PLUGIN name="JV-880" descriptiveName="JV-880" format="VST" category="Synth" manufacturer="sd88me" version="1.0" file="/media/az01-internal-sd/Synths/sd88me - VST - JV-880/jv880.so" uid="4a563838" isInstrument="1"/>\n</KNOWNPLUGINS></VALUE>\n</PROPERTIES>\n' > $S/MPC.settings
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

set -e
# SynthContentLocations has no usable Synths folder (factory content, an expansion, a card that is not there). Poloq's manager fell back to
# the folder of an installed plugin; G2 does not (that folder is not a content location, so a plugin there has no skin): it installs nothing.
S=/media/az01-internal/Settings/MPC; Y=/media/az01-internal/Synths; mkdir -p $S /media/acvs-content/Expansions "$Y/sd88me - VST - Acid"
touch "$Y/sd88me - VST - Acid/acid.so"
printf '<?xml version="1.0"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/media/acvs-content/Expansions</Location>\r\n      <Location>/usr/share/Akai/Content/Synths</Location>\r\n      <Location>/media/CARD/Synths/</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS>\r\n      <PLUGIN name="Acid" descriptiveName="Acid" format="VST" category="Synth" manufacturer="sd88me" version="1.0" file="/media/az01-internal/Synths/sd88me - VST - Acid/acid.so" uid="41634964" isInstrument="1"/>\r\n    </KNOWNPLUGINS>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

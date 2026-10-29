set -e
# Two usable locations (poloq's mpc-vst-manager issue #10: only the internal drive was offered): the internal /sdcard/Synths and an
# exFAT card. The first is the default; CHANGE on the restart prompt picks the other.
S=/media/az01-internal/Settings/MPC; mkdir -p $S /sdcard/Synths /media/CARD/Synths
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/media/CARD/Synths</Location>\r\n      <Location>/sdcard/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf 'x /sdcard ext4 rw,relatime 0 0\nx /media/CARD exfat rw,relatime 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

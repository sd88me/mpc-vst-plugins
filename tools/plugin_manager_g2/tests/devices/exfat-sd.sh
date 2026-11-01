set -e
# A Live Mk1 (Gen1) with the SD card formatted exFAT (poloq's mpc-vst-manager issue #9): the card is writable and executable, so it
# is a target; the internal path is not writable. The card is used, with no filesystem whitelist in the way.
S=/media/az01-internal/Settings/MPC; mkdir -p $S /media/az01-internal/Synths /sdcard/Synths
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/media/az01-internal/Synths</Location>\r\n      <Location>/sdcard/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf 'x /media/az01-internal ext4 ro,relatime 0 0\nx /sdcard exfat rw,relatime 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

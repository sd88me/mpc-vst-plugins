set -e
# A Force lists its internal SD twice, as /sdcard/Synths and /media/az01-internal-sd/Synths (one storage; a user's report, 2026-11-03:
# "both INTERNAL entries point to the same storage"). The Manager must offer it once.
S=/media/az01-internal/Settings/MPC; mkdir -p $S /sdcard/Synths
ln -s /sdcard /media/az01-internal-sd
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/sdcard/Synths</Location>\r\n      <Location>/media/az01-internal-sd/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf 'x /sdcard ext4 rw,relatime 0 0\nx /media/az01-internal-sd ext4 rw,relatime 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

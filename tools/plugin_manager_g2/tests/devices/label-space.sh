set -e
# An MPC One (Gen1, Hakai 3.9.1.2) with a 1 TB exFAT USB drive whose label has a space (a user's report, 2026-11-03): /proc/mounts
# writes the mount point as /media/My\040HDD. Undecoded, the drive never matched its own path and the Manager said "/media is tmpfs".
S=/media/az01-internal/Settings/MPC; mkdir -p $S /media/az01-internal/Synths "/media/My HDD/Synths"
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/media/az01-internal/Synths</Location>\r\n      <Location>/media/My HDD/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf 'x /media tmpfs rw,relatime 0 0\nx /media/az01-internal ext4 ro,relatime 0 0\n/dev/sda1 /media/My\\040HDD exfat rw,relatime 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

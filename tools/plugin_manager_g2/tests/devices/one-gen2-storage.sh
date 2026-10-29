set -e
# An MPC One Gen2, OS 3.9.1 (the user's own mount / grep output, 2026-10-28, docs/NOTES.md): /storage (loop0p1) is exFAT rw and holds eight plugins,
# /synths is read-only ext4 (not a content location), /data is rw ext4, the SD card /media/MPC (mmcblk1p1) is exFAT. MPC.settings lists the SD card
# FIRST, then /storage/Synths: the default must be /storage/Synths, because the card can be pulled out (told by the mount's device).
S=/data/Settings/MPC; mkdir -p $S /media/MPC/Synths /storage/Synths
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/media/MPC/Synths</Location>\r\n      <Location>/storage/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm-64bit">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf '/dev/mmcblk0p11 /synths ext4 ro,relatime 0 0\n/dev/loop0p1 /storage exfat rw,relatime 0 0\n/dev/mmcblk0p12 /data ext4 rw,relatime 0 0\n/dev/mmcblk1p1 /media/MPC exfat rw,relatime 0 0\n/dev/sda1 /media/B89A-DFD0 vfat rw,noexec 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

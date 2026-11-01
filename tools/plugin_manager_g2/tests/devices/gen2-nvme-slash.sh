set -e
# Live III with /nvme/Synths listed, with a trailing slash and CRLF line ends like the device's own file. MPC accepts the
# slash (device, 2026-10-27), so the target is /nvme/Synths.
S=/data/Settings/MPC; mkdir -p $S /nvme/Synths
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/nvme/Synths/</Location>\r\n      <Location>/usr/share/Akai/Content/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm-64bit">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf 'x /nvme exfat rw,relatime 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

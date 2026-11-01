set -e
# Live III on MPC OS 3.10 (device, 2026-10-27): the writable internal drive /nvme is NOT in SynthContentLocations. What is
# listed is the read-only /synths, Akai's own content, and a USB stick mounted noexec. Nothing usable is listed, so the manager
# installs nothing and says why (a folder outside the list would load its plugin with no skin).
S=/data/Settings/MPC; mkdir -p $S /nvme/Synths /synths/Synths /synths/Expansions /media/9A5E-BA8A/Synths
printf '<?xml version="1.0" encoding="UTF-8"?>\r\n<PROPERTIES>\r\n  <VALUE name="SynthContentLocations">\r\n    <SynthContentLocations>\r\n      <Location>/synths/Expansions</Location>\r\n      <Location>/synths/Synths</Location>\r\n      <Location>/usr/share/Akai/Content/Synths</Location>\r\n      <Location>/media/9A5E-BA8A/Synths</Location>\r\n    </SynthContentLocations>\r\n  </VALUE>\r\n  <VALUE name="pluginList-arm-64bit">\r\n    <KNOWNPLUGINS/>\r\n  </VALUE>\r\n</PROPERTIES>\r\n' > $S/MPC.settings
printf 'x /synths exfat ro,relatime 0 0\nx /media/9A5E-BA8A vfat rw,noexec 0 0\nx /nvme exfat rw,relatime 0 0\n' > /tmp/pm-mounts
printf "#!/bin/sh\nexit 0\n" > /usr/bin/systemctl; chmod +x /usr/bin/systemctl

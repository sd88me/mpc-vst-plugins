#!/bin/sh
# a stand-in Force inside the test container: sshd + shims for the few device-only commands
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null && apt-get install -y -qq openssh-server >/dev/null
mkdir -p /run/sshd /media/az01-internal/Settings/MPC /sdcard/Synths
echo '<?xml version="1.0" encoding="UTF-8"?>
<PROPERTIES>
  <VALUE name="SynthContentLocations">
    <SynthContentLocations>
      <Location>/sdcard/Synths</Location>
    </SynthContentLocations>
  </VALUE>
</PROPERTIES>' > /media/az01-internal/Settings/MPC/MPC.settings
mkdir -p "/sdcard/Synths/other - VST - Existing"
mkdir -p "/sdcard/Synths/mystery - VST - Thing" && echo '<PLUGIN name="Thing" file="%payload-path%/mystery - VST - Thing/thing.so" uid="77777777"/>' > "/sdcard/Synths/mystery - VST - Thing/plugin-meta.xml"
touch "/sdcard/Synths/mystery - VST - Thing/thing.so"
mkdir -p "/media/CARD1/Synths/card - VST - Gadget" && echo '<PLUGIN name="Gadget" format="VST" manufacturer="card" version="1.0" file="%payload-path%/card - VST - Gadget/gadget.so" uid="99887766" isInstrument="1"/>' > "/media/CARD1/Synths/card - VST - Gadget/plugin-meta.xml"
touch "/media/CARD1/Synths/card - VST - Gadget/gadget.so"
cat > /usr/local/bin/uname <<'X'
#!/bin/sh
[ "$1" = "-m" ] && { echo armv7l; exit 0; }
exec /usr/bin/uname "$@"
X
printf '#!/bin/sh\n[ "$1" = cat ] && { [ "$2" = acvs ]; exit; }\necho "$1 $2" >> /tmp/systemctl.log\n' > /usr/local/bin/systemctl
printf '#!/bin/sh\nexit 1\n' > /usr/local/bin/pidof
chmod +x /usr/local/bin/uname /usr/local/bin/systemctl /usr/local/bin/pidof
echo 'root:secret' | chpasswd
printf 'PermitRootLogin yes\nPasswordAuthentication yes\nUsePAM no\n' >> /etc/ssh/sshd_config
/usr/sbin/sshd
sleep 1
python3 /out/ui_test.py
python3 /out/ui_filters.py
python3 /out/ui_addins.py

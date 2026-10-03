package main

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDialReadsTheDeviceAndRefusesBadInput(t *testing.T) {
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if d.Info.Arch != "armv7l" || d.Info.UID != "0" || !d.Info.Tar || !d.Info.Systemctl || d.Info.Settings == "" || d.Info.Fingerprint == "" {
		t.Fatalf("unexpected device info: %+v", d.Info)
	}
	if p := d.Info.problems(); len(p) != 0 {
		t.Fatalf("a good device has no problems: %v", p)
	}
	if _, err := Dial("127.0.0.1", "wrong", fd.cfg()); err == nil {
		t.Error("a wrong password must fail")
	}
	for _, bad := range []string{"", "1.2.3.4; rm -rf /", "a b", "$(x)", "-oProxyCommand=x"} {
		if _, err := Dial(bad, "secret", fd.cfg()); err == nil {
			t.Errorf("host %q must be refused", bad)
		}
	}
}

func TestDialWithoutPasswordOrKey(t *testing.T) {
	t.Setenv("HOME", t.TempDir()) // no ~/.ssh keys
	if _, err := Dial("127.0.0.1", "", newFakeDevice(t).cfg()); err == nil || !strings.Contains(err.Error(), "enter the device's password") {
		t.Errorf("a device that wants a password must ask for one, got %v", err)
	}
	d, err := Dial("127.0.0.1", "", newOpenFakeDevice(t).cfg())
	if err != nil {
		t.Fatalf("a device whose root has no password must connect with none: %v", err)
	}
	d.Close()
}

func TestProblemsExplainWhyADeviceIsRefused(t *testing.T) {
	p := DeviceInfo{Arch: "x86_64", UID: "1000"}.problems()
	if len(p) < 4 {
		t.Fatalf("expected several reasons, got %v", p)
	}
}

// a package whose installer copies portable/<skin> into $SYN like the real one, so modes and symlinks are checked end to end
func installerPkg(t *testing.T, top, id, skin, install string, extra ...zent) *Package {
	t.Helper()
	ents := append(pluginEntries(top, "", id, skin, install, nil),
		zent{top + "/portable/" + skin + "/bin/tool", 0o755, "#!/bin/sh\necho tool\n"},
		zent{top + "/portable/" + skin + "/bin/link", fs.ModeSymlink | 0o777, "tool"})
	ents = append(ents, extra...)
	p, err := OpenPackage(writeZip(t, t.TempDir(), ents), "upload")
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// installers that behave like release.py's: -t <synths>, -y, optional -n; they copy the folder and log their arguments
func fakeInstaller(logName string, supportN bool, failWith int) string {
	n := ""
	if supportN {
		n = "DEFER=0\n"
	}
	return "#!/bin/sh\n" + n + `cd "$(dirname "$0")"
SYN=""; while [ $# -gt 0 ]; do case "$1" in -t) SYN="$2"; shift 2 ;; *) ARGS="$ARGS $1"; shift ;; esac; done
echo "` + logName + `:$ARGS" >> "$SYN/install.log"
[ ` + itoa(failWith) + ` = 0 ] || exit ` + itoa(failWith) + `
for d in portable/*; do rm -rf "$SYN/$(basename "$d")"; cp -a "$d" "$SYN/"; done
`
}

func runJob(t *testing.T, fd *fakeDevice, items ...Item) (*Job, error) {
	t.Helper()
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	j := &Job{ID: "x", State: "running"}
	err = RunInstall(d, d.Info.primaryRoot(), items, t.TempDir(), j, nil)
	return j, err
}

func TestInstallBatchesOneStopAndStartAndKeepsModesAndLinks(t *testing.T) {
	fd := newFakeDevice(t)
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	b := installerPkg(t, "B-1", "b-plug", "me - VST - B", fakeInstaller("B", true, 0))
	j, err := runJob(t, fd, Item{Pkg: a}, Item{Pkg: b})
	if err != nil {
		t.Fatal(err, j.Lines)
	}
	if st, _, _, res := j.snapshot(0); st != "done" {
		t.Fatalf("state %s %s", st, res)
	}
	if got := fd.calls(); strings.Join(got, ",") != "stop acvs,start acvs" {
		t.Fatalf("MPC must be stopped once and started once, got %v", got)
	}
	syn := fd.cfg().SynthsDir
	for _, s := range []string{"me - VST - A", "me - VST - B"} {
		fi, err := os.Stat(filepath.Join(syn, s, "bin", "tool"))
		if err != nil || fi.Mode()&0o111 == 0 {
			t.Errorf("%s: exec bit lost: %v %v", s, err, fi)
		}
		if l, err := os.Readlink(filepath.Join(syn, s, "bin", "link")); err != nil || l != "tool" {
			t.Errorf("%s: symlink lost: %v %q", s, err, l)
		}
	}
	log, _ := os.ReadFile(filepath.Join(syn, "install.log"))
	if !strings.Contains(string(log), "A: -y -n") || !strings.Contains(string(log), "B: -y -n") {
		t.Errorf("installers must run with -y -n: %s", log)
	}
	state, _ := os.ReadFile(filepath.Join(syn, ".mpc-store"))
	if !strings.Contains(string(state), "a-plug\t1.2.3\tme - VST - A\t1") || !strings.Contains(string(state), "b-plug\t1.2.3\tme - VST - B\t1") {
		t.Errorf("what was installed is not recorded: %q", state)
	}
	if ents, _ := os.ReadDir(fd.cfg().RemoteTmp); len(ents) != 0 {
		t.Errorf("the unpacked packages must be removed from the device: %v", ents)
	}
}

func TestAnOldInstallerRunsByItselfFirst(t *testing.T) {
	fd := newFakeDevice(t)
	old := installerPkg(t, "O-1", "old", "me - VST - Old", fakeInstaller("OLD", false, 0))
	nw := installerPkg(t, "N-1", "new", "me - VST - New", fakeInstaller("NEW", true, 0))
	if _, err := runJob(t, fd, Item{Pkg: nw}, Item{Pkg: old}); err != nil {
		t.Fatal(err)
	}
	log, _ := os.ReadFile(filepath.Join(fd.cfg().SynthsDir, "install.log"))
	if !strings.Contains(string(log), "OLD: -y\n") || strings.Contains(string(log), "OLD: -y -n") {
		t.Errorf("an installer without -n support must not be given -n: %s", log)
	}
	if strings.Index(string(log), "OLD") > strings.Index(string(log), "NEW") {
		t.Errorf("old installers run first: %s", log)
	}
}

func TestAFailingInstallerStopsTheRestAndStillStartsMPC(t *testing.T) {
	fd := newFakeDevice(t)
	bad := installerPkg(t, "F-1", "bad", "me - VST - Bad", fakeInstaller("BAD", true, 7))
	after := installerPkg(t, "G-1", "after", "me - VST - After", fakeInstaller("AFTER", true, 0))
	j, err := runJob(t, fd, Item{Pkg: bad}, Item{Pkg: after})
	if err == nil {
		t.Fatal("expected a failure")
	}
	if st, _, _, _ := j.snapshot(0); st != "failed" {
		t.Fatalf("state %s", st)
	}
	if got := strings.Join(fd.calls(), ","); got != "stop acvs,start acvs" {
		t.Fatalf("MPC must be started again after a failure: %v", got)
	}
	log, _ := os.ReadFile(filepath.Join(fd.cfg().SynthsDir, "install.log"))
	if strings.Contains(string(log), "AFTER") {
		t.Errorf("nothing after the failing plugin may be installed: %s", log)
	}
	state, _ := os.ReadFile(filepath.Join(fd.cfg().SynthsDir, ".mpc-store"))
	if strings.Contains(string(state), "bad") {
		t.Errorf("a failed install must not be recorded: %q", state)
	}
	if ents, _ := os.ReadDir(fd.cfg().RemoteTmp); len(ents) != 0 {
		t.Errorf("cleanup after a failure: %v", ents)
	}
}

func TestARefusedDeviceIsNotTouched(t *testing.T) {
	fd := newFakeDevice(t)
	os.WriteFile(filepath.Join(fd.shims, "uname"), []byte("#!/bin/sh\necho x86_64\n"), 0o755)
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	_, err := runJob(t, fd, Item{Pkg: a})
	if err == nil || !strings.Contains(err.Error(), "not a 32-bit ARM") {
		t.Fatalf("expected a refusal, got %v", err)
	}
	if len(fd.calls()) != 0 {
		t.Error("MPC must not be touched on a refused device")
	}
	if ents, _ := os.ReadDir(fd.cfg().RemoteTmp); len(ents) != 0 {
		t.Errorf("nothing may be copied: %v", ents)
	}
}

func TestInstallScriptQuotesEverything(t *testing.T) {
	p := &Package{Title: "It's; rm -rf / \"x\"", Defer: true, Plugins: []Manifest{{ID: "a", Version: "1", Skin: "a'b - VST - $(x)", ParamCompat: 1}}}
	s := installScript("/sd card/Synths", "/data/mpc-addins", "/tmp/x y", []*Package{p})
	for _, must := range []string{`'/sd card/Synths'`, `'Installing It'\''s; rm -rf / "x"'`, `'a'\''b - VST - $(x)'`} {
		if !strings.Contains(s, must) {
			t.Errorf("script must contain %s:\n%s", must, s)
		}
	}
}

// Hakai-enabled MPC systems have no acvs unit: MPC's service is inmusic-mpc, and the batch must stop and start that one.
func TestInstallUsesInmusicMpcServiceOnHakai(t *testing.T) {
	fd := newFakeDevice(t)
	os.WriteFile(filepath.Join(fd.dir, "svc"), []byte("inmusic-mpc\n"), 0o644)
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	j, err := runJob(t, fd, Item{Pkg: a})
	if err != nil {
		t.Fatal(err, j.Lines)
	}
	if got := strings.Join(fd.calls(), ","); got != "stop inmusic-mpc,start inmusic-mpc" {
		t.Fatalf("want stop/start of inmusic-mpc, got %v", got)
	}
}

// A zip with an old installer (no -n, `systemctl ... acvs` hard-coded) must still stop and start the real unit on a system without acvs.
func TestOldInstallerGetsInmusicMpcInPlaceOfAcvs(t *testing.T) {
	fd := newFakeDevice(t)
	os.WriteFile(filepath.Join(fd.dir, "svc"), []byte("inmusic-mpc\n"), 0o644)
	old := fakeInstaller("A", false, 0) + "systemctl stop acvs\nsystemctl start acvs\n"
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", old)
	j, err := runJob(t, fd, Item{Pkg: a})
	if err != nil {
		t.Fatal(err, j.Lines)
	}
	if got := strings.Join(fd.calls(), ","); got != "stop inmusic-mpc,start inmusic-mpc" {
		t.Fatalf("want the old installer's acvs calls turned into inmusic-mpc, got %v", got)
	}
}

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// "Register every plugin folder" after an install: a folder copied in by hand (never registered) ends up in MPC's plugin
// list along with the new plugin, MPC.settings is backed up, and MPC is stopped and started once.
func TestInstallCanRegisterEveryPluginFolder(t *testing.T) {
	fd := newFakeDevice(t)
	settings := writeSettings(fd, nil)
	card := fd.addCard("SSD")
	plugin(t, card, "hand - VST - Copied", "copied.so", "abcd0001", "Copied")
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	a.Defer = true
	j := &Job{ID: "x", State: "running"}
	if err := RunInstall(d, d.Info.primaryRoot(), []Item{{Pkg: a}}, t.TempDir(), j, nil, InstallOpts{Register: true}); err != nil {
		_, log, _, _ := j.snapshot(0)
		t.Fatalf("%v\n%s", err, strings.Join(log, "\n"))
	}
	b, _ := os.ReadFile(settings)
	if !strings.Contains(string(b), `uid="abcd0001"`) || !strings.Contains(string(b), card+"/hand - VST - Copied/copied.so") {
		t.Fatalf("the hand-copied folder was not registered:\n%s", b)
	}
	if got := fd.calls(); len(got) != 2 {
		t.Errorf("MPC calls %q, want one stop and one start", got)
	}
	if m, _ := filepath.Glob(filepath.Join(filepath.Dir(settings), "MPC.settings*")); len(m) < 2 {
		t.Errorf("no backup of MPC.settings next to it: %q", m)
	}
}

// Without the option nothing is registered or stopped for it; a failing install registers nothing.
func TestInstallWithoutRegisterLeavesHandCopiedFoldersAlone(t *testing.T) {
	fd := newFakeDevice(t)
	settings := writeSettings(fd, nil)
	card := fd.addCard("SSD")
	plugin(t, card, "hand - VST - Copied", "copied.so", "abcd0001", "Copied")
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	a.Defer = true
	if err := RunInstall(d, d.Info.primaryRoot(), []Item{{Pkg: a}}, t.TempDir(), &Job{ID: "x", State: "running"}, nil); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(settings); strings.Contains(string(b), `uid="abcd0001"`) {
		t.Fatalf("a folder was registered without the option:\n%s", b)
	}
	if got := fd.calls(); len(got) != 2 {
		t.Errorf("MPC calls %q, want one stop and one start", got)
	}

	os.Remove(fd.mpcLog)
	bad := installerPkg(t, "B-1", "b-plug", "me - VST - B", fakeInstaller("B", true, 1))
	bad.Defer = true
	j := &Job{ID: "y", State: "running"}
	if err := RunInstall(d, d.Info.primaryRoot(), []Item{{Pkg: bad}}, t.TempDir(), j, nil, InstallOpts{Register: true}); err == nil {
		t.Fatal("a failing installer must fail the job")
	}
	if b, _ := os.ReadFile(settings); strings.Contains(string(b), `uid="abcd0001"`) {
		t.Fatalf("registering ran after a failed install:\n%s", b)
	}
	if got := fd.calls(); len(got) != 2 {
		t.Errorf("MPC calls %q, want MPC started again after the failure", got)
	}
}

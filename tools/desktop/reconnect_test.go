package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The connection drops while a package is copied (a laptop waking from sleep, a VPN reconnecting): the app
// reconnects, copies again and installs, with MPC stopped and started once. A second drop gives up before MPC is touched.
func TestACopyThatLosesTheConnectionIsRetriedOnce(t *testing.T) {
	fd := newFakeDevice(t)
	writeSettings(fd, nil)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	a.Defer = true

	fd.dropOnCopy.Store(1)
	j := &Job{ID: "x", State: "running"}
	if err := RunInstall(d, d.Info.primaryRoot(), []Item{{Pkg: a}}, t.TempDir(), j, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(fd.cfg().SynthsDir, "me - VST - A")); err != nil {
		t.Fatal("not installed after the reconnect")
	}
	if _, log, _, _ := j.snapshot(0); !strings.Contains(strings.Join(log, "\n"), "Reconnecting") {
		t.Errorf("the log does not mention the reconnect: %q", log)
	}
	if got := fd.calls(); len(got) != 2 {
		t.Errorf("MPC calls %q, want one stop and one start", got)
	}

	fd.dropOnCopy.Store(2)
	os.Remove(fd.mpcLog)
	err = RunInstall(d, d.Info.primaryRoot(), []Item{{Pkg: a}}, t.TempDir(), &Job{ID: "y", State: "running"}, nil)
	if err == nil || !strings.Contains(err.Error(), "MPC was not stopped") {
		t.Fatalf("two drops must give up with a clear message: %v", err)
	}
	if got := fd.calls(); len(got) != 0 {
		t.Errorf("MPC was touched after the copy failed: %q", got)
	}
	if code, err := d.Run("true", nil, nil); err != nil || code != 0 { // and the device is usable again afterwards
		t.Errorf("the device connection did not recover: %d %v", code, err)
	}
}

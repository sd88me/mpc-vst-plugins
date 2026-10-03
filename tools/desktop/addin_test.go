package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// addinEntries: an addin release as tools/release_addin.py makes it, with the real installer from tools/release/addin.
func addinEntries(t *testing.T, top, id, version string) []zent {
	t.Helper()
	read := func(f string) string {
		b, err := os.ReadFile(filepath.Join("..", "release", "addin", f))
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	m, _ := json.Marshal(map[string]any{"schema": 1, "id": id, "name": "Test addin", "version": version, "kind": "addin", "layout": "addin",
		"so": "libtest.so", "conf": "test.conf", "files": []string{}, "arch": "armv7", "param_compat": 1})
	p := top + "/"
	return []zent{
		{p + "install.sh", 0o755, read("install.sh")},
		{p + "uninstall.sh", 0o755, read("uninstall.sh")},
		{p + "addin-lib.sh", 0o755, read("addin-lib.sh")},
		{p + "addin.manifest", 0, "ADDIN_ID=" + id + "\nADDIN_NAME=\"Test addin\"\nADDIN_SO=libtest.so\nADDIN_CONF=test.conf\nADDIN_VERSION=" + version + "\n"},
		{p + "libtest.so", 0, "ELF"},
		{p + "test.conf", 0, "x=1\n"},
		{p + "SHA256SUMS", 0, ""},
		{p + "mpc-plugin.json", 0, string(m)},
	}
}

func addinPkg(t *testing.T, id, version string) *Package {
	t.Helper()
	p, err := OpenPackage(writeZip(t, t.TempDir(), addinEntries(t, "Test-addin-"+version, id, version)), "upload")
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// unit gives the fake device MPC's service with a list it already preloads
func unit(t *testing.T, fd *fakeDevice) string {
	t.Helper()
	d := filepath.Join(fd.dir, "root", "usr", "lib", "systemd", "system")
	os.MkdirAll(d, 0o755)
	f := filepath.Join(d, "acvs.service")
	os.WriteFile(f, []byte("[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so\n"), 0o644)
	return f
}

func TestOpenPackageAddin(t *testing.T) {
	p := addinPkg(t, "test-addin", "1.0.0")
	if !p.Addin || !p.Defer || p.Bundle || p.Title != "Test addin" || p.Plugins[0].So != "libtest.so" {
		t.Fatalf("unexpected package: %+v", p)
	}
	ents := addinEntries(t, "T-1", "test-addin", "1.0.0")
	var noLib []zent
	for _, e := range ents {
		if !strings.HasSuffix(e.name, "/addin-lib.sh") {
			noLib = append(noLib, e)
		}
	}
	if _, err := OpenPackage(writeZip(t, t.TempDir(), noLib), "upload"); err == nil {
		t.Error("an addin without addin-lib.sh must be refused")
	}
	var bundle []zent
	for _, e := range ents {
		bundle = append(bundle, zent{strings.Replace(e.name, "T-1/", "B-1/sub/", 1), e.mode, e.body})
	}
	bundle = append(bundle, zent{"B-1/install.sh", 0o755, "#!/bin/sh\n\"$@\"\n"}, zent{"B-1/uninstall.sh", 0o755, "#!/bin/sh\n"})
	if _, err := OpenPackage(writeZip(t, t.TempDir(), bundle), "upload"); err == nil || !strings.Contains(err.Error(), "bundle") {
		t.Errorf("an addin inside a bundle must be refused: %v", err)
	}
}

func TestAddinInstallsWithAPluginInOneRestartAndIsRemoved(t *testing.T) {
	fd := newFakeDevice(t)
	u := unit(t, fd)
	plug := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	j, err := runJob(t, fd, Item{Pkg: plug}, Item{Pkg: addinPkg(t, "test-addin", "1.0.0")})
	if err != nil {
		t.Fatal(err, j.Lines)
	}
	if got := fd.calls(); strings.Join(got, ",") != "stop acvs,start acvs" {
		t.Fatalf("MPC must be stopped once and started once for the plugin and the addin, got %v", got)
	}
	dir := filepath.Join(fd.cfg().AddinsDir, "test-addin")
	for _, f := range []string{"libtest.so", "test.conf", "addin.manifest", "uninstall.sh", "addin-lib.sh"} {
		if _, err := os.Stat(filepath.Join(dir, f)); err != nil {
			t.Errorf("%s not installed: %v", f, err)
		}
	}
	if b, _ := os.ReadFile(u); !strings.Contains(string(b), "LD_PRELOAD=/usr/lib/x.so:"+dir+"/libtest.so") {
		t.Errorf("the addin is not added to LD_PRELOAD: %s", b)
	}
	if b, _ := os.ReadFile(filepath.Join(fd.dir, "addin.log")); strings.Contains(string(b), "restart") {
		t.Errorf("the addin installer must leave MPC to the app (-n): %s", b)
	}
	if state, _ := os.ReadFile(filepath.Join(fd.cfg().SynthsDir, ".mpc-store")); strings.Contains(string(state), "test-addin") {
		t.Errorf("an addin's version lives in its folder, not in .mpc-store: %q", state)
	}

	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	if len(d.Info.Addins) != 1 || d.Info.Addins[0] != (DevAddin{ID: "test-addin", Name: "Test addin", Version: "1.0.0", Removable: true}) {
		t.Fatalf("the device scan does not see the addin: %+v", d.Info.Addins)
	}
	d.Close()
	settings := filepath.Join(fd.dir, "Settings", "MPC", "MPC.settings")
	before, _ := os.ReadFile(settings)
	j, err = runRemove(t, fd, RemovePlan{Root: fd.cfg().AddinsDir, Folder: "test-addin", ID: "test-addin", Addin: true})
	if err != nil {
		t.Fatal(err, j.Lines)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Errorf("the addin folder must be gone: %v", err)
	}
	if b, _ := os.ReadFile(u); string(b) != "[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so\n" {
		t.Errorf("the unit must be as it was: %q", b)
	}
	if after, _ := os.ReadFile(settings); string(after) != string(before) {
		t.Errorf("MPC.settings must not be touched for an addin")
	}
	if baks, _ := filepath.Glob(settings + ".bak-*"); len(baks) != 0 {
		t.Errorf("no settings backup is needed for an addin: %v", baks)
	}
	if got := fd.calls(); strings.Join(got, ",") != "stop acvs,start acvs,stop acvs,start acvs" {
		t.Errorf("the removal stops and starts MPC once: %v", got)
	}
}

func TestAnAddinWithoutItsUninstallerIsListedButNotRemovable(t *testing.T) {
	fd := newFakeDevice(t)
	dir := filepath.Join(fd.cfg().AddinsDir, "old-addin")
	os.MkdirAll(dir, 0o755)
	os.WriteFile(filepath.Join(dir, "addin.manifest"), []byte("ADDIN_ID=old-addin\nADDIN_NAME=\"Old one\"   # shown\nADDIN_SO=libold.so\n"), 0o644)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if len(d.Info.Addins) != 1 || d.Info.Addins[0] != (DevAddin{ID: "old-addin", Name: "Old one"}) {
		t.Fatalf("unexpected: %+v", d.Info.Addins)
	}
	if err := (RemovePlan{Root: "/data/mpc-addins", Folder: "../x", Addin: true}).check(); err == nil {
		t.Error("an unsafe addin folder must be refused")
	}
}

func TestInstallScriptGivesAnAddinItsFolder(t *testing.T) {
	s := installScript("/sdcard/Synths", "/data/mpc-addins", "/tmp/x", []*Package{addinPkg(t, "test-addin", "1.0.0")})
	if !strings.Contains(s, `install.sh" -y -n -t '/data/mpc-addins/test-addin'`) || strings.Contains(s, "STATE.new") {
		t.Errorf("unexpected script:\n%s", s)
	}
}

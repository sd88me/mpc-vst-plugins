package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const gen2Cat = `{"schema":1,"plugins":[
 {"id":"both","name":"Both","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":10,"sha256":"%[1]s","url":"https://example.com/both-armv7.zip","channel":"stable","yanked":false,"gen2":true,
    "assets":{"armv7":{"size":10,"sha256":"%[1]s","url":"https://example.com/both-armv7.zip"},"aarch64":{"size":20,"sha256":"%[2]s","url":"https://example.com/both-aarch64.zip"}},
    "manifest":{"skin":"x"}}]},
 {"id":"gen1","name":"Gen1 only","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":10,"sha256":"%[1]s","url":"https://example.com/g1.zip","channel":"stable","yanked":false,"manifest":{"skin":"x"}}]},
 {"id":"bad64","name":"Bad64","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":10,"sha256":"%[1]s","url":"https://example.com/b.zip","channel":"stable","yanked":false,
    "assets":{"aarch64":{"size":20,"sha256":"short","url":"http://example.com/plain.zip"}},"manifest":{"skin":"x"}}]}]}`

func gen2Plugins(t *testing.T) map[string]CatPlugin {
	t.Helper()
	raw := strings.NewReplacer("%[1]s", strings.Repeat("a", 64), "%[2]s", strings.Repeat("b", 64)).Replace(gen2Cat)
	got, err := parseCatalog([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	by := map[string]CatPlugin{}
	for _, c := range got {
		by[c.ID] = c
	}
	return by
}

func TestParseCatalogReadsTheAarch64Asset(t *testing.T) {
	by := gen2Plugins(t)
	if b := by["both"]; !b.Gen2 || b.Aarch64 == nil || b.Aarch64.URL != "https://example.com/both-aarch64.zip" || b.URL != "https://example.com/both-armv7.zip" {
		t.Errorf("both: %+v", b)
	}
	if g := by["gen1"]; g.Gen2 || g.Aarch64 != nil {
		t.Errorf("gen1: %+v", g)
	}
	if b := by["bad64"]; b.Gen2 || b.Aarch64 != nil {
		t.Errorf("an aarch64 asset that is not https or has no sha256 must be ignored: %+v", b)
	}
}

func TestForArchPicksTheZipForTheDevice(t *testing.T) {
	by := gen2Plugins(t)
	c, err := by["both"].ForArch("armv7l")
	if err != nil || c.URL != "https://example.com/both-armv7.zip" || c.Size != 10 {
		t.Errorf("Gen1: %+v %v", c, err)
	}
	c, err = by["both"].ForArch("aarch64")
	if err != nil || c.URL != "https://example.com/both-aarch64.zip" || c.Size != 20 || c.SHA256 != strings.Repeat("b", 64) {
		t.Errorf("Gen2: %+v %v", c, err)
	}
	if _, err := by["gen1"].ForArch("aarch64"); err == nil || !strings.Contains(err.Error(), "no Gen2") {
		t.Errorf("a Gen1-only plugin on a Gen2 device must be refused, got %v", err)
	}
	if c, err := by["gen1"].ForArch("armv7l"); err != nil || c.URL != "https://example.com/g1.zip" {
		t.Errorf("Gen1-only on Gen1: %+v %v", c, err)
	}
	if _, err := (CatPlugin{Kind: "addin", Name: "A", Aarch64: &Asset{}}).ForArch("aarch64"); err == nil {
		t.Error("addins are armv7 only")
	}
}

func TestArchFits(t *testing.T) {
	for _, c := range []struct {
		pkg, dev string
		want     bool
	}{
		{"armv7", "armv7l", true}, {"", "armv7l", true}, {"aarch64", "aarch64", true},
		{"armv7", "aarch64", false}, {"aarch64", "armv7l", false}, {"aarch64", "x86_64", false}, {"armv7", "x86_64", false},
	} {
		if got := archFits(c.pkg, c.dev); got != c.want {
			t.Errorf("archFits(%q, %q) = %v", c.pkg, c.dev, got)
		}
	}
}

func TestOpenPackageAcceptsAnAarch64Plugin(t *testing.T) {
	p := arch64Pkg(t, "A-1", "a-plug", "me - VST - A", "aarch64")
	if len(p.Plugins) != 1 || p.Plugins[0].Arch != "aarch64" {
		t.Fatalf("%+v", p.Plugins)
	}
	if _, err := OpenPackage(writeZip(t, t.TempDir(), pluginEntries("A-1", "", "a-plug", "me - VST - A", "#!/bin/sh\n", func(m *Manifest) { m.Arch = "x86_64" })), "upload"); err == nil {
		t.Error("an x86_64 package must be refused")
	}
}

func arch64Pkg(t *testing.T, top, id, skin, arch string) *Package {
	t.Helper()
	p, err := OpenPackage(writeZip(t, t.TempDir(), pluginEntries(top, "", id, skin, fakeInstaller("A", true, 0), func(m *Manifest) { m.Arch = arch })), "upload")
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func setUname(fd *fakeDevice, arch string) {
	os.WriteFile(filepath.Join(fd.shims, "uname"), []byte("#!/bin/sh\necho "+arch+"\n"), 0o755)
}

func TestAGen2DeviceTakesAnAarch64PackageAndRefusesAnArmv7One(t *testing.T) {
	fd := newFakeDevice(t)
	setUname(fd, "aarch64")
	if _, err := runJob(t, fd, Item{Pkg: arch64Pkg(t, "A-1", "a-plug", "me - VST - A", "aarch64")}); err != nil {
		t.Fatalf("the Gen2 package must install on a Gen2 device: %v", err)
	}
	if _, err := os.Stat(filepath.Join(fd.dir, "Synths", "me - VST - A")); err != nil {
		t.Errorf("not installed: %v", err)
	}
	fd2 := newFakeDevice(t)
	setUname(fd2, "aarch64")
	_, err := runJob(t, fd2, Item{Pkg: arch64Pkg(t, "B-1", "b-plug", "me - VST - B", "armv7")})
	if err == nil || !strings.Contains(err.Error(), "-mpc-aarch64.zip") {
		t.Fatalf("an armv7 zip on a Gen2 device must be refused with the right zip named, got %v", err)
	}
	if len(fd2.calls()) != 0 {
		t.Error("MPC must not be touched")
	}
}

func TestAGen1DeviceRefusesAnAarch64Package(t *testing.T) {
	fd := newFakeDevice(t)
	_, err := runJob(t, fd, Item{Pkg: arch64Pkg(t, "A-1", "a-plug", "me - VST - A", "aarch64")})
	if err == nil || !strings.Contains(err.Error(), "-mpc-armv7.zip") {
		t.Fatalf("expected a refusal naming the armv7 zip, got %v", err)
	}
	if len(fd.calls()) != 0 {
		t.Error("MPC must not be touched")
	}
	if ents, _ := os.ReadDir(fd.cfg().RemoteTmp); len(ents) != 0 {
		t.Errorf("nothing may be copied: %v", ents)
	}
}

func TestAGen2DeviceRefusesACatalogPluginWithNoGen2Build(t *testing.T) {
	fd := newFakeDevice(t)
	setUname(fd, "aarch64")
	c := gen2Plugins(t)["gen1"]
	_, err := runJob(t, fd, Item{Catalog: &c})
	if err == nil || !strings.Contains(err.Error(), "no Gen2") {
		t.Fatalf("expected a refusal, got %v", err)
	}
	if len(fd.calls()) != 0 {
		t.Error("MPC must not be touched")
	}
}

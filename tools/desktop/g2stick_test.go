package main

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func sum(s string) string { h := sha256.Sum256([]byte(s)); return hex.EncodeToString(h[:]) }

const (
	g2A = "g2/Plugin-Manager-G2-0.2.1-mpc-armv7.zip"
	g2B = "g2/Plugin-Manager-G2-0.2.1-mpc-aarch64.zip"
)

// goodG2 is a minimal Level 1 bundle; tests change one thing at a time.
func goodG2() map[string]string {
	return map[string]string{
		"autorun/autorun.json": "{}", "autorun/autorun.check": "x", "autorun/open.sh": "#!/bin/sh",
		"autorun/runtime/run.sh": "#!/bin/sh", ".mpc-g2-stick": "mpc-usb-g2-v1\n",
		"autorun/runtime/payload.sha256": sum("armv7") + "  " + g2A + "\n" + sum("aarch64") + "  " + g2B + "\n",
		g2A:                              "armv7", g2B: "aarch64",
	}
}

func TestG2BundleAccepted(t *testing.T) {
	d := t.TempDir()
	if err := WriteG2Stick(d, easyZip(t, goodG2())); err != nil {
		t.Fatal(err)
	}
	for _, p := range g2StickNeed {
		if _, err := os.Stat(filepath.Join(d, filepath.FromSlash(p))); err != nil {
			t.Errorf("missing %s", p)
		}
	}
}

func TestG2BundleRefusals(t *testing.T) {
	cases := map[string]func(m map[string]string){
		"a package that doesn't match its checksum": func(m map[string]string) { m[g2A] = "swapped" },
		"a missing package":                         func(m map[string]string) { delete(m, g2B) },
		"an unlisted extra package": func(m map[string]string) {
			m["g2/Plugin-Manager-G2-0.2.1-mpc-extra.zip"] = "x"
		},
		"a missing boot check": func(m map[string]string) { delete(m, "autorun/autorun.check") },
		"a missing marker":     func(m map[string]string) { delete(m, ".mpc-g2-stick") },
		"a list with one arch only": func(m map[string]string) {
			m["autorun/runtime/payload.sha256"] = sum("armv7") + "  " + g2A + "\n"
			delete(m, g2B)
		},
		"two packages for one CPU": func(m map[string]string) {
			n := "g2/Plugin-Manager-G2-0.2.0-mpc-armv7.zip"
			m["autorun/runtime/payload.sha256"] += sum("old") + "  " + n + "\n"
			m[n] = "old"
		},
		"a list entry outside g2/": func(m map[string]string) {
			m["autorun/runtime/payload.sha256"] += sum("x") + "  ../evil.zip\n"
		},
	}
	for name, mut := range cases {
		m := goodG2()
		mut(m)
		d := t.TempDir()
		if err := WriteG2Stick(d, easyZip(t, m)); err == nil {
			t.Errorf("%s accepted", name)
		}
		if des, _ := os.ReadDir(d); len(des) != 0 {
			t.Errorf("%s: wrote files before refusing", name)
		}
	}
}

func TestG2BundleRefusesANonEmptyDrive(t *testing.T) {
	d := t.TempDir()
	os.WriteFile(filepath.Join(d, "keep.txt"), []byte("x"), 0644)
	if err := WriteG2Stick(d, easyZip(t, goodG2())); err == nil {
		t.Fatal("written onto a non-empty folder")
	}
}

func TestG2PinNeedsAReleaseUnderOurRepo(t *testing.T) {
	old := g2PinURL
	t.Cleanup(func() { g2PinURL = old })
	for name, body := range map[string]string{
		"empty":     `{"version":"","url":"","sha256":""}`,
		"elsewhere": `{"version":"v1","url":"https://evil.example/x.zip","sha256":"` + strings.Repeat("a", 64) + `"}`,
		"bad hash":  `{"version":"v1","url":"` + g2ReleasePrefix + `x.zip","sha256":"zz"}`,
	} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(body)) }))
		g2PinURL = srv.URL
		if _, err := currentG2Pin(); err == nil {
			t.Errorf("%s pin accepted", name)
		}
		srv.Close()
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"version":"g2-stick-0.2.1","url":"` + g2ReleasePrefix + `x.zip","sha256":"` + strings.Repeat("a", 64) + `"}`))
	}))
	defer srv.Close()
	g2PinURL = srv.URL
	if p, err := currentG2Pin(); err != nil || p.Version != "g2-stick-0.2.1" {
		t.Fatalf("good pin refused: %v", err)
	}
}

func TestShippedG2PinIsValid(t *testing.T) {
	b, err := os.ReadFile("g2stick-pin.json")
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write(b) }))
	defer srv.Close()
	old := g2PinURL
	g2PinURL = srv.URL
	defer func() { g2PinURL = old }()
	if _, err := currentG2Pin(); err != nil {
		t.Fatalf("the shipped g2stick-pin.json is not a valid pin: %v", err)
	}
}

func TestFetchG2StickChecksTheHash(t *testing.T) {
	body := easyZip(t, goodG2())
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write(body) }))
	defer srv.Close()
	h := sha256.Sum256(body)
	if data, err := fetchG2Stick(easyPin{Version: "v", URL: srv.URL, SHA256: hex.EncodeToString(h[:])}); err != nil || len(data) != len(body) {
		t.Fatalf("matching hash refused: %v", err)
	}
	if _, err := fetchG2Stick(easyPin{Version: "v", URL: srv.URL, SHA256: strings.Repeat("0", 64)}); err == nil {
		t.Fatal("a wrong hash was accepted")
	}
}

func postG2(t *testing.T, in string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	(&App{}).stickG2(rec, httptest.NewRequest("POST", "/api/stick/g2", strings.NewReader(in)))
	return rec
}

func TestStickG2EndpointWritesALocalBundleAndRefusesWithoutOne(t *testing.T) {
	old := g2PinURL
	g2PinURL = ""
	t.Cleanup(func() { g2PinURL = old })
	bundle := filepath.Join(t.TempDir(), "b.zip")
	os.WriteFile(bundle, easyZip(t, goodG2()), 0644)
	out := t.TempDir()
	if rec := postG2(t, `{"Out":"`+out+`","Bundle":"`+bundle+`"}`); rec.Code != 200 {
		t.Fatalf("local bundle: %d %s", rec.Code, rec.Body)
	}
	if _, err := os.Stat(filepath.Join(out, "autorun", "open.sh")); err != nil {
		t.Fatal("not written")
	}
	empty := t.TempDir()
	if rec := postG2(t, `{"Out":"`+empty+`"}`); rec.Code != 404 {
		t.Fatalf("no bundle and no pin should be a 404, got %d", rec.Code)
	}
	if des, _ := os.ReadDir(empty); len(des) != 0 {
		t.Fatal("wrote something without a bundle")
	}
}

func TestLooksGen2ByNameOrByAarch64Executable(t *testing.T) {
	d := t.TempDir()
	write := func(name string, b []byte) string {
		p := filepath.Join(d, name)
		os.WriteFile(p, b, 0644)
		return p
	}
	elf := func(machine byte) []byte {
		h := make([]byte, 64)
		copy(h, "\x7fELF")
		h[18] = machine
		return h
	}
	for name, c := range map[string]struct {
		path string
		want bool
	}{
		"gen2 name":      {write("MPC-3.9.1-Gen2-update.img", []byte("x")), true},
		"aarch64 binary": {write("MPC", elf(183)), true},
		"arm binary":     {write("MPC-arm", elf(40)), false},
		"plain image":    {write("MPC-3.9.1-update.img", []byte("not an elf")), false},
		"missing":        {filepath.Join(d, "nope"), false},
	} {
		if got := looksGen2(c.path); got != c.want {
			t.Errorf("%s: looksGen2 = %v, want %v", name, got, c.want)
		}
	}
}

func TestStickBuildRefusesAPasswordForAGen2Firmware(t *testing.T) {
	a := &App{stickScan: map[string]*stickScan{"h": {Firmware: "x", Salt: []byte("s"), Gen2: true}}}
	out := t.TempDir()
	rec := httptest.NewRecorder()
	a.stickBuild(rec, httptest.NewRequest("POST", "/api/stick/build", strings.NewReader(`{"ScanHandle":"h","Out":"`+out+`","SSHPassword":"force"}`)))
	if rec.Code != 400 || !strings.Contains(rec.Body.String(), "Gen2") {
		t.Fatalf("password for Gen2: %d %s", rec.Code, rec.Body)
	}
	if des, _ := os.ReadDir(out); len(des) != 0 {
		t.Fatal("wrote a stick anyway")
	}
}

// A tester's "can't use that bundle file": a quoted path, a ~ path, or the folder Safari unpacked the zip into.
func TestLoadG2BundleAcceptsTheWaysPeopleNameAFile(t *testing.T) {
	d := t.TempDir()
	zipPath := filepath.Join(d, "bundle.zip")
	body := easyZip(t, goodG2())
	os.WriteFile(zipPath, body, 0644)
	t.Setenv("HOME", d)
	t.Setenv("USERPROFILE", d)
	for name, p := range map[string]string{
		"plain":  zipPath,
		"quoted": `"` + zipPath + `"`,
		"single": `'` + zipPath + `'`,
		"padded": "  " + zipPath + "\n",
		"home":   "~/bundle.zip",
	} {
		got, err := loadG2Bundle(p)
		if err != nil || len(got) != len(body) {
			t.Errorf("%s: %v", name, err)
		}
	}
	// the folder an archive tool unpacked it into (hidden marker file and all) goes through the same check
	unpacked := filepath.Join(d, "unpacked")
	for n, c := range goodG2() {
		os.MkdirAll(filepath.Dir(filepath.Join(unpacked, n)), 0755)
		os.WriteFile(filepath.Join(unpacked, n), []byte(c), 0644)
	}
	os.WriteFile(filepath.Join(unpacked, ".DS_Store"), []byte("x"), 0644)
	data, err := loadG2Bundle(unpacked)
	if err != nil {
		t.Fatal(err)
	}
	if err := WriteG2Stick(t.TempDir(), data); err != nil {
		t.Fatalf("an unpacked bundle folder was refused: %v", err)
	}
}

func TestLoadG2BundleSaysWhatIsWrong(t *testing.T) {
	d := t.TempDir()
	if _, err := loadG2Bundle(filepath.Join(d, "nope.zip")); err == nil || !strings.Contains(err.Error(), "can't find that bundle") {
		t.Errorf("a missing file: %v", err)
	}
	if _, err := loadG2Bundle(d); err == nil || !strings.Contains(err.Error(), "is a folder, not the bundle") {
		t.Errorf("an ordinary folder: %v", err)
	}
	os.WriteFile(filepath.Join(d, "x.zip"), []byte("not a zip"), 0644)
	if data, err := loadG2Bundle(filepath.Join(d, "x.zip")); err != nil {
		t.Fatal(err)
	} else if err := checkG2Bundle(data); err == nil || !strings.Contains(err.Error(), "not a zip") {
		t.Errorf("a file that is not a zip: %v", err)
	}
}

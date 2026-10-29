package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func easyZip(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var b bytes.Buffer
	zw := zip.NewWriter(&b)
	for n, c := range files {
		w, err := zw.Create(n)
		if err != nil {
			t.Fatal(err)
		}
		w.Write([]byte(c))
	}
	zw.Close()
	return b.Bytes()
}

var goodEasy = map[string]string{
	"autorun/autorun.json": "{}", "autorun/autorun.check": "x", "autorun/open.sh": "#!/bin/sh",
	"autorun/runtime/aarch64/manager": "bin", ".mpc-manager-id": "id", "local-plugins/": "",
}

func TestWriteEasyStickUnpacksOntoAnEmptyDriveWithHousekeeping(t *testing.T) {
	d := t.TempDir()
	os.Mkdir(filepath.Join(d, "System Volume Information"), 0755)
	if err := WriteEasyStick(d, easyZip(t, goodEasy)); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"autorun/open.sh", "autorun/runtime/aarch64/manager", ".mpc-manager-id", "local-plugins"} {
		if _, err := os.Stat(filepath.Join(d, filepath.FromSlash(p))); err != nil {
			t.Errorf("missing %s: %v", p, err)
		}
	}
}

func TestWriteEasyStickRefusesANonEmptyFolder(t *testing.T) {
	d := t.TempDir()
	os.WriteFile(filepath.Join(d, "song.wav"), []byte("x"), 0644)
	if err := WriteEasyStick(d, easyZip(t, goodEasy)); err == nil || !strings.Contains(err.Error(), "not empty") {
		t.Fatalf("want a not-empty refusal, got %v", err)
	}
}

func TestWriteEasyStickRefusesAPathOutsideTheDrive(t *testing.T) {
	for _, bad := range []string{"../evil", "/abs", "a/../../evil", `..\evil`} {
		d := t.TempDir()
		files := map[string]string{bad: "x"}
		for k, v := range goodEasy {
			files[k] = v
		}
		if err := WriteEasyStick(d, easyZip(t, files)); err == nil {
			t.Errorf("%q accepted", bad)
		}
		if des, _ := os.ReadDir(d); len(des) != 0 {
			t.Errorf("%q: wrote %d entries before refusing", bad, len(des))
		}
	}
}

func TestWriteEasyStickRequiresTheAutorunFiles(t *testing.T) {
	if err := WriteEasyStick(t.TempDir(), easyZip(t, map[string]string{"readme.txt": "x"})); err == nil {
		t.Fatal("a zip without autorun accepted")
	}
}

func serveEasy(t *testing.T, body []byte, pin string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write(body) }))
	oldURL, oldSum := easyStickURL, easyStickSHA256
	easyStickURL, easyStickSHA256 = srv.URL, pin
	t.Cleanup(func() { srv.Close(); easyStickURL, easyStickSHA256 = oldURL, oldSum })
}

func TestFetchEasyStickRefusesAWrongHash(t *testing.T) {
	serveEasy(t, easyZip(t, goodEasy), strings.Repeat("0", 64))
	if _, err := fetchEasyStick(); err == nil || !strings.Contains(err.Error(), "checksum") {
		t.Fatalf("a download with the wrong hash must be refused, got %v", err)
	}
}

func TestFetchEasyStickAcceptsTheMatchingHash(t *testing.T) {
	good := easyZip(t, goodEasy)
	sum := sha256.Sum256(good)
	serveEasy(t, good, hex.EncodeToString(sum[:]))
	if _, err := fetchEasyStick(); err != nil {
		t.Fatal(err)
	}
}

func init() { easyPinURL = "" } // tests never reach the network; the pin-file tests set their own server

func servePin(t *testing.T, body string, status int) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		w.Write([]byte(body))
	}))
	old := easyPinURL
	easyPinURL = srv.URL
	t.Cleanup(func() { srv.Close(); easyPinURL = old })
}

func TestPinFileOverridesTheCompiledInRelease(t *testing.T) {
	servePin(t, `{"version":"v9.9.9","url":"`+easyReleasePrefix+`v9.9.9/x.zip","sha256":"`+strings.Repeat("a", 64)+`"}`, 200)
	if p := currentEasyPin(); p.Version != "v9.9.9" || p.SHA256 != strings.Repeat("a", 64) {
		t.Fatalf("pin file ignored: %+v", p)
	}
}

func TestBadPinFilesFallBackToTheCompiledInRelease(t *testing.T) {
	good := strings.Repeat("a", 64)
	for name, c := range map[string]struct {
		body   string
		status int
	}{
		"other host":         {`{"version":"v1","url":"https://evil.example/x.zip","sha256":"` + good + `"}`, 200},
		"another repository": {`{"version":"v1","url":"https://github.com/someone-else/plugin-manager-usb-for-open-mpc/releases/download/v1/x.zip","sha256":"` + good + `"}`, 200},
		"short hash":         {`{"version":"v1","url":"` + easyReleasePrefix + `v1/x.zip","sha256":"abc"}`, 200},
		"not json":           {`nope`, 200},
		"http error":         {`{}`, 500},
		"no version":         {`{"url":"` + easyReleasePrefix + `v1/x.zip","sha256":"` + good + `"}`, 200},
	} {
		servePin(t, c.body, c.status)
		if p := currentEasyPin(); p != builtinEasyPin() {
			t.Errorf("%s: used %+v instead of the compiled-in pin", name, p)
		}
	}
}

func TestBothTheUpstreamAndTheForkReleasePrefixAreAccepted(t *testing.T) {
	for _, prefix := range easyReleasePrefixes {
		if !(easyPin{Version: "v1", URL: prefix + "v1/x.zip", SHA256: strings.Repeat("a", 64)}).valid() {
			t.Errorf("%s refused", prefix)
		}
	}
	if (easyPin{Version: "v1", URL: "https://github.com/sd88me/other/releases/download/v1/x.zip", SHA256: strings.Repeat("a", 64)}).valid() {
		t.Error("a repository outside the allowlist was accepted")
	}
}

func TestShippedPinFileIsValid(t *testing.T) {
	b, err := os.ReadFile("easystick-pin.json")
	if err != nil {
		t.Fatal(err)
	}
	var p easyPin
	if err := json.Unmarshal(b, &p); err != nil || !p.valid() {
		t.Fatalf("easystick-pin.json invalid: %v %+v", err, p)
	}
}

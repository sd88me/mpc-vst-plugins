package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

const goodPatchJSON = `{"schema":1,"patches":[
 {"id":"drum-pad-layout","title":"Drum layout","summary":"s","author":"a","license":"MIT","docs":"d",
  "script":{"url":"https://example.org/abc/p.sh","sha256":"%s"},"supports":{"os":"MPC OS 3.9.1.2","arch":"armv7l","mpc_md5":["592eebc8e1ce0797dc8c98e7002143b8"]},
  "modifies":["/usr/bin/MPC"],"backup":"/sdcard/MPC-backup","restarts_mpc":true,"reversible":true}]}`

func TestParsePatchesKeepsOnlyWhatIsSafe(t *testing.T) {
	sum := strings.Repeat("a", 64)
	got, err := parsePatches([]byte(fmt.Sprintf(goodPatchJSON, sum)))
	if err != nil || len(got) != 1 || got[0].ID != "drum-pad-layout" || !got[0].RestartsMPC {
		t.Fatalf("good manifest: %v %+v", err, got)
	}
	for name, mut := range map[string]func(string) string{
		"http script":    func(s string) string { return strings.Replace(s, "https://example.org", "http://example.org", 1) },
		"short hash":     func(s string) string { return strings.Replace(s, sum, "abc", 1) },
		"not reversible": func(s string) string { return strings.Replace(s, `"reversible":true`, `"reversible":false`, 1) },
		"relative path":  func(s string) string { return strings.Replace(s, `"/usr/bin/MPC"`, `"usr/bin/MPC"`, 1) },
		"bad id":         func(s string) string { return strings.Replace(s, "drum-pad-layout", "Drum Pad!", 1) },
		"no arch":        func(s string) string { return strings.Replace(s, `"arch":"armv7l"`, `"arch":""`, 1) },
	} {
		if got, err := parsePatches([]byte(mut(fmt.Sprintf(goodPatchJSON, sum)))); err != nil || len(got) != 0 {
			t.Errorf("%s must be dropped: %v %+v", name, err, got)
		}
	}
	if _, err := parsePatches([]byte(`{"schema":2,"patches":[]}`)); err == nil {
		t.Error("an unknown schema must be refused")
	}
}

func TestPatchesURLIsNextToTheCatalog(t *testing.T) {
	if got := patchesURLFor("https://sd88me.github.io/mpc-vst-plugins/catalog.json?x=1"); got != "https://sd88me.github.io/mpc-vst-plugins/patches.json" {
		t.Errorf("got %q", got)
	}
	if patchesURLFor("not a url") != "" {
		t.Error("garbage gives no url")
	}
}

func TestParseStateLineReadsTheChecksum(t *testing.T) {
	st, ok := parseStateLine([]string{"STATE state=unsupported supported=0 backup=1 checksum=7cf96599ec61b1079688f253f3b65b9f"})
	if !ok || st.Checksum != "7cf96599ec61b1079688f253f3b65b9f" || !st.Backup {
		t.Errorf("checksum: %v %+v", ok, st)
	}
	if st, ok := parseStateLine([]string{"STATE state=stock supported=1 backup=0 checksum=not-a-hash"}); !ok || st.Checksum != "" {
		t.Errorf("a malformed checksum is dropped: %v %+v", ok, st)
	}
	if st, ok := parseStateLine([]string{"STATE state=stock supported=1 backup=0"}); !ok || st.Checksum != "" {
		t.Errorf("older scripts have no checksum: %v %+v", ok, st)
	}
}

func TestUnsupportedRowSaysWhy(t *testing.T) {
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	var p Patch
	p.ID, p.Supports.Arch, p.Supports.OS, p.Supports.MPCMD5 = "x", "armv7l", "MPC OS 3.9.1.2", []string{"592eebc8e1ce0797dc8c98e7002143b8"}
	script := "#!/bin/sh\necho 'MPC checksum: 7cf96599ec61b1079688f253f3b65b9f'\necho 'STATE state=unsupported supported=0 backup=1 checksum=7cf96599ec61b1079688f253f3b65b9f'\n"
	rows := PatchRows(d, []Patch{p}, func(Patch) ([]byte, error) { return []byte(script), nil })
	for _, want := range []string{"7cf96599ec61b1079688f253f3b65b9f", "MPC OS 3.9.1.2", "592eebc8e1ce0797dc8c98e7002143b8", "backup from an earlier install"} {
		if rows[0].State != "unsupported" || !strings.Contains(rows[0].Detail, want) {
			t.Errorf("the detail must mention %q: %+v", want, rows[0])
		}
	}
	// no backup: no advice about restoring
	script = strings.Replace(script, "backup=1", "backup=0", 1)
	if rows := PatchRows(d, []Patch{p}, func(Patch) ([]byte, error) { return []byte(script), nil }); strings.Contains(rows[0].Detail, "backup") {
		t.Errorf("no backup, no restore advice: %+v", rows[0])
	}
}

func TestParseStateLine(t *testing.T) {
	st, ok := parseStateLine([]string{"hello", "STATE state=stock supported=1 backup=0", "STATE state=patched supported=1 backup=1", ""})
	if !ok || st.State != "patched" || !st.Supported || !st.Backup {
		t.Errorf("the last STATE line wins: %v %+v", ok, st)
	}
	if st, ok := parseStateLine([]string{"STATE state=unsupported supported=0 backup=0"}); !ok || st.Supported || st.State != "unsupported" {
		t.Errorf("unsupported: %v %+v", ok, st)
	}
	for _, bad := range [][]string{nil, {"State: stock"}, {"STATE state=whatever supported=1 backup=0"}, {"STATE"}} {
		if _, ok := parseStateLine(bad); ok {
			t.Errorf("%q must not parse", bad)
		}
	}
}

// servePatches serves a manifest and a script over TLS and points the patch client at it. calls counts script downloads.
func servePatches(t *testing.T, script string, tamper bool) (manifestURL string, calls *int32) {
	t.Helper()
	sum := sha256.Sum256([]byte(script))
	hexsum := hex.EncodeToString(sum[:])
	var n int32
	var base string
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/patches.json":
			w.Write([]byte(strings.Replace(fmt.Sprintf(goodPatchJSON, hexsum), "https://example.org/abc", base, 1)))
		case "/p.sh":
			atomic.AddInt32(&n, 1)
			if tamper {
				w.Write([]byte(script + "\necho pwned\n"))
				return
			}
			w.Write([]byte(script))
		default:
			http.NotFound(w, r)
		}
	}))
	base = srv.URL
	t.Cleanup(srv.Close)
	old := patchClient
	patchClient = srv.Client()
	t.Cleanup(func() { patchClient = old })
	return srv.URL + "/patches.json", &n
}

// a stand-in for a patch script: records its arguments, answers status, refuses anything else
func fakePatchScript(logFile string) string {
	return "#!/bin/sh\necho \"$*\" >> " + shQuote(logFile) + "\n" +
		`[ "$1" = status ] || { echo "ERROR: unexpected $1"; exit 2; }` + "\n" +
		"echo 'some human text'\necho 'STATE state=stock supported=1 backup=0'\n"
}

func TestFetchPatchScriptRefusesAWrongHash(t *testing.T) {
	murl, _ := servePatches(t, "#!/bin/sh\necho hi\n", true)
	ps, err := FetchPatches(murl)
	if err != nil || len(ps) != 1 {
		t.Fatalf("manifest: %v %+v", err, ps)
	}
	if _, err := FetchPatchScript(ps[0]); err == nil || !strings.Contains(err.Error(), "checksum") {
		t.Errorf("a script that does not match the manifest must be refused: %v", err)
	}
}

func TestFetchPatchesNotPublishedIsNotAnError(t *testing.T) {
	murl, _ := servePatches(t, "x", false)
	if _, err := FetchPatches(strings.Replace(murl, "patches.json", "gone.json", 1)); err != errNoPatches {
		t.Errorf("a 404 means nothing is published: %v", err)
	}
}

func TestPatchStatusRunsOnlyStatusAndCleansUp(t *testing.T) {
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	logFile := filepath.Join(fd.dir, "patch.log")
	st, err := d.PatchStatus([]byte(fakePatchScript(logFile)))
	if err != nil || st.State != "stock" || !st.Supported || st.Backup {
		t.Fatalf("status: %v %+v", err, st)
	}
	if b, _ := os.ReadFile(logFile); strings.TrimSpace(string(b)) != "status" {
		t.Errorf("only `status` may run, got %q", b)
	}
	if left, _ := filepath.Glob(filepath.Join(fd.dir, "tmp", "mpc-patch-*")); len(left) != 0 {
		t.Errorf("the copy on the device must be removed: %v", left)
	}
	// a script that prints STATE but fails is not trusted; one that prints no STATE is an error too
	if _, err := d.PatchStatus([]byte("#!/bin/sh\necho 'STATE state=patched supported=1 backup=1'\nexit 3\n")); err == nil {
		t.Error("a non-zero exit must be an error")
	}
	if _, err := d.PatchStatus([]byte("#!/bin/sh\necho 'ERROR: not root'\nexit 1\n")); err == nil || !strings.Contains(err.Error(), "not root") {
		t.Errorf("no STATE line: %v", err)
	}
	if left, _ := filepath.Glob(filepath.Join(fd.dir, "tmp", "mpc-patch-*")); len(left) != 0 {
		t.Errorf("the copy must be removed after a failure too: %v", left)
	}
}

func TestPatchRowsOnlyAskTheDeviceWhenItCanAnswer(t *testing.T) {
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	var p Patch
	p.ID, p.Supports.Arch = "x", "armv7l"
	asked := 0
	fetch := func(Patch) ([]byte, error) { asked++; return []byte(fakePatchScript(filepath.Join(fd.dir, "l"))), nil }
	if rows := PatchRows(nil, []Patch{p}, fetch); rows[0].State != "not-checked" || asked != 0 {
		t.Errorf("not connected: %+v asked=%d", rows[0], asked)
	}
	other := p
	other.Supports.Arch = "aarch64"
	if rows := PatchRows(d, []Patch{other}, fetch); rows[0].State != "unsupported" || asked != 0 {
		t.Errorf("another architecture is not asked: %+v asked=%d", rows[0], asked)
	}
	if rows := PatchRows(d, []Patch{p}, func(Patch) ([]byte, error) { return nil, fmt.Errorf("checksum") }); rows[0].State != "error" || !strings.Contains(rows[0].Detail, "checksum") {
		t.Errorf("a refused script is an error row: %+v", rows[0])
	}
	if rows := PatchRows(d, []Patch{p}, fetch); rows[0].State != "stock" || !rows[0].Supported {
		t.Errorf("connected: %+v", rows[0])
	}
}

func TestPatchesEndpointIsReadOnly(t *testing.T) {
	h := newHarness(t)
	logFile := filepath.Join(h.fd.dir, "patch.log")
	murl, scriptCalls := servePatches(t, fakePatchScript(logFile), false)
	h.app.patchesURL = murl
	old := http.DefaultTransport
	http.DefaultTransport = patchClient.Transport // the harness talks plain http to the app; the patch client talks TLS to the stand-in site
	t.Cleanup(func() { http.DefaultTransport = old })

	_, body := h.do("GET", "/api/patches", nil, nil)
	if !strings.Contains(string(body), `"state":"not-checked"`) || !strings.Contains(string(body), `"connected":false`) {
		t.Fatalf("not connected: %s", body)
	}
	if atomic.LoadInt32(scriptCalls) != 0 {
		t.Error("nothing is downloaded before there is a device to ask")
	}
	if code, _ := h.post("/api/connect", map[string]string{"host": "127.0.0.1", "password": "secret"}); code != 200 {
		t.Fatal("connect")
	}
	_, body = h.do("GET", "/api/patches", nil, nil)
	if !strings.Contains(string(body), `"state":"stock"`) || !strings.Contains(string(body), `"connected":true`) {
		t.Fatalf("connected: %s", body)
	}
	if b, _ := os.ReadFile(logFile); strings.TrimSpace(string(b)) != "status" {
		t.Errorf("only `status` may ever run here, got %q", b)
	}
	h.do("GET", "/api/patches", nil, nil) // the verified script is kept: not downloaded again
	if n := atomic.LoadInt32(scriptCalls); n != 1 {
		t.Errorf("the script is downloaded once, got %d", n)
	}
	// while a job runs the device is left alone
	os.Remove(logFile)
	h.app.job = &Job{ID: "j", State: "running"}
	_, body = h.do("GET", "/api/patches", nil, nil)
	if !strings.Contains(string(body), `"state":"not-checked"`) || !strings.Contains(string(body), "job is running") {
		t.Errorf("during a job: %s", body)
	}
	if _, err := os.Stat(logFile); err == nil {
		t.Error("the device must not be asked while a job runs")
	}
}

func TestPatchesEndpointNeverRunsATamperedScript(t *testing.T) {
	h := newHarness(t)
	logFile := filepath.Join(h.fd.dir, "patch.log")
	murl, _ := servePatches(t, fakePatchScript(logFile), true)
	h.app.patchesURL = murl
	old := http.DefaultTransport
	http.DefaultTransport = patchClient.Transport
	t.Cleanup(func() { http.DefaultTransport = old })
	if code, _ := h.post("/api/connect", map[string]string{"host": "127.0.0.1", "password": "secret"}); code != 200 {
		t.Fatal("connect")
	}
	_, body := h.do("GET", "/api/patches", nil, nil)
	if !strings.Contains(string(body), `"state":"error"`) || !strings.Contains(string(body), "checksum") {
		t.Errorf("a script that does not match its hash is an error row: %s", body)
	}
	if _, err := os.Stat(logFile); err == nil {
		t.Error("a script that fails its checksum must never reach the device")
	}
}

// The manifest's "backup" is a folder; the device state used to share that JSON key and turned it into true on the page.
func TestRowJSONKeepsTheManifestBackupFolderAndTheDeviceFlagApart(t *testing.T) {
	var p Patch
	p.ID, p.Backup = "x", "/sdcard/MPC-backup"
	b, err := json.Marshal(PatchRow{Patch: p, State: "stock", HasBackup: true})
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	json.Unmarshal(b, &m)
	if m["backup"] != "/sdcard/MPC-backup" || m["hasBackup"] != true {
		t.Errorf(`"backup" must stay the folder and "hasBackup" the flag: %s`, b)
	}
}

func TestPartialStateAndReasonTokens(t *testing.T) {
	st, ok := parseStateLine([]string{"STATE state=partial supported=1 backup=1"})
	if !ok || st.State != "partial" || !st.Supported {
		t.Errorf("partial: %v %+v", ok, st)
	}
	st, ok = parseStateLine([]string{"STATE state=unsupported supported=0 backup=0 reason=no-noexec-drive"})
	if !ok || st.Reason != "no-noexec-drive" {
		t.Errorf("reason: %v %+v", ok, st)
	}
	for _, bad := range []string{"reason=Bad Token", "reason=a;b", "reason=" + strings.Repeat("a", 60), "reason=-x"} {
		if st, ok := parseStateLine([]string{"STATE state=unsupported supported=0 backup=0 " + bad}); !ok || st.Reason != "" {
			t.Errorf("%q must be dropped: %v %+v", bad, ok, st)
		}
	}
}

func TestRowsExplainReasonsAndPartialInstalls(t *testing.T) {
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	var p Patch
	p.ID, p.Supports.Arch, p.Supports.OS = "drive-exec", "armv7l", "Force Gen1, MPC OS 3.9.1"
	row := func(line string) PatchRow {
		return PatchRows(d, []Patch{p}, func(Patch) ([]byte, error) { return []byte("#!/bin/sh\necho '" + line + "'\n"), nil })[0]
	}
	if r := row("STATE state=unsupported supported=0 backup=0 reason=no-noexec-drive"); r.State != "unsupported" || !strings.Contains(r.Detail, "No drive is mounted") || strings.Contains(r.Detail, "checksum") {
		t.Errorf("a reason gets its own sentence, not the MPC-checksum one: %+v", r)
	}
	if r := row("STATE state=unsupported supported=0 backup=0 reason=other-install"); !strings.Contains(r.Detail, "original ForceHD VST Exec") {
		t.Errorf("the original install gets its own sentence: %+v", r)
	}
	if r := row("STATE state=unsupported supported=0 backup=0 reason=something-new"); !strings.Contains(r.Detail, "does not recognise this device") {
		t.Errorf("an unknown reason falls back: %+v", r)
	}
	if r := row("STATE state=partial supported=1 backup=1"); r.State != "partial" || !strings.Contains(r.Detail, "not active") || !r.Supported {
		t.Errorf("partial: %+v", r)
	}
	if r := row("STATE state=partial supported=1 backup=0 reason=not-loaded"); !strings.Contains(r.Detail, "has not loaded") || strings.Contains(r.Detail, "drive") {
		t.Errorf("a partial reason gets its own sentence: %+v", r)
	}
	if r := row("STATE state=patched supported=1 backup=1"); r.State != "patched" || r.Detail != "" {
		t.Errorf("patched has no detail: %+v", r)
	}
}

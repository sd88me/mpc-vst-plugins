package main

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// A stand-in patch script with a state of its own (a file): `install --confirmed` makes it patched, `uninstall --confirmed` stock.
// `mode` changes how it misbehaves: "" works, "lie" exits 0 without changing anything, "fail" exits 1.
func statefulPatchScript(dir, mode string) string {
	st, log := shQuote(filepath.Join(dir, "state")), shQuote(filepath.Join(dir, "patch.log"))
	return `#!/bin/sh
echo "$*" >> ` + log + `
S=$(cat ` + st + ` 2>/dev/null || echo stock)
case "$1" in
  status) echo "human text"; echo "STATE state=$S supported=1 backup=0" ;;
  install|uninstall)
    [ "$2" = --confirmed ] || { echo "ERROR: would ask on a terminal"; exit 4; }
    case "` + mode + `" in
      fail) echo "ERROR: boom"; exit 1 ;;
      lie) echo "did nothing"; exit 0 ;;
    esac
    if [ "$1" = install ]; then echo patched > ` + st + `; else echo stock > ` + st + `; fi
    echo "done $1" ;;
  *) echo "ERROR: unexpected $1"; exit 2 ;;
esac
`
}

func readLog(t *testing.T, dir string) []string {
	b, _ := os.ReadFile(filepath.Join(dir, "patch.log"))
	var out []string
	for _, l := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		if l != "" {
			out = append(out, l)
		}
	}
	return out
}

func runPatchJob(t *testing.T, mode, action, startState string) (*Job, error, []string, string) {
	t.Helper()
	fd := newFakeDevice(t)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if startState != "" {
		os.WriteFile(filepath.Join(fd.dir, "state"), []byte(startState+"\n"), 0o644)
	}
	var p Patch
	p.ID, p.Title, p.RestartsMPC = "x", "Test patch", true
	j := &Job{ID: "j", State: "running"}
	err = RunPatch(d, p, []byte(statefulPatchScript(fd.dir, mode)), action, j, nil)
	if left, _ := filepath.Glob(filepath.Join(fd.dir, "tmp", "mpc-patch-*")); len(left) != 0 {
		t.Errorf("the copy on the device must be removed: %v", left)
	}
	_, lines, _, _ := j.snapshot(0)
	return j, err, readLog(t, fd.dir), strings.Join(lines, "\n")
}

func TestRunPatchAppliesThenUndoes(t *testing.T) {
	j, err, log, lines := runPatchJob(t, "", "install", "")
	if err != nil {
		t.Fatal(err)
	}
	if st, _, _, res := j.snapshot(0); st != "done" {
		t.Errorf("job: %s %s", st, res)
	}
	if got := strings.Join(log, "|"); got != "status|install --confirmed|status" {
		t.Errorf("calls (the state check, the install with --confirmed, the state check to verify): %s", got)
	}
	if !strings.Contains(lines, "done install") || !strings.Contains(lines, "now reports: patched") {
		t.Errorf("log: %s", lines)
	}
	_, err, log, _ = runPatchJob(t, "", "uninstall", "patched")
	if err != nil || strings.Join(log, "|") != "status|uninstall --confirmed|status" {
		t.Errorf("undo: %v %v", err, log)
	}
}

func TestRunPatchRefusesWhatTheStateSaysCannotWork(t *testing.T) {
	_, err, log, _ := runPatchJob(t, "", "install", "patched")
	if err == nil || !strings.Contains(err.Error(), "cannot be applied") {
		t.Errorf("apply on an applied patch: %v", err)
	}
	_, err, _, _ = runPatchJob(t, "", "uninstall", "stock")
	if err == nil || !strings.Contains(err.Error(), "nothing to undo") {
		t.Errorf("undo of a stock device: %v", err)
	}
	for _, l := range log {
		if strings.HasPrefix(l, "install") {
			t.Errorf("install must not run: %v", log)
		}
	}
	_, err, _, _ = runPatchJob(t, "", "format", "")
	if err == nil {
		t.Error("an unknown action must be refused")
	}
}

func TestRunPatchDoesNotTrustAnExitStatusAlone(t *testing.T) {
	j, err, _, _ := runPatchJob(t, "lie", "install", "")
	if err == nil || !strings.Contains(err.Error(), `reports "stock", not "patched"`) {
		t.Errorf("a script that exits 0 without changing the device: %v", err)
	}
	if st, _, _, _ := j.snapshot(0); st != "failed" {
		t.Errorf("job state %s", st)
	}
	_, err, _, lines := runPatchJob(t, "fail", "install", "")
	if err == nil || !strings.Contains(err.Error(), "status 1") || !strings.Contains(lines, "boom") {
		t.Errorf("a failing script: %v / %s", err, lines)
	}
}

func waitJob(t *testing.T, h *harness) (string, string) {
	t.Helper()
	for i := 0; i < 100; i++ {
		h.app.mu.Lock()
		j := h.app.job
		h.app.mu.Unlock()
		if j != nil {
			if st, _, _, res := j.snapshot(0); st != "running" {
				return st, res
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("job did not finish")
	return "", ""
}

func TestPatchRunEndpointNeedsTheTypedWordAndAKnownPatch(t *testing.T) {
	h := newHarness(t)
	murl, _ := servePatches(t, statefulPatchScript(h.fd.dir, ""), false)
	h.app.patchesURL = murl
	old := http.DefaultTransport
	http.DefaultTransport = patchClient.Transport
	t.Cleanup(func() { http.DefaultTransport = old })

	body := map[string]string{"id": "drum-pad-layout", "action": "install", "confirm": "APPLY"}
	if code, _ := h.post("/api/patch/run", body); code != 400 {
		t.Errorf("not connected: %d", code)
	}
	if code, _ := h.post("/api/connect", map[string]string{"host": "127.0.0.1", "password": "secret"}); code != 200 {
		t.Fatal("connect")
	}
	if code, _ := h.post("/api/patch/run", body); code != 404 {
		t.Errorf("before the list was read: %d", code)
	}
	h.do("GET", "/api/patches", nil, nil)
	for _, bad := range []map[string]string{
		{"id": "drum-pad-layout", "action": "install", "confirm": ""},
		{"id": "drum-pad-layout", "action": "install", "confirm": "apply"},
		{"id": "drum-pad-layout", "action": "install", "confirm": "UNDO"},
		{"id": "drum-pad-layout", "action": "uninstall", "confirm": "APPLY"},
		{"id": "drum-pad-layout", "action": "rm -rf", "confirm": "APPLY"},
	} {
		if code, _ := h.post("/api/patch/run", bad); code != 400 {
			t.Errorf("%v: %d", bad, code)
		}
	}
	if code, _ := h.post("/api/patch/run", map[string]string{"id": "nope", "action": "install", "confirm": "APPLY"}); code != 404 {
		t.Errorf("unknown id: %d", code)
	}
	if l := readLog(t, h.fd.dir); len(l) != 1 || l[0] != "status" {
		t.Errorf("nothing but the status check may have run so far: %v", l)
	}

	code, out := h.post("/api/patch/run", body)
	if code != 200 || out["job"] == nil {
		t.Fatalf("apply: %d %v", code, out)
	}
	if st, res := waitJob(t, h); st != "done" {
		t.Fatalf("job %s %s", st, res)
	}
	_, rows := h.do("GET", "/api/patches", nil, nil)
	if !strings.Contains(string(rows), `"state":"patched"`) {
		t.Errorf("the row after applying: %s", rows)
	}
	if code, _ := h.post("/api/patch/run", map[string]string{"id": "drum-pad-layout", "action": "uninstall", "confirm": "UNDO"}); code != 200 {
		t.Fatalf("undo: %d", code)
	}
	if st, res := waitJob(t, h); st != "done" {
		t.Fatalf("undo job %s %s", st, res)
	}
	// one job at a time
	h.app.job = &Job{ID: "busy", State: "running"}
	if code, _ := h.post("/api/patch/run", body); code != 409 {
		t.Errorf("while a job runs: %d", code)
	}
}

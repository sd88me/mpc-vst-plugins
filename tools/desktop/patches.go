package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Device patches (docs/PATCHES.md): scripts from this project that change the device itself, not a plugin. This file only reads: it
// fetches the manifest, checks each script against its sha256 and asks the device what state a patch is in (the script's `status`
// command, which changes nothing), and, only when the user has typed the confirmation word, runs the script's `install --confirmed`
// or `uninstall --confirmed` (RunPatch) and checks the state afterwards.

const maxPatchScript = 1 << 20

// patchClient fetches the manifest and the scripts (small files, unlike plugin zips).
var patchClient = &http.Client{Timeout: time.Minute}

var sha256Re = regexp.MustCompile(`^[0-9a-f]{64}$`)
var md5Re = regexp.MustCompile(`^[0-9a-f]{32}$`)
var reasonRe = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)

// Patch is one entry of patches.json, published next to catalog.json.
type Patch struct {
	ID      string `json:"id"`
	Title   string `json:"title"`
	Summary string `json:"summary"`
	Author  string `json:"author"`
	License string `json:"license"`
	Docs    string `json:"docs"`
	Script  struct {
		URL    string `json:"url"`
		SHA256 string `json:"sha256"`
	} `json:"script"`
	Supports struct {
		OS     string   `json:"os"`
		Arch   string   `json:"arch"`
		MPCMD5 []string `json:"mpc_md5"`
	} `json:"supports"`
	Modifies    []string `json:"modifies"`
	Backup      string   `json:"backup"`
	RestartsMPC bool     `json:"restarts_mpc"`
	Reversible  bool     `json:"reversible"`
}

// patchesURLFor: patches.json sits next to the catalog it is used with.
func patchesURLFor(catalogURL string) string {
	u, err := url.Parse(catalogURL)
	if err != nil || u.Host == "" {
		return ""
	}
	u.Path = path.Join(path.Dir(u.Path), "patches.json")
	u.RawQuery, u.Fragment = "", ""
	return u.String()
}

// parsePatches keeps the entries the app can handle safely: https script, 64-hex hash, a way back, absolute device paths. Others are dropped.
func parsePatches(data []byte) ([]Patch, error) {
	var doc struct {
		Schema  int     `json:"schema"`
		Patches []Patch `json:"patches"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil, err
	}
	if doc.Schema != 1 {
		return nil, fmt.Errorf("patches schema %d is not supported by this app", doc.Schema)
	}
	out := []Patch{}
	seen := map[string]bool{}
	for _, p := range doc.Patches {
		ok := idRe.MatchString(p.ID) && !seen[p.ID] && p.Title != "" && isHTTPS(p.Script.URL) && sha256Re.MatchString(p.Script.SHA256) &&
			p.Reversible && len(p.Modifies) > 0 && p.Supports.Arch != ""
		for _, m := range p.Modifies {
			ok = ok && strings.HasPrefix(m, "/")
		}
		if !ok {
			continue
		}
		seen[p.ID] = true
		out = append(out, p)
	}
	return out, nil
}

var errNoPatches = errors.New("no patches are published yet")

func FetchPatches(u string) ([]Patch, error) {
	if u == "" {
		return nil, errNoPatches
	}
	resp, err := patchClient.Get(u)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, errNoPatches
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("patches: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	return parsePatches(data)
}

// FetchPatchScript downloads a patch's script over https and refuses it unless it is small and matches the manifest's sha256.
func FetchPatchScript(p Patch) ([]byte, error) {
	if !isHTTPS(p.Script.URL) {
		return nil, errors.New("the patch script link is not https")
	}
	resp, err := patchClient.Get(p.Script.URL)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("patch script: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxPatchScript+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxPatchScript {
		return nil, errors.New("the patch script is larger than the app accepts")
	}
	sum := sha256.Sum256(data)
	if hex.EncodeToString(sum[:]) != p.Script.SHA256 {
		return nil, errors.New("the patch script does not match the checksum in the manifest; refusing it")
	}
	return data, nil
}

// PatchState is what a patch script's `status` says about the device.
type PatchState struct {
	State     string `json:"state"` // stock | patched | old-patch | partial | unsupported
	Supported bool   `json:"supported"`
	Backup    bool   `json:"backup"`
	Checksum  string `json:"checksum,omitempty"` // md5 of the device's MPC program, when the script says (the drum-pad patch, v5 and later)
	Reason    string `json:"reason,omitempty"`   // a short token saying why a patch cannot apply (see reasonText)
}

// parseStateLine reads the last "STATE state=.. supported=0|1 backup=0|1 [checksum=<md5>] [reason=<token>]" line of a script's output.
func parseStateLine(lines []string) (PatchState, bool) {
	for i := len(lines) - 1; i >= 0; i-- {
		l := strings.TrimSpace(lines[i])
		if !strings.HasPrefix(l, "STATE ") {
			continue
		}
		kv := map[string]string{}
		for _, f := range strings.Fields(l[6:]) {
			if k, v, ok := strings.Cut(f, "="); ok {
				kv[k] = v
			}
		}
		switch kv["state"] {
		case "stock", "patched", "old-patch", "partial", "unsupported":
		default:
			return PatchState{}, false
		}
		st := PatchState{State: kv["state"], Supported: kv["supported"] == "1", Backup: kv["backup"] == "1"}
		if md5Re.MatchString(kv["checksum"]) {
			st.Checksum = kv["checksum"]
		}
		if len(kv["reason"]) <= 40 && reasonRe.MatchString(kv["reason"]) {
			st.Reason = kv["reason"]
		}
		return st, true
	}
	return PatchState{}, false
}

// PatchStatus copies the (already verified) script to a private folder on the device, runs `status` and removes the copy.
func (d *Device) PatchStatus(script []byte) (PatchState, error) {
	tmp := d.cfg.RemoteTmp + "/mpc-patch-" + randHex(4)
	defer d.Run("rm -rf "+shQuote(tmp), nil, nil)
	if code, err := d.Run("mkdir -p "+shQuote(tmp)+" && cat > "+shQuote(tmp+"/patch.sh"), bytes.NewReader(script), nil); err != nil || code != 0 {
		return PatchState{}, fmt.Errorf("cannot prepare the device (status %d): %v", code, err)
	}
	var lines []string
	var mu sync.Mutex
	code, err := d.Run("sh "+shQuote(tmp+"/patch.sh")+" status </dev/null", nil, func(l string) { mu.Lock(); lines = append(lines, l); mu.Unlock() })
	mu.Lock()
	defer mu.Unlock()
	if st, ok := parseStateLine(lines); ok && err == nil && code == 0 {
		return st, nil
	}
	msg := ""
	for _, l := range lines {
		if strings.HasPrefix(l, "ERROR") {
			msg = ": " + l
		}
	}
	return PatchState{}, fmt.Errorf("the patch script's status did not answer (status %d)%s", code, msg)
}

// PatchRow is one patch as the page shows it.
type PatchRow struct {
	Patch
	State     string `json:"state"` // "not-checked" until the device is connected, then the script's state, "unsupported" or "error"
	Supported bool   `json:"supported"`
	HasBackup bool   `json:"hasBackup"` // a saved copy of the stock program is on the device (not Patch.Backup, the manifest's backup folder: same key would hide it)
	Detail    string `json:"detail,omitempty"`
}

// PatchRows reads the state of every patch from the device. Read only. A patch built for another architecture is not asked.
func PatchRows(dev *Device, patches []Patch, fetch func(Patch) ([]byte, error)) []PatchRow {
	rows := []PatchRow{}
	for _, p := range patches {
		r := PatchRow{Patch: p, State: "not-checked"}
		switch {
		case dev == nil:
		case dev.Info.Arch != "" && p.Supports.Arch != dev.Info.Arch:
			r.State, r.Detail = "unsupported", "built for "+p.Supports.Arch+"; this device is "+dev.Info.Arch
		default:
			script, err := fetch(p)
			if err == nil {
				var st PatchState
				if st, err = dev.PatchStatus(script); err == nil {
					r.State, r.Supported, r.HasBackup = st.State, st.Supported, st.Backup
					switch st.State {
					case "unsupported":
						r.Detail = unsupportedDetail(p, st)
					case "partial":
						if t, ok := reasonText[st.Reason]; ok {
							r.Detail = t
						} else {
							r.Detail = "Installed, but not active right now: the drive may not be mounted, or its mount was removed. Check the patch's guide."
						}
					}
				}
			}
			if err != nil {
				r.State, r.Detail = "error", err.Error()
			}
		}
		rows = append(rows, r)
	}
	return rows
}

// reasonText: what a patch script's reason= token means on the page. An unknown token falls back to the general sentence.
var reasonText = map[string]string{
	"not-root":        "The script must run as root on the device.",
	"arch":            "This patch is for another kind of device.",
	"tools":           "A tool the patch needs is missing on this device.",
	"other-version":   "Another version of this patch is already installed: remove it with its own uninstaller first.",
	"other-install":   "The original ForceHD VST Exec is installed: remove it with its own uninstaller first.",
	"bad-drive":       "The drive path is not one the patch can use.",
	"no-drive":        "That drive is not mounted.",
	"not-needed":      "That drive already allows running programs, so the patch is not needed.",
	"no-noexec-drive": "No drive is mounted that blocks running programs (is the drive plugged in, and does it already work?).",
	"unknown-layout":  "This device has neither the Hakai launcher nor an acvs or inmusic-mpc service this patch can hook.",
	"hand-install":    "A copy of this remap is already installed by hand. Remove it first; the patch's guide says how.",
	"not-loaded":      "Installed, but the running MPC has not loaded it. Restart MPC.",
	"not-running":     "Installed. MPC is not running, so it is not in effect until MPC starts.",
	"incomplete":      "Installed, but a file is missing. The patch's guide says how to remove it and install it again.",
}

// unsupportedDetail says why the script would not touch the device, so a bare "not supported" is never all the page shows.
func unsupportedDetail(p Patch, st PatchState) string {
	var b strings.Builder
	if t, ok := reasonText[st.Reason]; ok {
		return t
	}
	if st.Checksum != "" {
		b.WriteString("This device's MPC program has the checksum " + st.Checksum + ", which is not a build this patch knows")
	} else {
		b.WriteString("The patch script does not recognise this device")
	}
	if p.Supports.OS != "" {
		b.WriteString(" (it supports " + p.Supports.OS)
		if len(p.Supports.MPCMD5) > 0 {
			b.WriteString(", checksum " + strings.Join(p.Supports.MPCMD5, " or "))
		}
		b.WriteString(")")
	}
	b.WriteString(".")
	if st.Backup && st.Checksum != "" {
		b.WriteString(" A backup from an earlier install is on the device: its guide explains how to restore the stock program from it with the script's uninstall.")
	}
	return b.String()
}

// Words the user must type before a patch is applied or undone (the page asks; the server checks again).
const (
	ConfirmApply = "APPLY"
	ConfirmUndo  = "UNDO"
)

// patchAction checks that `action` makes sense for the state the device reported. The script has its own gates; this keeps the app
// from even starting something the row already says cannot work.
func patchAction(action string, st PatchState) error {
	switch action {
	case "install":
		if !st.Supported || (st.State != "stock" && st.State != "old-patch") {
			return fmt.Errorf("this patch cannot be applied here (state: %s)", st.State)
		}
	case "uninstall":
		switch {
		case st.State == "patched" || st.State == "old-patch" || st.State == "partial":
		case st.State == "unsupported" && st.Backup: // the script restores the stock program from its own verified backup, or refuses
		default:
			return fmt.Errorf("there is nothing to undo (state: %s)", st.State)
		}
	default:
		return errors.New("unknown action")
	}
	return nil
}

// RunPatch copies the (already verified) script to a private folder on the device, runs `<action> --confirmed` with its output in the
// job's log, then asks `status` again and only reports success when the device is in the state that was asked for.
func RunPatch(dev *Device, p Patch, script []byte, action string, j *Job, refresh func()) (err error) {
	defer func() {
		if refresh != nil {
			refresh()
		}
		j.finish(err)
	}()
	tmp := dev.cfg.RemoteTmp + "/mpc-patch-" + randHex(4)
	defer dev.Run("rm -rf "+shQuote(tmp), nil, nil)
	if code, rerr := dev.Run("mkdir -p "+shQuote(tmp)+" && cat > "+shQuote(tmp+"/patch.sh"), bytes.NewReader(script), nil); rerr != nil || code != 0 {
		return fmt.Errorf("cannot prepare the device (status %d): %v", code, rerr)
	}
	status := func() (PatchState, error) {
		var lines []string
		var mu sync.Mutex
		code, rerr := dev.Run("sh "+shQuote(tmp+"/patch.sh")+" status </dev/null", nil, func(l string) { mu.Lock(); lines = append(lines, l); mu.Unlock() })
		mu.Lock()
		defer mu.Unlock()
		if st, ok := parseStateLine(lines); ok && rerr == nil && code == 0 {
			return st, nil
		}
		return PatchState{}, fmt.Errorf("the patch script's status did not answer (status %d) %v", code, rerr)
	}
	before, err := status()
	if err != nil {
		return err
	}
	if err = patchAction(action, before); err != nil {
		return err
	}
	verb, want := "Applying", "patched"
	if action == "uninstall" {
		verb, want = "Undoing", "stock"
	}
	j.log("%s: %s", verb, p.Title)
	if p.RestartsMPC {
		j.log("The script stops and starts MPC itself if it has to.")
	}
	code, rerr := dev.Run("sh "+shQuote(tmp+"/patch.sh")+" "+action+" --confirmed </dev/null 2>&1", nil, func(l string) { j.log("  %s", l) })
	if rerr != nil {
		return rerr
	}
	if code != 0 {
		return fmt.Errorf("the patch script stopped with status %d (see the log). Check the row: the script restores the original when it fails", code)
	}
	after, err := status()
	if err != nil {
		return fmt.Errorf("the script finished but the device would not report its state: %v", err)
	}
	if after.State != want {
		return fmt.Errorf("the script finished but the device reports %q, not %q: check the patch's guide", after.State, want)
	}
	j.log("The device now reports: %s.", after.State)
	return nil
}

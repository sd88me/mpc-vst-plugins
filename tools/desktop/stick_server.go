package main

// HTTP handlers for the USB-stick builder (stick.go): a separate top-level mode from the SSH-based steps, for a
// device the user cannot reach yet. Independent job slot (stickJob) so it never blocks, or is blocked by, an
// install running against a connected device.

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"

	"golang.org/x/crypto/ssh"
)

// stickScan is one salt-scan result, kept server-side (never sent to the page) so the salt itself never has to
// round-trip through the browser or get logged.
type stickScan struct {
	Firmware string
	Salt     []byte
	Hits     int
}

func (a *App) stickScanStart(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct{ Firmware string }
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<12)).Decode(&in); err != nil || in.Firmware == "" {
		fail(w, 400, "bad request")
		return
	}
	if st, err := os.Stat(in.Firmware); err != nil || st.IsDir() {
		fail(w, 400, "that doesn't look like a file: "+in.Firmware)
		return
	}
	a.mu.Lock()
	if a.stickJob != nil {
		if st, _, _, _ := a.stickJob.snapshot(0); st == "running" {
			a.mu.Unlock()
			fail(w, 409, "a scan or build is already running")
			return
		}
	}
	j := &Job{ID: randHex(4), State: "running"}
	a.stickJob = j
	a.mu.Unlock()
	go func() {
		j.log("Scanning %s for the autorun salt (this reads the whole file; a Gen2 image can take a few minutes)", in.Firmware)
		salt, hits, err := findSalt(in.Firmware, func(label string, done, total int64) {
			pct := 0
			if total > 0 {
				pct = int(done * 100 / total)
			}
			j.log("%s: %d / %d MB (%d%%)", label, done>>20, total>>20, pct)
		})
		if err != nil {
			j.finish(fmt.Errorf("%w (is this a stock Akai update image, or the MPC executable from one?)", err))
			return
		}
		a.mu.Lock()
		handle := randHex(6)
		a.stickScan[handle] = &stickScan{Firmware: in.Firmware, Salt: salt, Hits: hits}
		a.mu.Unlock()
		j.log("Found it (%d match%s). The salt itself is never shown or stored anywhere but this run.", hits, plural(hits))
		j.finishWithResult(handle) // the page's only handle on the result; never the salt bytes
	}()
	writeJSON(w, 200, map[string]string{"job": j.ID})
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "es"
}

func (a *App) stickJobStatus(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	j := a.stickJob
	a.mu.Unlock()
	if j == nil {
		fail(w, 404, "no scan or build has been started")
		return
	}
	since := 0
	fmt.Sscanf(r.URL.Query().Get("since"), "%d", &since)
	st, lines, next, result := j.snapshot(since)
	writeJSON(w, 200, map[string]any{"id": j.ID, "state": st, "lines": lines, "next": next, "result": result})
}

// stickKeygen makes a fresh ed25519 keypair for a user with no key of their own: the public half goes on the stick,
// the private half is handed back once, in the response, and never kept by the app (docs/USB_STICK.md).
func (a *App) stickKeygen(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	sshPub, err := ssh.NewPublicKey(pub)
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	pubLine := string(ssh.MarshalAuthorizedKey(sshPub))
	pemBlock, err := ssh.MarshalPrivateKey(priv, "mpc-installer")
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"public": pubLine, "private": string(pem.EncodeToMemory(pemBlock))})
}

func (a *App) stickBuild(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct {
		ScanHandle  string
		Out         string
		Install     []string
		SSHPubKey   string // pasted or generated; empty = no SSH
		SSHPassword string // advanced, less secure alternative; empty = no password login. At most one of these two.
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	a.mu.Lock()
	scan, ok := a.stickScan[in.ScanHandle]
	a.mu.Unlock()
	if !ok {
		fail(w, 400, "scan the firmware again: that result is no longer available")
		return
	}
	if in.Out == "" {
		fail(w, 400, "choose a folder to write the stick to")
		return
	}
	out := filepath.Clean(in.Out)
	var pub []byte
	if in.SSHPubKey != "" {
		pub = []byte(in.SSHPubKey)
	}
	if err := BuildStick(out, scan.Salt, in.Install, pub, in.SSHPassword); err != nil {
		fail(w, 400, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"out": out, "firmware": scan.Firmware, "hits": scan.Hits})
}

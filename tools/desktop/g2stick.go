package main

// The "Level 1" USB stick (beta): a prebuilt stick that carries our own autorun script and the OpenMPC Plugin Manager VST
// packages, built by tools/usb_g2/build_stick.py. Confirm the stock prompt on MPC OS 3.9.1 or earlier and it installs G2
// and restarts MPC. Like the easy stick it is written as-is: the installer reads no firmware, and nothing derived from
// one but autorun.check is on the stick. This file checks a bundle before writing it, then unpacks it.
//
// Until a release is published, g2stick-pin.json has an empty url and the bundle is chosen from a local file.

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const g2StickMaxSize = 128 << 20 // two packages of ~20 MB each

// g2PinURL is a var so tests can point it at a local server; empty means "no published stick".
var g2PinURL = "https://raw.githubusercontent.com/sd88me/mpc-vst-plugins/main/tools/desktop/g2stick-pin.json"

// g2ReleasePrefix is the only place a pin file may send the download.
const g2ReleasePrefix = "https://github.com/sd88me/mpc-vst-plugins/releases/download/"

var g2StickNeed = []string{"autorun/autorun.json", "autorun/autorun.check", "autorun/open.sh",
	"autorun/runtime/run.sh", "autorun/runtime/payload.sha256", ".mpc-g2-stick"}

var g2PackageName = regexp.MustCompile(`^g2/Plugin-Manager-G2-[0-9][0-9A-Za-z.]*-mpc-(armv7|aarch64)\.zip$`)

// currentG2Pin returns the pinned Level 1 stick, or an error when none is published yet.
func currentG2Pin() (easyPin, error) {
	if g2PinURL == "" {
		return easyPin{}, errNoG2Stick
	}
	c := &http.Client{Timeout: 5 * time.Second}
	resp, err := c.Get(g2PinURL)
	if err != nil {
		return easyPin{}, errNoG2Stick
	}
	defer resp.Body.Close()
	var p easyPin
	if resp.StatusCode != 200 || json.NewDecoder(io.LimitReader(resp.Body, 8<<10)).Decode(&p) != nil ||
		p.Version == "" || !strings.HasPrefix(p.URL, g2ReleasePrefix) || strings.ContainsAny(p.URL, " \t\r\n") || !hex64.MatchString(p.SHA256) {
		return easyPin{}, errNoG2Stick
	}
	return p, nil
}

var errNoG2Stick = errors.New("no Level 1 stick is published yet; choose a bundle file from your computer")

func fetchG2Stick(pin easyPin) ([]byte, error) {
	c := &http.Client{Timeout: 5 * time.Minute}
	resp, err := c.Get(pin.URL)
	if err != nil {
		return nil, fmt.Errorf("couldn't download the Level 1 stick: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("couldn't download the Level 1 stick: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, g2StickMaxSize+1))
	if err != nil {
		return nil, err
	}
	if len(data) > g2StickMaxSize {
		return nil, errors.New("the Level 1 stick download is larger than expected; refusing it")
	}
	if sum := sha256.Sum256(data); hex.EncodeToString(sum[:]) != pin.SHA256 {
		return nil, errors.New("the Level 1 stick download doesn't match the checksum this installer expects; refusing it")
	}
	return data, nil
}

// checkG2Bundle verifies, without writing anything, that the zip is a Level 1 stick whose packages are exactly the ones
// payload.sha256 (covered by the stock boot check) lists: one per CPU, each matching its checksum.
func checkG2Bundle(data []byte) error {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return errors.New("that file is not a zip")
	}
	files := map[string]*zip.File{}
	for _, f := range zr.File {
		files[path.Clean(f.Name)] = f
	}
	for _, n := range g2StickNeed {
		if files[n] == nil {
			return fmt.Errorf("this is not a Level 1 stick bundle: %s is missing", n)
		}
	}
	rc, err := files["autorun/runtime/payload.sha256"].Open()
	if err != nil {
		return err
	}
	list, err := io.ReadAll(io.LimitReader(rc, 8<<10))
	rc.Close()
	if err != nil {
		return err
	}
	listed := map[string]string{}
	arches := map[string]bool{}
	for _, line := range strings.Split(strings.TrimSpace(string(list)), "\n") {
		f := strings.Fields(line)
		if len(f) != 2 || !hex64.MatchString(f[0]) || !g2PackageName.MatchString(f[1]) {
			return fmt.Errorf("payload.sha256 has a line this installer doesn't accept: %q", line)
		}
		listed[f[1]] = f[0]
		arches[g2PackageName.FindStringSubmatch(f[1])[1]] = true
	}
	if len(listed) != 2 || !arches["armv7"] || !arches["aarch64"] {
		return errors.New("payload.sha256 must list one armv7 and one aarch64 package")
	}
	for name, want := range listed {
		f := files[name]
		if f == nil {
			return fmt.Errorf("the bundle lacks %s, which payload.sha256 lists", name)
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		h := sha256.New()
		_, err = io.Copy(h, rc)
		rc.Close()
		if err != nil {
			return err
		}
		if hex.EncodeToString(h.Sum(nil)) != want {
			return fmt.Errorf("%s doesn't match its checksum in payload.sha256; refusing it", name)
		}
	}
	for n, f := range files {
		if _, ok := listed[n]; strings.HasPrefix(n, "g2/") && !ok && !f.FileInfo().IsDir() {
			return fmt.Errorf("the bundle carries %s, which payload.sha256 doesn't list", n)
		}
	}
	return nil
}

// WriteG2Stick checks the bundle, then unpacks it onto out (missing or empty, as for every stick).
func WriteG2Stick(out string, data []byte) error {
	if err := checkG2Bundle(data); err != nil {
		return err
	}
	return writeStickZip(out, data, "Level 1 stick", g2StickNeed)
}

// loadG2Bundle reads a bundle the user chose: the downloaded .zip, or the folder a browser or archive tool unpacked it into
// (Safari unzips downloads by default). A path pasted from "Copy as path" has quotes round it, and a Mac path may start with ~.
func loadG2Bundle(p string) ([]byte, error) {
	p = strings.TrimSpace(p)
	if len(p) >= 2 && (p[0] == '"' && p[len(p)-1] == '"' || p[0] == '\'' && p[len(p)-1] == '\'') {
		p = strings.TrimSpace(p[1 : len(p)-1])
	}
	if p == "~" || strings.HasPrefix(p, "~/") || strings.HasPrefix(p, `~\`) {
		if h, err := os.UserHomeDir(); err == nil {
			p = filepath.Join(h, p[1:])
		}
	}
	st, err := os.Stat(p)
	if err != nil {
		return nil, fmt.Errorf("can't find that bundle: %s (pick the downloaded .zip with Browse)", p)
	}
	if st.IsDir() {
		if _, err := os.Stat(filepath.Join(p, ".mpc-g2-stick")); err != nil {
			return nil, fmt.Errorf("%s is a folder, not the bundle: pick the downloaded .zip file (or the folder it was unpacked into, which has an autorun folder in it)", p)
		}
		return zipFolder(p)
	}
	if st.Size() > g2StickMaxSize {
		return nil, errors.New("that file is much larger than a bundle (about 40 MB); is it the right file?")
	}
	return os.ReadFile(p)
}

// zipFolder packs an unpacked bundle back into a zip in memory, so one check covers both; links and anything outside the folder are skipped.
func zipFolder(root string) ([]byte, error) {
	var b bytes.Buffer
	zw := zip.NewWriter(&b)
	total := int64(0)
	err := filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil || p == root || d.Type()&os.ModeSymlink != 0 {
			return err
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		name := filepath.ToSlash(rel)
		if d.IsDir() {
			_, err = zw.Create(name + "/")
			return err
		}
		if d.Name() != ".mpc-g2-stick" && isHousekeeping(d.Name()) { // .DS_Store, ._ files, Thumbs.db: not part of the bundle
			return nil
		}
		if !d.Type().IsRegular() {
			return nil
		}
		w, err := zw.Create(name)
		if err != nil {
			return err
		}
		f, err := os.Open(p)
		if err != nil {
			return err
		}
		defer f.Close()
		n, err := io.Copy(w, io.LimitReader(f, g2StickMaxSize+1))
		if total += n; total > g2StickMaxSize {
			return errors.New("that folder is much larger than a bundle (about 40 MB)")
		}
		return err
	})
	if err != nil {
		return nil, err
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

// stickG2 writes the Level 1 stick from a local bundle file (the beta path) or the pinned release.
func (a *App) stickG2(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct{ Out, Bundle string }
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<12)).Decode(&in); err != nil || in.Out == "" {
		fail(w, 400, "choose a folder or drive to write the stick to")
		return
	}
	out := filepath.Clean(in.Out)
	var data []byte
	version := "local file"
	if in.Bundle != "" {
		var err error
		if data, err = loadG2Bundle(in.Bundle); err != nil {
			fail(w, 400, err.Error())
			return
		}
	} else {
		pin, err := currentG2Pin()
		if err != nil {
			fail(w, 404, err.Error())
			return
		}
		if data, err = fetchG2Stick(pin); err != nil {
			fail(w, 502, err.Error())
			return
		}
		version = pin.Version
	}
	if err := WriteG2Stick(out, data); err != nil {
		fail(w, 400, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"out": out, "version": version})
}

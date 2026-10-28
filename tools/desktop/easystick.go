package main

// The "easy" USB stick: instead of building a stick from the user's own firmware (stick.go), download the
// community plugin manager's prebuilt universal stick (Eurikon/plugin-manager-usb-for-open-mpc, MIT) and unpack it
// onto the chosen drive. One bundle carries the MPC OS 3.9.1 autorun route and the OS 3.10 controller helper, and
// picks the Gen1 or Gen2 runtime by `uname -m` on the device, so the installer needs to know neither the OS version
// nor the generation. No firmware is read here.
//
// The stick runs as root on the device, so the release is pinned by SHA-256 and never "latest". To move to a new
// release, read its changelog, test it on a device, then update tools/desktop/easystick-pin.json (picked up by
// installers already out) and, at the next installer release, the compiled-in fallback below.

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

const (
	easyStickVersion = "v1.2.2" // sd88me fork build of upstream v1.2.1 (display rotation override, helper failure log, updates from the fork); device test notes in docs/NOTES.md (2026-10-28)
	easyStickMaxSize = 16 << 20 // the zip is ~1.8 MB; refuse anything wildly larger
)

// easyStickSHA256 is a var, like the URL, so tests can pin a fixture instead.
var easyStickSHA256 = "321d553a45ddec6567536d0c84509fb2f857beec78118223cc7a161d072c2b9b"

// easyStickURL is a var so tests can point it at a local server.
var easyStickURL = "https://github.com/sd88me/plugin-manager-usb-for-open-mpc/releases/download/" +
	easyStickVersion + "/plugin-manager-usb-" + easyStickVersion + ".zip"

// easyPin is one reviewed release of the community manager. The compiled-in one is the fallback; the installer
// prefers easystick-pin.json from this repo's main branch, so a newly tested release can be adopted with a one-file PR
// instead of a new installer release. Either way the zip is checked against its SHA-256 before anything is written.
type easyPin struct {
	Version string `json:"version"`
	URL     string `json:"url"`
	SHA256  string `json:"sha256"`
}

// easyPinURL is a var so tests can point it at a local server; empty means "use the compiled-in pin only".
var easyPinURL = "https://raw.githubusercontent.com/sd88me/mpc-vst-plugins/main/tools/desktop/easystick-pin.json"

// easyReleasePrefixes are the only places a pin file may send the download (the upstream project's releases and this
// project's fork of it), so a changed pin file can't point the installer at an arbitrary host.
var easyReleasePrefixes = []string{
	"https://github.com/Eurikon/plugin-manager-usb-for-open-mpc/releases/download/",
	"https://github.com/sd88me/plugin-manager-usb-for-open-mpc/releases/download/",
}

// easyReleasePrefix is the fork's, which is what the compiled-in pin uses.
const easyReleasePrefix = "https://github.com/sd88me/plugin-manager-usb-for-open-mpc/releases/download/"

func allowedEasyURL(url string) bool {
	for _, prefix := range easyReleasePrefixes {
		if strings.HasPrefix(url, prefix) {
			return true
		}
	}
	return false
}

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (p easyPin) valid() bool {
	return p.Version != "" && allowedEasyURL(p.URL) && !strings.ContainsAny(p.URL, " \t\r\n") && hex64.MatchString(p.SHA256)
}

func builtinEasyPin() easyPin {
	return easyPin{Version: easyStickVersion, URL: easyStickURL, SHA256: easyStickSHA256}
}

// currentEasyPin returns the pin file's release when it can be fetched and is well-formed, else the compiled-in one.
func currentEasyPin() easyPin {
	if easyPinURL == "" {
		return builtinEasyPin()
	}
	c := &http.Client{Timeout: 5 * time.Second}
	resp, err := c.Get(easyPinURL)
	if err != nil {
		return builtinEasyPin()
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return builtinEasyPin()
	}
	var p easyPin
	if err := json.NewDecoder(io.LimitReader(resp.Body, 8<<10)).Decode(&p); err != nil || !p.valid() {
		return builtinEasyPin()
	}
	return p
}

// fetchEasyStick downloads the pinned zip and checks its hash before returning it.
func fetchEasyStick() ([]byte, error) {
	return fetchEasyStickPin(currentEasyPin())
}

func fetchEasyStickPin(pin easyPin) ([]byte, error) {
	c := &http.Client{Timeout: 2 * time.Minute}
	resp, err := c.Get(pin.URL)
	if err != nil {
		return nil, fmt.Errorf("couldn't download the plugin manager stick: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("couldn't download the plugin manager stick: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, easyStickMaxSize+1))
	if err != nil {
		return nil, err
	}
	if len(data) > easyStickMaxSize {
		return nil, errors.New("the plugin manager download is larger than expected; refusing it")
	}
	if sum := sha256.Sum256(data); hex.EncodeToString(sum[:]) != pin.SHA256 {
		return nil, errors.New("the plugin manager download doesn't match the checksum this installer expects; refusing it")
	}
	return data, nil
}

// WriteEasyStick unpacks the zip onto out, which must be missing or empty (a drive's own housekeeping aside), the
// same rule as BuildStick. Entries that would land outside out are refused.
func WriteEasyStick(out string, data []byte) error {
	if st, err := os.Stat(out); err == nil {
		if !st.IsDir() {
			return fmt.Errorf("%s already exists and is not a folder", out)
		}
		des, err := os.ReadDir(out)
		if err != nil {
			return err
		}
		for _, d := range des {
			if !isHousekeeping(d.Name()) {
				return fmt.Errorf("%s is not empty; pick an empty folder (or an empty, freshly formatted USB stick)", out)
			}
		}
	}
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return err
	}
	// Validate every name before writing anything, so a bad zip leaves the drive untouched.
	for _, f := range zr.File {
		name := path.Clean(f.Name)
		if name == "." || strings.HasPrefix(name, "/") || name == ".." || strings.HasPrefix(name, "../") ||
			strings.Contains(name, `\`) || strings.Contains(name, ":") {
			return fmt.Errorf("unsafe path in the plugin manager zip: %q", f.Name)
		}
	}
	if err := os.MkdirAll(out, 0755); err != nil {
		return err
	}
	for _, f := range zr.File {
		dst := filepath.Join(out, filepath.FromSlash(path.Clean(f.Name)))
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(dst, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
			return err
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		w, err := os.Create(dst)
		if err == nil {
			_, err = io.Copy(w, rc)
			if cerr := w.Close(); err == nil {
				err = cerr
			}
		}
		rc.Close()
		if err != nil {
			return err
		}
	}
	for _, need := range []string{"autorun/autorun.json", "autorun/autorun.check", "autorun/open.sh", ".mpc-manager-id"} {
		if _, err := os.Stat(filepath.Join(out, filepath.FromSlash(need))); err != nil {
			return fmt.Errorf("the plugin manager zip is missing %s", need)
		}
	}
	return nil
}

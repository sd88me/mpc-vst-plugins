package main

// The no-SSH-yet USB-stick installer (docs/USB_STICK.md): a Go port of tools/usb_stick/{saltscan,make_stick}.py, so the
// desktop app can build a stick without the user needing Python. Same algorithm, same output layout, same rule: the salt is
// read from the user's own firmware at generation time and is never stored, logged, or put in a release.
//
// autorun/autorun.check = sha256(autorun.json + open.sh + the listed files + salt), checked by the stock MPC OS "USB script"
// reader (Gen1, Force and Gen2 on MPC OS up to 3.9.1; removed in 3.10.0, docs/GEN2.md). The salt is 37 bytes kept
// XOR-obfuscated in the MPC executable, found by scanning rather than a fixed offset, so it works on any firmware build that
// keeps the same scheme. This is the advanced stick: it turns on SSH (a public key, or a password) and puts installed addins back,
// then opens the community plugin manager (easystick.go) when the user wants it too. Plugins are installed from that manager;
// this stick no longer installs a preset list itself (tools/usb_stick/*.py still does, for a CLI user).

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/ulikunitz/xz"
)

//go:embed stick_adv_open.sh
var stickAdvOpenSH []byte

//go:embed stick_extras.sh
var stickExtrasSH []byte

//go:embed stick_enable_ssh.sh
var stickEnableSSHSH []byte

var saltKey = [8]byte{0x87, 0x3b, 0x91, 0xf9, 0x45, 0x1b, 0x77, 0xc9} // 0xc9771b45f9913b87, little-endian; from the firmware's scheme, not a secret

const (
	saltWidth  = 37 // bytes reserved for the salt, padded with zeros
	saltMinLen = 16
	saltChunk  = 8 << 20
)

var printableRun = regexp.MustCompile(`[\x20-\x7e]{16,}`)

// saltHit is one place the salt (or a coincidental look-alike) was found.
type saltHit struct {
	where string // "file" or "xz@<offset>"
	at    int64
	salt  []byte
}

// xorDecode XORs block (whose first byte is at stream offset `start`) against the repeating key, with `align` picking which
// of the 8 possible phases of the key lines up with the stream: decoded[i] = block[i] ^ key[(start+i-align) mod 8].
func xorDecode(block []byte, start int64, align int) []byte {
	out := make([]byte, len(block))
	for i, b := range block {
		k := ((start+int64(i)-int64(align))%8 + 8) % 8
		out[i] = b ^ saltKey[k]
	}
	return out
}

// scanSalt streams r, yielding every salt candidate (offset, bytes) it finds under any of the key's 8 phases.
func scanSalt(r io.Reader, yield func(at int64, salt []byte)) error {
	var base int64
	var tail []byte
	buf := make([]byte, saltChunk)
	for {
		n, rerr := io.ReadFull(r, buf)
		if rerr != nil && rerr != io.ErrUnexpectedEOF && rerr != io.EOF {
			return rerr
		}
		data := buf[:n]
		if n == 0 && len(tail) == 0 {
			return nil
		}
		block := append(append([]byte(nil), tail...), data...)
		start := base - int64(len(tail))
		final := n == 0
		for align := 0; align < 8; align++ {
			dec := xorDecode(block, start, align)
			for _, m := range printableRun.FindAllIndex(dec, -1) {
				rs, e := m[0], m[1]
				lo := e - saltWidth
				if rs > lo {
					lo = rs
				}
				s0 := lo + int((((int64(align)-(start+int64(lo)))%8)+8)%8)
				if e-s0 < saltMinLen {
					continue
				}
				if s0+saltWidth > len(block) && !final {
					continue // the window continues in the next chunk
				}
				hi := s0 + saltWidth
				if hi > len(block) {
					hi = len(block)
				}
				if bytesAnyNonZero(dec[e:hi]) {
					continue
				}
				if start+int64(s0)+saltWidth <= base {
					continue // lay wholly in the previous chunk: already reported
				}
				yield(start+int64(s0), dec[s0:e])
			}
		}
		base += int64(n)
		if n > 0 {
			keep := saltWidth + 8
			if len(block) > keep {
				tail = append([]byte(nil), block[len(block)-keep:]...)
			} else {
				tail = append([]byte(nil), block...)
			}
		} else {
			tail = nil
		}
		if final {
			return nil
		}
	}
}

func bytesAnyNonZero(b []byte) bool {
	for _, c := range b {
		if c != 0 {
			return true
		}
	}
	return false
}

var xzMagic = []byte{0xfd, '7', 'z', 'X', 'Z', 0x00}

// xzOffsets finds every xz stream start in path (an update image's root filesystems are xz-compressed).
func xzOffsets(path string) ([]int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var found []int64
	var pos int64
	var carry []byte
	buf := make([]byte, 1<<24)
	for {
		n, rerr := f.Read(buf)
		if n > 0 {
			blk := append(carry, buf[:n]...)
			for i := 0; ; {
				j := bytes.Index(blk[i:], xzMagic)
				if j < 0 {
					break
				}
				found = append(found, pos-int64(len(carry))+int64(i+j))
				i += j + 1
			}
			if len(blk) >= 5 {
				carry = append([]byte(nil), blk[len(blk)-5:]...)
			} else {
				carry = append([]byte(nil), blk...)
			}
			pos += int64(n)
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return nil, rerr
		}
	}
	return found, nil
}

// countingReader counts bytes read through it, for progress reporting.
type countingReader struct {
	r io.Reader
	n int64
}

func (c *countingReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n += int64(n)
	return n, err
}

// progressReader wraps whatever scanSalt actually reads (src) and periodically reports how far "progress" has
// gotten against total, where progress is measured by a separate counter: for the raw-file scan that is src's own
// byte count; for an xz stream it is the compressed bytes consumed from the underlying file, which scanSalt never
// sees directly (it reads the decompressed stream).
type progressReader struct {
	src      io.Reader
	progress func() int64
	total    int64
	label    string
	cb       func(label string, done, total int64)
	last     int64
}

func (p *progressReader) Read(b []byte) (int, error) {
	n, err := p.src.Read(b)
	if p.cb != nil {
		d := p.progress()
		if d-p.last >= 16<<20 || err != nil {
			p.cb(p.label, d, p.total)
			p.last = d
		}
	}
	return n, err
}

// FindSalt is the salt in a firmware file: a raw MPC executable, or an update image whose root filesystems are xz streams.
// Returns an error when there is no candidate or the candidates disagree (the scheme changed, or the file is not stock
// firmware): it never guesses.
func FindSalt(path string) (salt []byte, hits int, err error) {
	return findSalt(path, nil)
}

// findSalt is FindSalt with an optional progress callback (label, bytes done, bytes total), called periodically
// during a scan that can take minutes on a large Gen2 image -- so a caller like the installer app's job log can
// show that it is still working, not stuck.
func findSalt(path string, progress func(label string, done, total int64)) (salt []byte, hits int, err error) {
	var all []saltHit
	f, err := os.Open(path)
	if err != nil {
		return nil, 0, err
	}
	fi, serr := f.Stat()
	if serr != nil {
		f.Close()
		return nil, 0, serr
	}
	total := fi.Size()
	cr := &countingReader{r: f}
	pr := &progressReader{src: cr, progress: func() int64 { return cr.n }, total: total, label: "scanning the file", cb: progress}
	serr = scanSalt(pr, func(at int64, s []byte) { all = append(all, saltHit{"file", at, append([]byte(nil), s...)}) })
	f.Close()
	if serr != nil {
		return nil, 0, serr
	}
	if len(all) == 0 {
		offs, oerr := xzOffsets(path)
		if oerr != nil {
			return nil, 0, oerr
		}
		for i, off := range offs {
			f, err := os.Open(path)
			if err != nil {
				return nil, 0, err
			}
			if _, err := f.Seek(off, io.SeekStart); err != nil {
				f.Close()
				continue
			}
			cr := &countingReader{r: f}
			zr, zerr := xz.NewReader(cr)
			if zerr != nil {
				f.Close()
				continue
			}
			where := fmt.Sprintf("xz@%d", off)
			label := fmt.Sprintf("decompressing stream %d/%d", i+1, len(offs))
			pr := &progressReader{src: zr, progress: func() int64 { return cr.n }, total: total - off, label: label, cb: progress}
			_ = scanSalt(pr, func(at int64, s []byte) { all = append(all, saltHit{where, at, append([]byte(nil), s...)}) })
			f.Close()
		}
	}
	if len(all) == 0 {
		return nil, 0, errors.New("no salt found: not stock MPC firmware, or the scheme changed")
	}
	byValue := map[string][]byte{}
	for _, h := range all {
		byValue[string(h.salt)] = h.salt
	}
	if len(byValue) > 1 {
		// A genuine candidate is shorter than saltWidth (zero-padded). Coincidental printable runs instead fill
		// the whole reserved field and have length == saltWidth; drop them if a padded candidate also exists.
		padded := map[string][]byte{}
		for k, v := range byValue {
			if len(v) < saltWidth {
				padded[k] = v
			}
		}
		if len(padded) > 0 {
			byValue = padded
		}
	}
	if len(byValue) != 1 {
		return nil, 0, fmt.Errorf("%d different salt candidates; refusing to guess", len(byValue))
	}
	var only []byte
	for _, v := range byValue {
		only = v
	}
	n := 0
	for _, h := range all {
		if string(h.salt) == string(only) {
			n++
		}
	}
	return only, n, nil
}

// --- Building the stick ---

const stickPromptManager = "MPC PLUGIN INSTALLER\n\nThis turns on SSH and puts your addins back, then opens the plugin manager.\n\nHave you saved your project?"
const stickPromptSSH = "MPC SSH ACCESS\n\nThis turns on SSH and puts your addins back. MPC may restart once.\n\nHave you saved your project?"

type autorunScript struct {
	Path          string `json:"path"`
	AskQuestion   bool   `json:"askQuestion"`
	Message       string `json:"message"`
	YesButtonText string `json:"yesButtonText"`
	NoButtonText  string `json:"noButtonText"`
}
type autorunManifest struct {
	Value0 struct {
		Files   []string        `json:"files"`
		Scripts []autorunScript `json:"scripts"`
	} `json:"value0"`
}

// autorunCheck is what the stock reader recomputes: sha256 of autorun.json, open.sh, then each listed file in order, then
// the salt, as lowercase hex text.
func autorunCheck(autorunDir string, files []string, salt []byte) ([]byte, error) {
	h := sha256.New()
	for _, name := range append([]string{"autorun.json", "open.sh"}, files...) {
		b, err := os.ReadFile(filepath.Join(autorunDir, name))
		if err != nil {
			return nil, err
		}
		h.Write(b)
	}
	h.Write(salt)
	sum := h.Sum(nil)
	out := make([]byte, hex.EncodedLen(len(sum)))
	hex.Encode(out, sum)
	return out, nil
}

// housekeeping names an OS or file manager creates on its own, on a drive nobody has put anything on yet: not
// something a user put there, so they don't make a folder count as "not empty" (a freshly formatted Windows drive
// always has System Volume Information; macOS Finder adds its own after browsing a drive).
var housekeepingNames = map[string]bool{
	"system volume information": true,
	"$recycle.bin":              true,
	".trashes":                  true,
	".spotlight-v100":           true,
	".fseventsd":                true,
	".ds_store":                 true,
	"thumbs.db":                 true,
}

func isHousekeeping(name string) bool {
	if strings.HasPrefix(name, ".") {
		return true
	}
	return housekeepingNames[strings.ToLower(name)]
}

// BuildSSHStick writes the advanced stick into out: SSH access (a public key, or a password), addins put back, and, when manager
// is non-nil (the community plugin manager's release zip, easystick.go), that manager too. The manager's files go in untouched; its
// open.sh is kept as autorun/manager-open.sh and a wrapper open.sh runs ours first, then it. The salt-based autorun.check is made
// over the combined set of files (this is why it needs the user's firmware), and USB-SHA256.json is rewritten to match.
// out may be missing or an empty folder (a mounted drive's own root counts, ignoring its housekeeping files); anything else is
// refused, so it never merges into what is there. sshPubKey must be one line starting "ssh-" (never a private key); sshPassword is the
// less secure alternative; exactly one of the two is required, because SSH is the point of this stick.
func BuildSSHStick(out string, salt []byte, manager []byte, sshPubKey []byte, sshPassword string) error {
	if len(sshPubKey) > 0 && sshPassword != "" {
		return errors.New("use an SSH key or a password, not both")
	}
	if len(sshPubKey) == 0 && sshPassword == "" {
		return errors.New("choose how to log in over SSH: a public key, or a password")
	}
	if len(sshPubKey) > 0 && !bytes.HasPrefix(bytes.TrimSpace(sshPubKey), []byte("ssh-")) {
		return errors.New("that doesn't look like an SSH public key (it should start with ssh-)")
	}
	if manager != nil {
		if err := WriteEasyStick(out, manager); err != nil { // checks that out is missing or empty
			return err
		}
	} else if st, err := os.Stat(out); err == nil {
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
	autorunDir := filepath.Join(out, "autorun")
	runtime := filepath.Join(autorunDir, "runtime")
	if err := os.MkdirAll(runtime, 0755); err != nil {
		return err
	}
	if manager != nil { // the manager's own open.sh moves aside, unchanged, for ours to call
		own, err := os.ReadFile(filepath.Join(autorunDir, "open.sh"))
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(autorunDir, "manager-open.sh"), own, 0644); err != nil {
			return err
		}
	}
	write := func(path string, data []byte) error { return os.WriteFile(path, data, 0644) }
	if err := write(filepath.Join(autorunDir, "open.sh"), stickAdvOpenSH); err != nil {
		return err
	}
	if err := write(filepath.Join(runtime, "mpc-extras.sh"), stickExtrasSH); err != nil {
		return err
	}
	if err := write(filepath.Join(runtime, "enable_ssh.sh"), stickEnableSSHSH); err != nil {
		return err
	}
	if len(sshPubKey) > 0 {
		if err := write(filepath.Join(runtime, "authorized_key.pub"), append(bytes.TrimSpace(sshPubKey), '\n')); err != nil {
			return err
		}
	} else if err := write(filepath.Join(runtime, "ssh_password.txt"), []byte(sshPassword+"\n")); err != nil {
		return err
	}
	var files []string
	err := filepath.WalkDir(autorunDir, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, err := filepath.Rel(autorunDir, p)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		if rel != "autorun.json" && rel != "autorun.check" && rel != "open.sh" {
			files = append(files, rel)
		}
		return nil
	})
	if err != nil {
		return err
	}
	sort.Strings(files)
	prompt := stickPromptSSH
	if manager != nil {
		prompt = stickPromptManager
	}
	var m autorunManifest
	m.Value0.Files = files
	m.Value0.Scripts = []autorunScript{{Path: "open.sh", AskQuestion: true, Message: prompt, YesButtonText: "Open", NoButtonText: "Cancel"}}
	mj, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	if err := write(filepath.Join(autorunDir, "autorun.json"), append(mj, '\n')); err != nil {
		return err
	}
	check, err := autorunCheck(autorunDir, files, salt)
	if err != nil {
		return err
	}
	if err := write(filepath.Join(autorunDir, "autorun.check"), check); err != nil {
		return err
	}
	if manager != nil {
		if err := rewriteInventory(out); err != nil {
			return err
		}
	}
	readme := "Copy everything in this folder (hidden files too) to the root of a USB stick, insert it into the MPC/Force (MPC OS up to 3.9.1),\n" +
		"and confirm the prompt. It turns on SSH (a key you gave, or a password) and puts any already-installed addins back;\n" +
		"what it did is written to mpc-extras-result.txt on the stick. Save your project first: MPC may restart once.\n"
	if manager != nil {
		readme += "It then opens the plugin manager (Eurikon's Plugin Manager USB for OPEN MPC, MIT); see the README of that project.\n"
	}
	return write(filepath.Join(out, "README-USB.txt"), []byte(readme))
}

// rewriteInventory regenerates the plugin manager bundle's own USB-SHA256.json (path -> sha256 for every file on the stick except
// itself and our README) after the wrapper, the extras and the new autorun files changed what is there.
func rewriteInventory(out string) error {
	inv := map[string]string{}
	err := filepath.WalkDir(out, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, err := filepath.Rel(out, p)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		if rel == "USB-SHA256.json" || rel == "README-USB.txt" || isHousekeeping(strings.Split(rel, "/")[0]) && rel != ".mpc-manager-id" {
			return nil
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(b)
		inv[rel] = hex.EncodeToString(sum[:])
		return nil
	})
	if err != nil {
		return err
	}
	j, err := json.MarshalIndent(inv, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(out, "USB-SHA256.json"), append(j, '\n'), 0644)
}

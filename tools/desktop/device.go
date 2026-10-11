package main

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

// Config holds the few things that differ on a real device and in tests.
type Config struct {
	Port         string // ssh port, "22"
	User         string // "root"
	RemoteTmp    string // where packages are unpacked on the device, "/tmp"
	SynthsDir    string // "/sdcard/Synths": the internal drive, the default place to install
	RootGlobs    string // where to look for plugin locations, shell words (globs allowed): "/sdcard/Synths /media/*/Synths"
	SettingsGlob string // where MPC.settings is
	MountsFile   string // the list of mounts, "/proc/mounts"
	AddinsDir    string // where addins live, one folder each: "/data/mpc-addins"
	LibcPaths    string // where to look for the device's libc, shell words (globs allowed), to read its glibc version
}

func defaultConfig() Config {
	return Config{Port: "22", User: "root", RemoteTmp: "/tmp", SynthsDir: "/sdcard/Synths", RootGlobs: "/sdcard/Synths /media/*/Synths", MountsFile: "/proc/mounts", SettingsGlob: "/media/az01-internal/Settings/*/MPC.settings /data/Settings/*/MPC.settings", AddinsDir: "/data/mpc-addins",
		LibcPaths: "/lib/libc.so.6 /lib/arm-linux-gnueabihf/libc.so.6 /usr/lib/libc.so.6 /lib/libc-*.so /usr/lib/libc-*.so"}
}

type DeviceInfo struct {
	Host        string                       `json:"host"`
	Arch        string                       `json:"arch"`
	UID         string                       `json:"uid"`
	Fingerprint string                       `json:"fingerprint"`
	Synths      string                       `json:"synths"`
	Settings    string                       `json:"settings"`
	TmpFreeKB   int64                        `json:"tmpFreeKB"`
	Tar         bool                         `json:"tar"`
	Systemctl   bool                         `json:"systemctl"`
	Libc        string                       `json:"libc"`      // the device's glibc ("2.33"), empty when it cannot be told: MPC OS 2.x has about 2.32, 3.x and the Force 2.39
	Roots       []Root                       `json:"roots"`     // the places plugins can live: the internal drive first, then cards and drives
	Installed   []string                     `json:"installed"` // names of the plugin folders found in any of them
	Store       map[string]string            `json:"store"`     // plugin id -> version recorded by this app or mpc-store.sh, in the internal drive
	Plugins     []DevPlugin                  `json:"-"`
	Addins      []DevAddin                   `json:"-"`
	Stores      map[string]map[string]string `json:"-"` // root path -> plugin id -> recorded version
}

// Root is a Synths folder MPC can load plugins from. Only writable ones are listed; the same storage reached by two paths
// (/sdcard and /media/az01-internal-sd on a Force) is listed once.
type Root struct {
	Path       string `json:"path"`
	Label      string `json:"label"`
	FS         string `json:"fs"`
	FreeKB     int64  `json:"freeKB"`
	Primary    bool   `json:"primary"`
	InContent  bool   `json:"inContent"`  // MPC lists it as a content location, so a plugin's screen shows
	NoSymlinks bool   `json:"noSymlinks"` // FAT, exFAT and NTFS cannot store symbolic links
	NoExec     bool   `json:"noExec"`     // mounted noexec: MPC cannot load a plugin from it
	ID         string `json:"-"`
}

func noSymlinkFS(fs string) bool {
	switch strings.ToLower(fs) {
	case "vfat", "exfat", "msdos", "ntfs", "ntfs3", "ntfs-3g", "fuseblk":
		return true
	}
	return false
}

// rootLabel names a location for people: the internal drive, or "Drive <name>" after its folder under /media.
func rootLabel(path, primary string) string {
	if path == primary {
		return "Internal drive"
	}
	if parts := strings.Split(strings.Trim(path, "/"), "/"); len(parts) >= 2 {
		return "Drive " + parts[len(parts)-2]
	}
	return path
}

func (i DeviceInfo) root(path string) (Root, bool) {
	for _, r := range i.Roots {
		if r.Path == path {
			return r, true
		}
	}
	return Root{}, false
}

func (i DeviceInfo) primaryRoot() Root {
	for _, r := range i.Roots {
		if r.Primary {
			return r
		}
	}
	return Root{Path: i.Synths, Label: "Internal drive", Primary: true}
}

// DevPlugin is a plugin folder on the device (one with a plugin-meta.xml).
type DevPlugin struct {
	Root   string `json:"root"`
	Folder string `json:"folder"`
	UID    string `json:"uid"`
	Name   string `json:"name"`
}

// DevAddin is an addin folder on the device (one with an addin.manifest). Removable: it carries its own uninstall.sh (every addin
// installed by the addin installer does); Version is "" for an addin installed without a catalog release.
type DevAddin struct {
	ID        string
	Name      string
	Version   string
	Removable bool
}

type Device struct {
	client *ssh.Client
	cfg    Config
	Info   DeviceInfo
}

var hostRe = regexp.MustCompile(`^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$`)

func validHost(h string) bool { return len(h) <= 253 && hostRe.MatchString(h) }

// authMethods: the password when one was given, then the user's default private keys that need no passphrase.
func authMethods(password string) []ssh.AuthMethod {
	var m []ssh.AuthMethod
	if password != "" {
		m = append(m, ssh.Password(password), ssh.KeyboardInteractive(func(_, _ string, qs []string, _ []bool) ([]string, error) {
			a := make([]string, len(qs))
			for i := range a {
				a[i] = password
			}
			return a, nil
		}))
	}
	if home, err := os.UserHomeDir(); err == nil {
		var signers []ssh.Signer
		for _, n := range []string{"id_ed25519", "id_ecdsa", "id_rsa"} {
			b, err := os.ReadFile(filepath.Join(home, ".ssh", n))
			if err != nil {
				continue
			}
			if s, err := ssh.ParsePrivateKey(b); err == nil {
				signers = append(signers, s)
			}
		}
		if len(signers) > 0 {
			m = append(m, ssh.PublicKeys(signers...))
		}
	}
	return m
}

// Dial connects and reads what the app needs to know about the device. The host key is not remembered between runs: the
// fingerprint is shown so it can be compared, and nothing about the device is written to disk.
func Dial(host, password string, cfg Config) (*Device, error) {
	if !validHost(host) {
		return nil, errors.New("use the address as numbers and dots (or a host name)")
	}
	// With no password and no key, auth is empty and the client offers only "none", which a device whose root has no
	// password (some modified firmware) accepts.
	auth := authMethods(password)
	var fp string
	conf := &ssh.ClientConfig{
		User: cfg.User, Auth: auth, Timeout: 10 * time.Second,
		HostKeyCallback: func(_ string, _ net.Addr, key ssh.PublicKey) error { fp = ssh.FingerprintSHA256(key); return nil },
	}
	c, err := ssh.Dial("tcp", net.JoinHostPort(host, cfg.Port), conf)
	if err != nil {
		if len(auth) == 0 && strings.Contains(err.Error(), "unable to authenticate") {
			return nil, errors.New("enter the device's password (no SSH key was found on this computer)")
		}
		return nil, fmt.Errorf("cannot log in to %s: %w", host, err)
	}
	d := &Device{client: c, cfg: cfg}
	if err := d.readInfo(host, fp); err != nil {
		c.Close()
		return nil, err
	}
	return d, nil
}

func (d *Device) Close() {
	if d.client != nil {
		d.client.Close()
	}
}

type lineWriter struct {
	mu   *sync.Mutex
	buf  []byte
	emit func(string)
}

func (w *lineWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.buf = append(w.buf, p...)
	for {
		i := strings.IndexAny(string(w.buf), "\n\r")
		if i < 0 {
			break
		}
		if line := strings.TrimRight(string(w.buf[:i]), "\r"); line != "" && w.emit != nil {
			w.emit(line)
		}
		w.buf = w.buf[i+1:]
	}
	return len(p), nil
}

func (w *lineWriter) flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if len(w.buf) > 0 && w.emit != nil {
		w.emit(strings.TrimRight(string(w.buf), "\r\n"))
	}
	w.buf = nil
}

// Run executes cmd on the device; stdout and stderr lines go to onLine. It returns the exit status.
func (d *Device) Run(cmd string, stdin io.Reader, onLine func(string)) (int, error) {
	s, err := d.client.NewSession()
	if err != nil {
		return -1, err
	}
	defer s.Close()
	var mu sync.Mutex
	lw := &lineWriter{mu: &mu, emit: onLine}
	s.Stdout, s.Stderr = lw, lw
	if stdin != nil {
		s.Stdin = stdin
	}
	err = s.Run(cmd)
	lw.flush()
	var ee *ssh.ExitError
	if errors.As(err, &ee) {
		return ee.ExitStatus(), nil
	}
	if err != nil {
		return -1, err
	}
	return 0, nil
}

func (d *Device) readInfo(host, fp string) error {
	script := fmt.Sprintf(`S=%s
TAB=$(printf '\t')
echo "arch=$(uname -m)"; echo "uid=$(id -u)"; echo "synths=$S"
echo "settings=$(ls %s 2>/dev/null | head -n 1)"
echo "tmpfree=$(df -k %s 2>/dev/null | awk 'NR==2 {print $4}')"
command -v tar >/dev/null 2>&1 && echo tar=1
command -v systemctl >/dev/null 2>&1 && echo systemctl=1
libc=""
for f in %s; do   # glibc 2.34 and later print their version when the library is run; older ones keep it in the file name (libc-2.33.so)
  [ -e "$f" ] || continue
  v=""; if [ -x "$f" ]; then v=$("$f" 2>/dev/null | sed -n 's/.*version \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1); fi
  [ -n "$v" ] || v=$(basename "$f" | sed -n 's/^libc-\([0-9][0-9]*\.[0-9][0-9]*\)\.so$/\1/p')
  if [ -n "$v" ]; then libc=$v; break; fi
done
echo "libc=$libc"
P=${S%%/*}   # the internal drive may have no Synths folder yet (an MPC One whose official plugins went to the card): make it
[ -d "$S" ] || { [ -d "$P" ] && [ -w "$P" ] && mkdir "$S" 2>/dev/null; }
for r in %s; do
  [ -d "$r" ] && [ -w "$r" ] || continue
  rid=$(stat -L -c '%%d:%%i' "$r" 2>/dev/null)
  dfl=$(df -kP "$r" 2>/dev/null | awk 'NR==2 {m = $6; for (i = 7; i <= NF; i++) m = m " " $i; print $4 "\t" m}')   # the mount point may hold spaces ("/media/SSD - Force")
  free=${dfl%%%%$TAB*}; mp=${dfl#*$TAB}; [ -n "$free" ] || free=0; [ -n "$mp" ] || mp=/
  mpe=$(printf %%s "$mp" | sed 's/ /\\040/g')   # /proc/mounts writes a space as \040
  set -- $(MP="$mpe" awk '$2 == ENVIRON["MP"] {t = $3; o = $4} END {print t, o}' %s 2>/dev/null); fs=${1:-}; opts=${2:-}
  case ",$opts," in *,ro,*) continue ;; esac   # a read-only mount (MPC's own content folder) cannot take plugins, even though root may "write" to it
  nx=0; case ",$opts," in *,noexec,*) nx=1 ;; esac   # MPC cannot load a .so from a noexec mount (a Force's SSD): it lists the plugin but shows only "Load Plugin"
  printf 'root=%%s\t%%s\t%%s\t%%s\t%%s\n' "$r" "$rid" "$free" "$fs" "$nx"
  if [ -f "$r/.mpc-store" ]; then sed "s|^|store=$r$TAB|" "$r/.mpc-store"; fi
  for d in "$r"/*/; do
    f="${d}plugin-meta.xml"; [ -f "$f" ] || continue
    u=$(sed -n 's/.* uid="\([^"]*\)".*/\1/p' "$f" | head -n 1); n=$(sed -n 's/.* name="\([^"]*\)".*/\1/p' "$f" | head -n 1)
    printf 'plug=%%s\t%%s\t%%s\t%%s\n' "$r" "$(basename "$d")" "$u" "$n"
  done
done
SET=$(ls %s 2>/dev/null | head -n 1)
if [ -n "$SET" ]; then sed -n 's/.*<Location>\(.*\)<\/Location>.*/loc=\1/p' "$SET"; fi
mval() { sed -n "s/^$1=//p" "$2" | head -n 1 | sed -e 's/^"\([^"]*\)".*/\1/;t' -e "s/^'\\([^']*\\)'.*/\\1/;t" -e 's/[[:space:]]*#.*//'; }
for d in %s/*/; do
  f="${d}addin.manifest"; [ -f "$f" ] || continue
  u=0; [ -f "${d}uninstall.sh" ] && u=1
  printf 'addin=%%s\t%%s\t%%s\t%%s\n' "$(basename "$d")" "$(mval ADDIN_VERSION "$f")" "$u" "$(mval ADDIN_NAME "$f")"
done
true`, shQuote(d.cfg.SynthsDir), d.cfg.SettingsGlob, shQuote(d.cfg.RemoteTmp), d.cfg.LibcPaths, d.cfg.RootGlobs, shQuote(d.cfg.MountsFile), d.cfg.SettingsGlob, shQuote(d.cfg.AddinsDir))
	info := DeviceInfo{Host: host, Fingerprint: fp, Synths: d.cfg.SynthsDir, Installed: []string{}, Store: map[string]string{}, Stores: map[string]map[string]string{}}
	var lines []string
	var mu sync.Mutex
	code, err := d.Run(script, nil, func(l string) { mu.Lock(); lines = append(lines, l); mu.Unlock() })
	if err != nil || code != 0 {
		return fmt.Errorf("the device did not answer a basic command (%v, status %d)", err, code)
	}
	var cands []Root
	var plugs []DevPlugin
	var locs []string
	for _, l := range lines {
		k, v, ok := strings.Cut(l, "=")
		if !ok {
			continue
		}
		f := strings.Split(v, "\t")
		switch k {
		case "arch":
			info.Arch = v
		case "uid":
			info.UID = v
		case "settings":
			info.Settings = v
		case "tmpfree":
			info.TmpFreeKB, _ = strconv.ParseInt(strings.TrimSpace(v), 10, 64)
		case "tar":
			info.Tar = true
		case "systemctl":
			info.Systemctl = true
		case "libc":
			info.Libc = strings.TrimSpace(v)
		case "loc":
			locs = append(locs, strings.TrimRight(v, "/"))
		case "root":
			if len(f) >= 4 {
				free, _ := strconv.ParseInt(strings.TrimSpace(f[2]), 10, 64)
				cands = append(cands, Root{Path: f[0], ID: f[1], FreeKB: free, FS: f[3], NoExec: len(f) >= 5 && f[4] == "1"})
			}
		case "addin":
			if len(f) >= 4 && idRe.MatchString(f[0]) {
				name := strings.TrimSpace(f[3])
				if i := strings.Index(name, "  #"); i >= 0 { // a trailing comment
					name = strings.TrimSpace(name[:i])
				}
				name = strings.Trim(name, `"'`)
				if name == "" {
					name = f[0]
				}
				info.Addins = append(info.Addins, DevAddin{ID: f[0], Name: name, Version: strings.Trim(f[1], `"'`), Removable: f[2] == "1"})
			}
		case "plug":
			if len(f) >= 4 {
				plugs = append(plugs, DevPlugin{Root: f[0], Folder: f[1], UID: f[2], Name: f[3]})
			}
		case "store":
			if len(f) >= 3 && f[1] != "" {
				if info.Stores[f[0]] == nil {
					info.Stores[f[0]] = map[string]string{}
				}
				info.Stores[f[0]][f[1]] = f[2]
			}
		}
	}
	// the same storage through two paths is one location; the first path wins (the internal drive is listed first)
	seen := map[string]bool{}
	keep := map[string]bool{}
	for _, r := range cands {
		if r.ID != "" && seen[r.ID] {
			continue
		}
		seen[r.ID] = true
		r.Primary = r.Path == d.cfg.SynthsDir
		r.Label = rootLabel(r.Path, d.cfg.SynthsDir)
		r.NoSymlinks = noSymlinkFS(r.FS)
		for _, loc := range locs {
			if loc == r.Path {
				r.InContent = true
			}
		}
		info.Roots = append(info.Roots, r)
		keep[r.Path] = true
	}
	if len(info.Roots) > 0 && !info.Roots[0].Primary { // the internal drive first, whatever order the shell listed them in
		for i, r := range info.Roots {
			if r.Primary {
				info.Roots = append([]Root{r}, append(info.Roots[:i:i], info.Roots[i+1:]...)...)
				break
			}
		}
	}
	names := map[string]bool{}
	for _, p := range plugs {
		if keep[p.Root] {
			info.Plugins = append(info.Plugins, p)
			if !names[p.Folder] {
				names[p.Folder] = true
				info.Installed = append(info.Installed, p.Folder)
			}
		}
	}
	for root := range info.Stores {
		if !keep[root] {
			delete(info.Stores, root)
		}
	}
	if st, ok := info.Stores[d.cfg.SynthsDir]; ok {
		info.Store = st
	}
	d.Info = info
	return nil
}

// problems lists why an install must not go ahead on this device (empty when it is fine).
func (i DeviceInfo) problems() []string {
	var p []string
	if i.UID != "0" {
		p = append(p, "you are not logged in as root")
	}
	if !strings.HasPrefix(i.Arch, "armv7") && i.Arch != "aarch64" {
		p = append(p, "this is "+i.Arch+", not a 32-bit ARM (Gen1) or aarch64 (Gen2) MPC OS device")
	}
	if !i.Tar {
		p = append(p, "the device has no tar")
	}
	if !i.Systemctl {
		p = append(p, "the device has no systemctl (is this an MPC OS device?)")
	}
	if i.Settings == "" {
		p = append(p, "MPC.settings was not found")
	}
	return p
}

// shQuote wraps s in single quotes for a POSIX shell.
func shQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }

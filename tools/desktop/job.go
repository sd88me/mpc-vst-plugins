package main

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// Job is one install run; the page polls it for log lines.
type Job struct {
	mu     sync.Mutex
	ID     string
	State  string // running, done, failed
	Lines  []string
	Result string
}

func (j *Job) log(format string, a ...any) {
	j.mu.Lock()
	j.Lines = append(j.Lines, fmt.Sprintf(format, a...))
	j.mu.Unlock()
}

func (j *Job) finish(err error) {
	j.mu.Lock()
	defer j.mu.Unlock()
	if err != nil {
		j.State, j.Result = "failed", err.Error()
	} else {
		j.State, j.Result = "done", "Done."
	}
}

// snapshot returns the state and the lines after `since`.
func (j *Job) snapshot(since int) (state string, lines []string, next int, result string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	if since < 0 || since > len(j.Lines) {
		since = 0
	}
	return j.State, append([]string(nil), j.Lines[since:]...), len(j.Lines), j.Result
}

type Item struct {
	Catalog *CatPlugin // to download first, or nil for a package the user dropped in
	Pkg     *Package   // set for dropped zips; filled in after the download for catalog ones
}

func randHex(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

// RunInstall downloads and checks what has to be downloaded, copies every package to the device, then installs them with MPC
// stopped once and started once (packages whose installer predates -n run first, each with its own restart).
func RunInstall(dev *Device, root Root, items []Item, workDir string, j *Job, refresh func()) (err error) {
	defer func() {
		if err == nil && refresh != nil {
			refresh() // re-read what is on the device before the page is told it is done
		}
		j.finish(err)
	}()
	if p := dev.Info.problems(); len(p) > 0 {
		return errors.New("this device cannot be installed to: " + strings.Join(p, "; "))
	}
	var pkgs []*Package
	for _, it := range items {
		if it.Catalog != nil {
			c := *it.Catalog
			dest := filepath.Join(workDir, c.ID+"-"+c.Version+".zip")
			j.log("Downloading %s %s (%d KB)", c.Name, c.Version, c.Size/1024)
			next := int64(0)
			if err := Download(c, dest, func(done, total int64) {
				if total > 0 && done*4/total >= next && done*4/total > 0 {
					j.log("  %d%%", done*100/total)
					next = done*4/total + 1
				}
			}); err != nil {
				return err
			}
			p, err := OpenPackage(dest, "catalog")
			if err != nil {
				return fmt.Errorf("%s: %w", c.Name, err)
			}
			j.log("%s %s downloaded and checked against the catalog's sha256.", c.Name, c.Version)
			pkgs = append(pkgs, p)
		} else {
			pkgs = append(pkgs, it.Pkg)
		}
	}
	if len(pkgs) == 0 {
		return errors.New("nothing selected")
	}
	var need int64
	for _, p := range pkgs {
		if p.Addin { // goes to the addins folder on /data, not to the chosen plugin location
			continue
		}
		need += p.Unpacked
		if root.NoSymlinks && p.Symlinks > 0 {
			return fmt.Errorf("%s contains %d symbolic links (for example a bundled Python), but %s is formatted %s, which cannot store them: install it on the internal drive instead", p.Title, p.Symlinks, root.Label, strings.ToUpper(root.FS))
		}
	}
	if needKB := (need*11/10 + 1023) / 1024; root.FreeKB > 0 && needKB > root.FreeKB { // with a tenth to spare, rounded up
		return fmt.Errorf("%s has %d MB free, these plugins need about %d MB", root.Label, root.FreeKB/1024, (needKB+1023)/1024)
	}
	plugins := false
	for _, p := range pkgs {
		if p.Addin {
			j.log("%s is an addin: it goes to %s/%s", p.Title, dev.cfg.AddinsDir, p.Plugins[0].ID)
		} else {
			plugins = true
		}
	}
	if plugins {
		j.log("Installing to %s (%s)", root.Label, root.Path)
		if !root.InContent && root.Path != "" {
			j.log("Note: MPC does not list %s as a content location, so a plugin's screen may not show until you add it in MPC's settings", root.Path)
		}
	}
	if dev.Info.TmpFreeKB > 0 && need/1024*13/10 > dev.Info.TmpFreeKB {
		return fmt.Errorf("the device's /tmp has %d MB free, these packages need about %d MB to unpack", dev.Info.TmpFreeKB/1024, need*13/10/(1<<20))
	}
	tmp := dev.cfg.RemoteTmp + "/mpc-installer-" + randHex(4)
	cleanup := func() { dev.Run("rm -rf "+shQuote(tmp), nil, nil) }
	for i, p := range pkgs {
		j.log("Copying %s to the device (%d MB unpacked)", p.Title, p.Unpacked>>20)
		pr, pw := io.Pipe()
		go func(p *Package) { pw.CloseWithError(p.WriteTar(pw)) }(p)
		dir := fmt.Sprintf("%s/p%d", tmp, i+1)
		var out []string
		code, rerr := dev.Run("mkdir -p "+shQuote(dir)+" && tar -xf - -C "+shQuote(dir), pr, func(l string) { out = append(out, l) })
		pr.Close()
		if rerr != nil || code != 0 {
			cleanup()
			return fmt.Errorf("copying %s failed (status %d): %v %s", p.Title, code, rerr, strings.Join(out, " "))
		}
	}
	script := installScript(root.Path, dev.cfg.AddinsDir, tmp, pkgs)
	j.log("Installing (MPC is stopped once and started again at the end)")
	code, rerr := dev.Run(script, nil, func(l string) { j.log("  %s", l) })
	if rerr != nil {
		cleanup()
		return rerr
	}
	if code != 0 {
		return fmt.Errorf("the installer stopped with status %d (see the log). MPC was started again; nothing after the failing plugin was installed", code)
	}
	return nil
}

// installScript is the one shell script that runs on the device. Packages with an old installer go first (each restarts MPC
// itself); the rest run between one stop and one start. MPC is started again even when something fails. An addin installs to
// <addins>/<id> and records its version in its own folder (addin.manifest), not in .mpc-store.
func installScript(synths, addins, tmp string, pkgs []*Package) string {
	var b strings.Builder
	w := func(f string, a ...any) { fmt.Fprintf(&b, f+"\n", a...) }
	w("T=%s; SYN=%s; STATE=\"$SYN/.mpc-store\"; rc=0", shQuote(tmp), shQuote(synths))
	w("SVC=acvs; systemctl cat acvs >/dev/null 2>&1 || ! systemctl cat inmusic-mpc >/dev/null 2>&1 || SVC=inmusic-mpc") // acvs on stock firmware, inmusic-mpc on Hakai
	// A zip built before its installer picked the service itself runs `systemctl stop acvs` and fails where there is no acvs. Put a
	// systemctl in front of it that says the real unit where the installer says acvs (the plain name only, other arguments pass through).
	w(`if [ "$SVC" != acvs ]; then mkdir -p "$T/bin"; REAL=$(command -v systemctl); printf '%%s\n' '#!/bin/sh' 'n=$#; while [ $n -gt 0 ]; do a=$1; shift; [ "$a" = acvs ] && a="'"$SVC"'"; set -- "$@" "$a"; n=$((n-1)); done' 'exec '"$REAL"' "$@"' > "$T/bin/systemctl"; chmod 755 "$T/bin/systemctl"; PATH="$T/bin:$PATH"; export PATH; fi`)
	target := func(p *Package) string { // what install.sh gets as -t
		if p.Addin {
			return shQuote(addins + "/" + p.Plugins[0].ID)
		}
		return `"$SYN"`
	}
	record := func(p *Package) {
		if p.Addin {
			w("  :") // its folder records the version; a then-branch may not be empty
			return
		}
		for _, m := range p.Plugins {
			if m.ID == "" {
				continue
			}
			w(`  mkdir -p "$SYN"; touch "$STATE"; awk -F'\t' -v id=%s '$1 != id' "$STATE" > "$STATE.new"; printf '%%s\t%%s\t%%s\t%%s\n' %s %s %s %s >> "$STATE.new"; mv "$STATE.new" "$STATE"`,
				shQuote(m.ID), shQuote(m.ID), shQuote(m.Version), shQuote(m.Skin), shQuote(strconv.Itoa(m.ParamCompat)))
		}
	}
	for i, p := range pkgs {
		if p.Defer {
			continue
		}
		w("if [ $rc = 0 ]; then")
		w("  printf '%%s\\n' %s", shQuote("Installing "+p.Title+" (its installer restarts MPC by itself)"))
		w(`  if sh "$T/p%d/install.sh" -y -t %s; then`, i+1, target(p))
		record(p)
		w("  else rc=1; fi")
		w("fi")
	}
	anyDefer := false
	for _, p := range pkgs {
		anyDefer = anyDefer || p.Defer
	}
	if anyDefer {
		w("if [ $rc = 0 ]; then")
		w("  systemctl stop $SVC")
		w("  i=0; while pidof MPC >/dev/null && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done")
		w(`  if pidof MPC >/dev/null; then echo "MPC did not stop: nothing was installed"; rc=3; fi`)
		w("fi")
		for i, p := range pkgs {
			if !p.Defer {
				continue
			}
			w("if [ $rc = 0 ]; then")
			w("  printf '%%s\\n' %s", shQuote("Installing "+p.Title))
			w(`  if sh "$T/p%d/install.sh" -y -n -t %s; then`, i+1, target(p))
			record(p)
			w("  else rc=1; fi")
			w("fi")
		}
		w("systemctl start $SVC")
	}
	w(`rm -rf "$T"`)
	w("exit $rc")
	return b.String()
}

// tempWorkDir makes a private folder for downloads and uploaded zips.
func tempWorkDir() (string, error) { return os.MkdirTemp("", "mpc-installer-") }

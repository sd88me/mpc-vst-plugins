package main

import (
	"bytes"
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

// finishWithResult is finish(nil) but with a caller-chosen Result instead of the default "Done." -- for a job whose
// success carries data the page needs (e.g. stickScanStart's scan handle), not just a status line.
func (j *Job) finishWithResult(result string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.State, j.Result = "done", result
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
// InstallOpts are the page's choices beyond what to install and where.
type InstallOpts struct {
	// Register runs the app's own sync.sh after the install, while MPC is stopped for it: every plugin folder in
	// every location gets into MPC's plugin list, nothing on the device needed. Like vstscanner.sh, but it only adds and fixes
	// entries (and backs up MPC.settings) instead of rebuilding the list.
	Register bool
}

func RunInstall(dev *Device, root Root, items []Item, workDir string, j *Job, refresh func(), opts ...InstallOpts) (err error) {
	var o InstallOpts
	if len(opts) > 0 {
		o = opts[0]
	}
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
			c, err := it.Catalog.ForArch(dev.Info.Arch)
			if err != nil {
				return err
			}
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
	for _, p := range pkgs { // a zip dropped in by hand may be for the other generation
		for _, m := range p.Plugins {
			if !archFits(m.Arch, dev.Info.Arch) {
				return fmt.Errorf("%s is built for %s, but this device is %s (%s): get the %s zip", p.Title, m.Arch, dev.Info.Arch, genName(dev.Info.Arch), otherZip(dev.Info.Arch))
			}
		}
	}
	if root.NoExec && dev.WaitExec(root.Path) { // an auto exec patch may just have made it executable
		root, _ = dev.Info.root(root.Path)
	}
	if root.NoExec {
		return fmt.Errorf("%s (%s) is mounted noexec, so MPC cannot load plugins from it: they would be listed but only show \"Load Plugin\". Pick the internal drive under Install to, or keep this drive and apply the auto exec patch (step 7, Advanced) first. If auto exec is already installed, wait five seconds and try again", root.Label, root.Path)
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
			j.log("WARNING: MPC does not list %s as a content location, so the plugin will load with no skin until the folder is added to MPC's content locations (or you install to a listed folder)", root.Path)
		}
	}
	if dev.Info.TmpFreeKB > 0 && need/1024*13/10 > dev.Info.TmpFreeKB {
		return fmt.Errorf("the device's /tmp has %d MB free, these packages need about %d MB to unpack", dev.Info.TmpFreeKB/1024, need*13/10/(1<<20))
	}
	tmp := dev.cfg.RemoteTmp + "/mpc-installer-" + randHex(4)
	cleanup := func() { dev.Run("rm -rf "+shQuote(tmp), nil, nil) }
	for i, p := range pkgs {
		j.log("Copying %s to the device (%d MB unpacked)", p.Title, p.Unpacked>>20)
		dir := fmt.Sprintf("%s/p%d", tmp, i+1)
		var out []string
		copyOnce := func(cmd string) (int, error) { // each attempt streams the package through a pipe of its own
			pr, pw := io.Pipe()
			go func() { pw.CloseWithError(p.WriteTar(pw)) }()
			out = nil
			code, err := dev.Run(cmd, pr, func(l string) { out = append(out, l) })
			pr.Close()
			return code, err
		}
		code, rerr := copyOnce("mkdir -p " + shQuote(dir) + " && tar -xf - -C " + shQuote(dir))
		if connectionLost(rerr) && dev.host != "" { // nothing is installed and MPC is untouched yet, so copying again is safe
			j.log("The connection to the device dropped while copying %s (%v). Reconnecting and copying it again.", p.Title, rerr)
			if cerr := dev.reconnect(); cerr != nil {
				return fmt.Errorf("the connection to the device dropped while copying %s and could not be made again (%v). Nothing was installed and MPC was not stopped. Check the network (and any VPN), then try again", p.Title, cerr)
			}
			code, rerr = copyOnce("rm -rf " + shQuote(dir) + " && mkdir -p " + shQuote(dir) + " && tar -xf - -C " + shQuote(dir))
		}
		if connectionLost(rerr) {
			cleanup()
			return fmt.Errorf("the connection to the device dropped while copying %s (%v). Nothing was installed and MPC was not stopped. Check the network (and any VPN), then try again", p.Title, rerr)
		}
		if rerr != nil || code != 0 {
			cleanup()
			return fmt.Errorf("copying %s failed (status %d): %v %s", p.Title, code, rerr, strings.Join(out, " "))
		}
	}
	syncRoots := ""
	if o.Register {
		for name, data := range map[string][]byte{"sync.sh": syncSH, "plugin_list.awk": pluginListAWK} {
			code, rerr := dev.Run("mkdir -p "+shQuote(tmp+"/sync")+" && cat > "+shQuote(tmp+"/sync/"+name), bytes.NewReader(data), nil)
			if rerr != nil || code != 0 {
				cleanup()
				return fmt.Errorf("cannot copy the plugin-list script to the device (status %d): %v", code, rerr)
			}
		}
		syncRoots = dev.syncRoots()
		j.log("After installing, every plugin folder on the device is registered with MPC (the app's own script; MPC.settings is backed up first)")
	}
	script := installScriptWith(root.Path, dev.cfg.AddinsDir, tmp, pkgs, dev.Info.Settings, syncRoots)
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
	return installScriptWith(synths, addins, tmp, pkgs, "", "")
}

// installScriptWith is installScript plus registering every plugin folder (InstallOpts.Register) once everything is in place,
// while MPC is stopped for the batch, so MPC restarts once.
// syncRoots, when not empty, runs sync.sh from $T/sync with those -t options while MPC is stopped (InstallOpts.Register).
func installScriptWith(synths, addins, tmp string, pkgs []*Package, settings, syncRoots string) string {
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
	register := func() {
		if syncRoots == "" {
			return
		}
		w("if [ $rc = 0 ]; then")
		w("  echo 'Registering every plugin folder with MPC'")
		w(`  (cd "$T/sync" && MPC_SETTINGS=%s sh sync.sh -y -n%s) || { echo 'registering failed (see above): MPC.settings is unchanged unless it said Done'; rc=5; }`, shQuote(settings), syncRoots)
		w("fi")
	}
	if anyDefer || syncRoots != "" { // MPC is stopped once for the batch and for registering
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
		register()
		w("systemctl start $SVC")
	}
	w(`rm -rf "$T"`)
	w("exit $rc")
	return b.String()
}

// tempWorkDir makes a private folder for downloads and uploaded zips.
func tempWorkDir() (string, error) { return os.MkdirTemp("", "mpc-installer-") }

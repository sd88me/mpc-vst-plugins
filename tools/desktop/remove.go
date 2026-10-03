package main

import (
	"bytes"
	_ "embed"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

// pluginListAWK is tools/release/plugin_list.awk (a test keeps the two identical): it edits MPC.settings' plugin list.
//
//go:embed plugin_list.awk
var pluginListAWK []byte

var uidRe = regexp.MustCompile(`^[0-9a-fA-F]{1,16}$`)

// RemovePlan is one plugin to remove. Keep lists the folders inside it that hold the user's own files (ROMs, kits, dumps): they stay.
// An addin (Addin set) is the folder <Root>/<Folder> in the addins folder; the uninstall.sh it carries takes it out of MPC's LD_PRELOAD
// and deletes it, and MPC.settings is not touched for it.
type RemovePlan struct {
	Root   string // the Synths folder the plugin folder is in (the addins folder for an addin)
	Folder string
	UID    string
	ID     string // the catalog id, to forget the version recorded for it ("" when unknown)
	Keep   []string
	Addin  bool
}

var keepRe = regexp.MustCompile(`^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$`) // what release.py allows for --user-data

func safeRel(p string) bool {
	if !keepRe.MatchString(p) {
		return false
	}
	for _, seg := range strings.Split(p, "/") {
		if seg == "" || seg == ".." || seg == "." {
			return false
		}
	}
	return true
}

func (p RemovePlan) check() error {
	if !strings.HasPrefix(p.Root, "/") || strings.ContainsAny(p.Root, "\\\x00\n\r'\"$`") || strings.Contains(p.Root, "..") {
		return fmt.Errorf("unsafe location %q", p.Root)
	}
	if p.Folder == "" || p.Folder == "." || p.Folder == ".." || strings.ContainsAny(p.Folder, "/\\\x00\n") {
		return fmt.Errorf("unsafe folder name %q", p.Folder)
	}
	if p.Addin {
		if !idRe.MatchString(p.Folder) {
			return fmt.Errorf("unsafe addin folder %q", p.Folder)
		}
		return nil
	}
	if !uidRe.MatchString(p.UID) {
		return fmt.Errorf("%s has no usable uid in its plugin-meta.xml", p.Folder)
	}
	for _, k := range p.Keep {
		if !safeRel(k) {
			return fmt.Errorf("unsafe path to keep %q", k)
		}
	}
	return nil
}

// removeScript runs on the device: stop MPC, back up MPC.settings, take every plugin's entry out, check the result, and only then
// delete the folders (your own files inside them are kept); then each addin's own uninstall.sh. MPC is started again whatever happens.
func removeScript(tmp, settings string, all []RemovePlan) string {
	var plans, addins []RemovePlan
	for _, p := range all {
		if p.Addin {
			addins = append(addins, p)
		} else {
			plans = append(plans, p)
		}
	}
	var b strings.Builder
	w := func(f string, a ...any) { fmt.Fprintf(&b, f+"\n", a...) }
	w("T=%s; SET=%s; rc=0", shQuote(tmp), shQuote(settings))
	w("SVC=acvs; systemctl cat acvs >/dev/null 2>&1 || ! systemctl cat inmusic-mpc >/dev/null 2>&1 || SVC=inmusic-mpc") // acvs on stock firmware, inmusic-mpc on Hakai
	w("systemctl stop $SVC")
	w("i=0; while pidof MPC >/dev/null && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done")
	w(`if pidof MPC >/dev/null; then echo "MPC did not stop: nothing was removed"; rc=3; fi`)
	if len(plans) > 0 {
		pluginsPart(w, plans)
	}
	for _, p := range addins {
		d := shQuote(p.Root + "/" + p.Folder)
		w(`if [ $rc = 0 ]; then`)
		w(`  if sh %s -y -n -t %s; then echo %s; else echo %s; rc=10; fi`, shQuote(p.Root+"/"+p.Folder+"/uninstall.sh"), d,
			shQuote("Removed the addin "+p.Folder), shQuote("removing the addin "+p.Folder+" failed"))
		w(`fi`)
	}
	w("systemctl start $SVC")
	w(`rm -rf "$T"`)
	w("exit $rc")
	return b.String()
}

// pluginsPart: back up MPC.settings, take the plugins' entries out, write it once checked, delete their folders.
func pluginsPart(w func(string, ...any), plans []RemovePlan) {
	w(`if [ $rc = 0 ]; then`)
	w(`  BAK="$SET.bak-remove-$(date +%%Y%%m%%d-%%H%%M%%S)"`)
	w(`  if cp "$SET" "$BAK" && cp "$SET" "$T/cur"; then echo "Settings backup: $BAK"; else echo "cannot back up MPC.settings"; rc=4; fi`)
	w(`fi`)
	for _, p := range plans {
		w(`if [ $rc = 0 ]; then`)
		w(`  if awk -v mode=remove -v file=%s -v uid=%s -f "$T/plugin_list.awk" "$T/cur" > "$T/next" && mv "$T/next" "$T/cur"; then :; else echo "cannot edit the plugin list"; rc=5; fi`,
			shQuote(p.Root+"/"+p.Folder+"/.none"), shQuote(p.UID))
		w(`fi`)
	}
	w(`if [ $rc = 0 ]; then`)
	w(`  if grep -q '<PROPERTIES' "$T/cur" && grep -q '</PROPERTIES>' "$T/cur"; then :; else echo "the edited settings lost their root element"; rc=6; fi`)
	w(`fi`)
	w(`if [ $rc = 0 ] && command -v python3 >/dev/null 2>&1; then`)
	w(`  if python3 -c 'import sys, xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$T/cur" 2>/dev/null; then :; else echo "the edited settings are not valid XML"; rc=7; fi`)
	w(`fi`)
	for _, p := range plans {
		w(`if [ $rc = 0 ]; then`)
		w(`  n=$(grep -c " uid=\"%s\"" "$T/cur" || true)`, p.UID)
		w(`  if [ "$n" = 0 ]; then :; else echo %s; rc=8; fi`, shQuote("the plugin entry for "+p.Folder+" is still there"))
		w(`fi`)
	}
	w(`if [ $rc = 0 ]; then`)
	w(`  if cp "$T/cur" "$SET.new" && mv "$SET.new" "$SET"; then sync; else echo "cannot write MPC.settings"; rc=9; fi`)
	w(`fi`)
	for i, p := range plans {
		dir := shQuote(p.Root + "/" + p.Folder)
		w(`if [ $rc = 0 ]; then`)
		w(`  D=%s; K="$T/keep%d"; mkdir -p "$K"`, dir, i)
		for _, k := range p.Keep {
			w(`  if [ -e "$D/%s" ]; then mkdir -p "$K/$(dirname %s)"; mv "$D/%s" "$K/%s"; fi`, k, shQuote(k), k, k)
		}
		w(`  rm -rf "$D"`)
		w(`  if [ -n "$(ls -A "$K" 2>/dev/null)" ]; then mkdir -p "$D"; cp -a "$K/." "$D/"; echo "kept your own files in $D"; fi`)
		w(`  echo %s`, shQuote("Removed "+p.Folder))
		if p.ID != "" {
			w(`  STATE=%s`, shQuote(p.Root+"/.mpc-store"))
			w(`  if [ -f "$STATE" ]; then awk -F'\t' -v id=%s '$1 != id' "$STATE" > "$STATE.new" && mv "$STATE.new" "$STATE"; fi`, shQuote(p.ID))
		}
		w(`fi`)
	}
}

// RunRemove removes the plugins in plans from the device in one MPC stop and start.
func RunRemove(dev *Device, plans []RemovePlan, j *Job, refresh func()) (err error) {
	defer func() {
		if err == nil && refresh != nil {
			refresh()
		}
		j.finish(err)
	}()
	if p := dev.Info.problems(); len(p) > 0 {
		return errors.New("this device cannot be changed: " + strings.Join(p, "; "))
	}
	if len(plans) == 0 {
		return errors.New("nothing selected")
	}
	for _, p := range plans {
		if err := p.check(); err != nil {
			return err
		}
	}
	tmp := dev.cfg.RemoteTmp + "/mpc-installer-" + randHex(4)
	var out []string
	code, rerr := dev.Run("mkdir -p "+shQuote(tmp)+" && cat > "+shQuote(tmp+"/plugin_list.awk"), bytes.NewReader(pluginListAWK), func(l string) { out = append(out, l) })
	if rerr != nil || code != 0 {
		return fmt.Errorf("cannot prepare the device (status %d): %v %s", code, rerr, strings.Join(out, " "))
	}
	j.log("Removing %d item(s) (MPC is stopped once and started again at the end)", len(plans))
	code, rerr = dev.Run(removeScript(tmp, dev.Info.Settings, plans), nil, func(l string) { j.log("  %s", l) })
	if rerr != nil {
		dev.Run("rm -rf "+shQuote(tmp), nil, nil)
		return rerr
	}
	if code != 0 {
		return fmt.Errorf("the removal stopped with status %d (see the log). MPC was started again; MPC.settings was not changed unless the log says Removed", code)
	}
	return nil
}

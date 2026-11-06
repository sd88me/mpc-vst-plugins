package main

import (
	"bytes"
	_ "embed"
	"fmt"
	"strings"
	"sync"
)

// syncSH is tools/release/sync.sh (a test keeps the two identical): it makes MPC's plugin list follow the plugin folders on disk.
//
//go:embed sync.sh
var syncSH []byte

// SyncItem is a plugin folder that is not in MPC's plugin list yet.
type SyncItem struct {
	File   string `json:"file"`
	Root   string `json:"root"`
	Folder string `json:"folder"`
}

// SyncPlan is what registering would do: add the folders MPC does not know, and drop entries whose plugin file is gone.
type SyncPlan struct {
	Add     []SyncItem `json:"add"`
	Remove  []string   `json:"remove"`
	Skipped []string   `json:"skipped"`
}

func (d *Device) syncRoots() string {
	var b strings.Builder
	for _, r := range d.Info.Roots {
		b.WriteString(" -t " + shQuote(r.Path))
	}
	return b.String()
}

// upload copies sync.sh and plugin_list.awk into a fresh private folder on the device and returns its path.
func (d *Device) uploadSync() (string, error) {
	tmp := d.cfg.RemoteTmp + "/mpc-installer-" + randHex(4)
	for name, data := range map[string][]byte{"sync.sh": syncSH, "plugin_list.awk": pluginListAWK} {
		code, err := d.Run("mkdir -p "+shQuote(tmp)+" && cat > "+shQuote(tmp+"/"+name), bytes.NewReader(data), nil)
		if err != nil || code != 0 {
			d.Run("rm -rf "+shQuote(tmp), nil, nil)
			return "", fmt.Errorf("cannot prepare the device (status %d): %v", code, err)
		}
	}
	return tmp, nil
}

// SyncPlan asks sync.sh what it would do (--dry-run): nothing on the device is changed.
func (d *Device) SyncPlan() (SyncPlan, error) {
	plan := SyncPlan{Add: []SyncItem{}, Remove: []string{}, Skipped: []string{}}
	if len(d.Info.Roots) == 0 || d.Info.Settings == "" {
		return plan, nil
	}
	tmp, err := d.uploadSync()
	if err != nil {
		return plan, err
	}
	defer d.Run("rm -rf "+shQuote(tmp), nil, nil)
	var mu sync.Mutex
	var lines []string
	code, rerr := d.Run("cd "+shQuote(tmp)+" && MPC_SETTINGS="+shQuote(d.Info.Settings)+" sh sync.sh --dry-run"+d.syncRoots(), nil, func(l string) { mu.Lock(); lines = append(lines, l); mu.Unlock() })
	if rerr != nil || code != 0 {
		return plan, fmt.Errorf("cannot check the plugin list (status %d): %v %s", code, rerr, strings.Join(lines, " "))
	}
	for _, l := range lines {
		switch {
		case strings.HasPrefix(l, "  add    "):
			f := strings.TrimSpace(strings.TrimPrefix(l, "  add    "))
			it := SyncItem{File: f}
			for _, r := range d.Info.Roots {
				if strings.HasPrefix(f, r.Path+"/") {
					it.Root = r.Path
					it.Folder = strings.SplitN(strings.TrimPrefix(f, r.Path+"/"), "/", 2)[0]
					break
				}
			}
			plan.Add = append(plan.Add, it)
		case strings.HasPrefix(l, "  remove "):
			f := strings.TrimPrefix(l, "  remove ")
			plan.Remove = append(plan.Remove, strings.TrimSuffix(f, " (file is gone)"))
		case strings.HasPrefix(l, "  skip   "):
			plan.Skipped = append(plan.Skipped, strings.TrimSpace(strings.TrimPrefix(l, "  skip   ")))
		}
	}
	return plan, nil
}

// registerScript runs sync.sh for real between one stop and one start of MPC (sync.sh -n: the caller does that).
func registerScript(tmp, settings, roots string) string {
	var b strings.Builder
	w := func(f string, a ...any) { fmt.Fprintf(&b, f+"\n", a...) }
	w("T=%s; rc=0", shQuote(tmp))
	w("SVC=acvs; if systemctl cat ac50 >/dev/null 2>&1; then SVC=ac50; elif ! systemctl cat acvs >/dev/null 2>&1 && systemctl cat inmusic-mpc >/dev/null 2>&1; then SVC=inmusic-mpc; fi")
	w("systemctl stop $SVC")
	w("i=0; while { pidof MPC || pidof 'MPC Sample'; } >/dev/null 2>&1 && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done")
	w(`if { pidof MPC || pidof 'MPC Sample'; } >/dev/null 2>&1; then echo "MPC did not stop: nothing was changed"; rc=3; fi`)
	w(`if [ $rc = 0 ]; then`)
	w(`  (cd "$T" && MPC_SETTINGS=%s sh sync.sh -y -n%s) || rc=$?`, shQuote(settings), roots)
	w(`fi`)
	w("systemctl start $SVC")
	w(`rm -rf "$T"`)
	w("exit $rc")
	return b.String()
}

// RunRegister registers the plugin folders MPC does not know yet (and drops entries whose file is gone), with one MPC restart.
func RunRegister(dev *Device, j *Job, refresh func()) (err error) {
	defer func() {
		if err == nil && refresh != nil {
			refresh()
		}
		j.finish(err)
	}()
	if p := dev.Info.problems(); len(p) > 0 {
		return fmt.Errorf("this device cannot be changed: %s", strings.Join(p, "; "))
	}
	tmp, err := dev.uploadSync()
	if err != nil {
		return err
	}
	j.log("Registering plugin folders (MPC is stopped once and started again at the end)")
	code, rerr := dev.Run(registerScript(tmp, dev.Info.Settings, dev.syncRoots()), nil, func(l string) { j.log("  %s", l) })
	if rerr != nil {
		dev.Run("rm -rf "+shQuote(tmp), nil, nil)
		return rerr
	}
	if code != 0 {
		return fmt.Errorf("registering stopped with status %d (see the log). MPC was started again; MPC.settings is unchanged unless the log says Done", code)
	}
	return nil
}

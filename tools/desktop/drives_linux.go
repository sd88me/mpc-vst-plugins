//go:build linux

package main

import (
	"os"
	"path/filepath"
)

// listDrives finds the usual places a Linux desktop (or udisks) mounts a USB stick. Not exhaustive -- no
// /proc/mounts parsing, no removable-flag or filesystem-type check -- good enough to save typing a path; a wrong
// guess here is just an extra folder offered, never a write (building the stick still needs the folder picked and
// confirmed).
func listDrives() []driveEntry {
	user := os.Getenv("USER")
	var out []driveEntry
	bases := []string{"/mnt"}
	if user != "" {
		bases = append([]string{"/media/" + user, "/run/media/" + user}, bases...)
	}
	for _, base := range bases {
		des, err := os.ReadDir(base)
		if err != nil {
			continue
		}
		for _, d := range des {
			if !d.IsDir() {
				continue
			}
			out = append(out, driveEntry{Label: d.Name(), Path: filepath.Join(base, d.Name())})
		}
	}
	return dedupeDrives(out)
}

//go:build darwin

package main

import (
	"os"
	"path/filepath"
)

// listDrives lists mounted volumes under /Volumes, macOS's usual place for a USB stick. The boot volume itself is
// skipped: it is never a sensible pick for "where to write the stick".
func listDrives() []driveEntry {
	des, err := os.ReadDir("/Volumes")
	if err != nil {
		return nil
	}
	var out []driveEntry
	for _, d := range des {
		if !d.IsDir() || d.Name() == "Macintosh HD" {
			continue
		}
		out = append(out, driveEntry{Label: d.Name(), Path: filepath.Join("/Volumes", d.Name())})
	}
	return dedupeDrives(out)
}

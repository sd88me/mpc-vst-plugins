package main

// A server-side file/folder browser and a best-effort list of local removable drives, for the USB-stick mode's two
// path fields (the firmware file in step 1, the output folder in step 4). A browser's own file input never hands
// JS a real filesystem path (a security restriction, not a bug), so a native-feeling picker for this local app has
// to be served by the app itself. Read-only: it never writes anything, just lists what's already on disk.

import (
	"net/http"
	"os"
	"path/filepath"
	"sort"
)

type browseEntry struct {
	Name  string `json:"name"`
	Path  string `json:"path"`
	IsDir bool   `json:"isDir"`
}

type driveEntry struct {
	Label string `json:"label"`
	Path  string `json:"path"`
}

func startDir() string {
	if h, err := os.UserHomeDir(); err == nil && h != "" {
		return h
	}
	return "."
}

func (a *App) browse(w http.ResponseWriter, r *http.Request) {
	dir := r.URL.Query().Get("dir")
	if dir == "" {
		dir = startDir()
	}
	dir = filepath.Clean(dir)
	st, err := os.Stat(dir)
	if err != nil || !st.IsDir() {
		fail(w, 400, "not a folder: "+dir)
		return
	}
	des, err := os.ReadDir(dir)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	entries := make([]browseEntry, 0, len(des))
	for _, d := range des {
		name := d.Name()
		if name != "" && name[0] == '.' {
			continue // hidden folders/files are never a sensible pick here
		}
		isDir := d.IsDir()
		if d.Type()&os.ModeSymlink != 0 {
			if target, err := os.Stat(filepath.Join(dir, name)); err == nil {
				isDir = target.IsDir()
			}
		}
		entries = append(entries, browseEntry{Name: name, Path: filepath.Join(dir, name), IsDir: isDir})
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].IsDir != entries[j].IsDir {
			return entries[i].IsDir
		}
		return entries[i].Name < entries[j].Name
	})
	parent := filepath.Dir(dir)
	if parent == dir {
		parent = "" // already at a root; nothing above it
	}
	writeJSON(w, 200, map[string]any{"dir": dir, "parent": parent, "entries": entries})
}

func (a *App) drives(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"drives": listDrives()})
}

// dedupeDrives collapses entries that resolve to the same real folder (Linux offers a few candidate mount
// locations, which commonly overlap via symlinks).
func dedupeDrives(in []driveEntry) []driveEntry {
	seen := map[string]bool{}
	out := make([]driveEntry, 0, len(in))
	for _, d := range in {
		real := d.Path
		if r, err := filepath.EvalSymlinks(d.Path); err == nil {
			real = r
		}
		if seen[real] {
			continue
		}
		seen[real] = true
		out = append(out, d)
	}
	return out
}

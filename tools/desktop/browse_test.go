package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestBrowseListsDirsBeforeFilesHidingDotfiles(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"zdir", "adir", "bfile.txt", ".hidden"} {
		if name == "zdir" || name == "adir" {
			if err := os.Mkdir(filepath.Join(dir, name), 0755); err != nil {
				t.Fatal(err)
			}
		} else if err := os.WriteFile(filepath.Join(dir, name), nil, 0644); err != nil {
			t.Fatal(err)
		}
	}
	a := &App{}
	w := httptest.NewRecorder()
	a.browse(w, httptest.NewRequest(http.MethodGet, "/api/browse?dir="+dir, nil))
	if w.Code != 200 {
		t.Fatalf("status %d: %s", w.Code, w.Body)
	}
	var out struct {
		Dir     string
		Parent  string
		Entries []browseEntry
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if len(out.Entries) != 3 {
		t.Fatalf("entries = %+v, want 3 (dotfile skipped)", out.Entries)
	}
	if !out.Entries[0].IsDir || out.Entries[0].Name != "adir" {
		t.Errorf("first entry = %+v, want adir (dirs first, sorted)", out.Entries[0])
	}
	if !out.Entries[1].IsDir || out.Entries[1].Name != "zdir" {
		t.Errorf("second entry = %+v, want zdir", out.Entries[1])
	}
	if out.Entries[2].IsDir || out.Entries[2].Name != "bfile.txt" {
		t.Errorf("third entry = %+v, want bfile.txt", out.Entries[2])
	}
	if out.Parent != filepath.Dir(dir) {
		t.Errorf("parent = %q, want %q", out.Parent, filepath.Dir(dir))
	}
}

func TestBrowseRefusesAFileOrMissingPath(t *testing.T) {
	a := &App{}
	f := filepath.Join(t.TempDir(), "x")
	if err := os.WriteFile(f, nil, 0644); err != nil {
		t.Fatal(err)
	}
	for _, dir := range []string{f, filepath.Join(t.TempDir(), "nope")} {
		w := httptest.NewRecorder()
		a.browse(w, httptest.NewRequest(http.MethodGet, "/api/browse?dir="+dir, nil))
		if w.Code != 400 {
			t.Errorf("dir=%q: status %d, want 400", dir, w.Code)
		}
	}
}

func TestBrowseWithNoDirDefaultsToHome(t *testing.T) {
	a := &App{}
	w := httptest.NewRecorder()
	a.browse(w, httptest.NewRequest(http.MethodGet, "/api/browse", nil))
	if w.Code != 200 {
		t.Fatalf("status %d: %s", w.Code, w.Body)
	}
	var out struct{ Dir string }
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if home, _ := os.UserHomeDir(); out.Dir != home {
		t.Errorf("dir = %q, want home %q", out.Dir, home)
	}
}

func TestDedupeDrivesCollapsesSymlinkedDuplicates(t *testing.T) {
	real := t.TempDir()
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(real, link); err != nil {
		t.Skip("symlinks unavailable:", err)
	}
	got := dedupeDrives([]driveEntry{{Label: "a", Path: real}, {Label: "b", Path: link}})
	if len(got) != 1 {
		t.Fatalf("dedupeDrives = %+v, want 1 entry", got)
	}
}

func TestDrivesHandlerReturnsJSON(t *testing.T) {
	a := &App{}
	w := httptest.NewRecorder()
	a.drives(w, httptest.NewRequest(http.MethodGet, "/api/drives", nil))
	if w.Code != 200 {
		t.Fatalf("status %d: %s", w.Code, w.Body)
	}
	var out struct {
		Drives []driveEntry
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
}

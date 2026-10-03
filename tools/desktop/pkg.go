package main

import (
	"archive/tar"
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"regexp"
	"sort"
	"strings"
)

// A release zip made by tools/release.py (docs/RELEASING.md): one top folder with install.sh, uninstall.sh, plugin_list.awk,
// SHA256SUMS, mpc-plugin.json and portable/<skin>/. A per-user "bundle" (Monomodule: One and FX) has a top install.sh and one such
// package per sub folder instead of a manifest of its own. An addin (tools/release_addin.py: layout "addin") has the addin installer,
// addin.manifest and the addin's files at the top instead of a plugin folder, and installs to /data/mpc-addins/<id>.

const (
	maxUncompressed = 2 << 30 // refuse a zip that would unpack to more than this
	maxEntries      = 50000
)

var (
	idRe   = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)
	skinRe = regexp.MustCompile(`^[^/\\\x00-\x1f]+$`)
)

type Manifest struct {
	Schema      int      `json:"schema"`
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Version     string   `json:"version"`
	Kind        string   `json:"kind"`
	Layout      string   `json:"layout"`
	Skin        string   `json:"skin"`
	Arch        string   `json:"arch"`
	ParamCompat int      `json:"param_compat"`
	About       string   `json:"about"`
	Requires    string   `json:"requires"`
	UID         string   `json:"uid"`
	UserData    []string `json:"user_data"`
	So          string   `json:"so"`
}

type Package struct {
	Handle   string     `json:"handle"`
	Title    string     `json:"title"`
	Version  string     `json:"version"`
	Plugins  []Manifest `json:"plugins"`
	Bundle   bool       `json:"bundle"`
	Addin    bool       `json:"addin"`    // a library MPC preloads, not a plugin: it goes to the addins folder, not a Synths folder
	Defer    bool       `json:"defer"`    // every installer in it understands -n (MPC is stopped and started by the caller)
	Symlinks int        `json:"symlinks"` // links inside it (an engine's bundled Python): a FAT/exFAT drive cannot hold them
	Size     int64      `json:"size"`     // the zip
	Unpacked int64      `json:"unpacked"` // what it takes on the device
	SHA256   string     `json:"sha256"`
	Source   string     `json:"source"` // "catalog" or "upload"
	Path     string     `json:"-"`
	Top      string     `json:"-"`
}

// cleanName returns the entry name without a trailing slash, or an error for anything that could leave the package folder.
func cleanName(n string) (string, error) {
	n = strings.TrimSuffix(n, "/")
	if n == "" || strings.HasPrefix(n, "/") || strings.Contains(n, "\\") || strings.ContainsRune(n, 0) {
		return "", fmt.Errorf("unsafe path %q", n)
	}
	for _, seg := range strings.Split(n, "/") {
		if seg == ".." || seg == "" {
			return "", fmt.Errorf("unsafe path %q", n)
		}
	}
	return n, nil
}

// symlinkOK: a link target must be relative and stay inside the package folder.
func symlinkOK(entry, target string) bool {
	if target == "" || strings.HasPrefix(target, "/") || strings.Contains(target, "\\") {
		return false
	}
	resolved := path.Clean(path.Join(path.Dir(entry), target))
	return resolved != ".." && !strings.HasPrefix(resolved, "../")
}

func OpenPackage(zipPath, source string) (*Package, error) {
	st, err := os.Stat(zipPath)
	if err != nil {
		return nil, err
	}
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		return nil, fmt.Errorf("not a zip file: %w", err)
	}
	defer zr.Close()
	if len(zr.File) == 0 || len(zr.File) > maxEntries {
		return nil, errors.New("the zip is empty or has too many files")
	}
	var top string
	var total uint64
	links := 0
	names := map[string]*zip.File{}
	for _, f := range zr.File {
		n, err := cleanName(f.Name)
		if err != nil {
			return nil, err
		}
		first := strings.SplitN(n, "/", 2)[0]
		if top == "" {
			top = first
		} else if first != top {
			return nil, errors.New("the zip must hold one folder (unzip it: you should see a single folder such as Name-1.0.0)")
		}
		total += f.UncompressedSize64
		if total > maxUncompressed {
			return nil, errors.New("the zip unpacks to more than 2 GB: refusing")
		}
		if f.Mode()&fs.ModeSymlink != 0 {
			links++
			rc, err := f.Open()
			if err != nil {
				return nil, err
			}
			target, _ := io.ReadAll(io.LimitReader(rc, 4096))
			rc.Close()
			if !symlinkOK(n, string(target)) {
				return nil, fmt.Errorf("%s is a link that points outside the package", n)
			}
		}
		names[n] = f
	}
	need := func(rel string) error {
		if _, ok := names[rel]; !ok {
			return fmt.Errorf("missing %s: this is not a plugin release zip from the catalog", strings.TrimPrefix(rel, top+"/"))
		}
		return nil
	}
	readManifest := func(dir string) (*Manifest, error) {
		if err := need(dir + "/mpc-plugin.json"); err != nil {
			return nil, err
		}
		rc, err := names[dir+"/mpc-plugin.json"].Open()
		if err != nil {
			return nil, err
		}
		defer rc.Close()
		var m Manifest
		if err := json.NewDecoder(io.LimitReader(rc, 1<<20)).Decode(&m); err != nil {
			return nil, fmt.Errorf("bad mpc-plugin.json: %w", err)
		}
		files := []string{"install.sh", "uninstall.sh", "SHA256SUMS", "plugin_list.awk"}
		if m.Layout == "addin" {
			files = []string{"install.sh", "uninstall.sh", "SHA256SUMS", "addin-lib.sh", "addin.manifest", m.So}
		}
		for _, f := range files {
			if err := need(dir + "/" + f); err != nil {
				return nil, err
			}
		}
		switch {
		case m.Schema != 1:
			return nil, fmt.Errorf("mpc-plugin.json has schema %d, this app understands 1", m.Schema)
		case m.Layout == "addin":
			if m.Kind != "addin" || !idRe.MatchString(m.ID) || m.Name == "" || m.Version == "" || !strings.HasSuffix(m.So, ".so") || strings.Contains(m.So, "/") {
				return nil, errors.New("mpc-plugin.json of this addin is missing its id, name, version or library")
			}
			if m.Arch != "armv7" {
				return nil, fmt.Errorf("built for %s: MPC OS standalone devices need armv7", m.Arch)
			}
			return &m, nil
		case m.Layout != "portable":
			return nil, errors.New("this zip uses the old /sdcard/vst layout: get a newer release")
		case m.Arch != "armv7":
			return nil, fmt.Errorf("built for %s: MPC OS standalone devices need armv7", m.Arch)
		case !idRe.MatchString(m.ID) || m.Name == "" || m.Version == "" || !skinRe.MatchString(m.Skin):
			return nil, errors.New("mpc-plugin.json is missing its id, name, version or folder")
		}
		if err := need(dir + "/portable/" + m.Skin + "/plugin-meta.xml"); err != nil {
			return nil, err
		}
		return &m, nil
	}
	readAll := func(rel string) string {
		f, ok := names[rel]
		if !ok {
			return ""
		}
		rc, err := f.Open()
		if err != nil {
			return ""
		}
		defer rc.Close()
		b, _ := io.ReadAll(io.LimitReader(rc, 1<<20))
		return string(b)
	}
	p := &Package{Path: zipPath, Top: top, Source: source, Size: st.Size(), Unpacked: int64(total), Symlinks: links}
	if _, ok := names[top+"/mpc-plugin.json"]; ok {
		m, err := readManifest(top)
		if err != nil {
			return nil, err
		}
		p.Plugins, p.Title, p.Version = []Manifest{*m}, m.Name, m.Version
		p.Addin = m.Layout == "addin"
		p.Defer = strings.Contains(readAll(top+"/install.sh"), "DEFER=")
	} else { // a bundle: install.sh at the top, one package per sub folder
		if err := need(top + "/install.sh"); err != nil {
			return nil, err
		}
		if err := need(top + "/uninstall.sh"); err != nil {
			return nil, err
		}
		var subs []string
		for n := range names {
			parts := strings.Split(n, "/")
			if len(parts) == 3 && parts[2] == "mpc-plugin.json" {
				subs = append(subs, parts[0]+"/"+parts[1])
			}
		}
		sort.Strings(subs)
		if len(subs) == 0 {
			return nil, errors.New("no plugin found in this zip (no mpc-plugin.json)")
		}
		var titles []string
		for _, s := range subs {
			m, err := readManifest(s)
			if err != nil {
				return nil, err
			}
			if m.Layout == "addin" {
				return nil, errors.New("an addin cannot be part of a bundle: release it as a zip of its own")
			}
			p.Plugins = append(p.Plugins, *m)
			titles = append(titles, m.Name)
			p.Version = m.Version
		}
		p.Bundle, p.Title = true, strings.Join(titles, " + ")
		p.Defer = strings.Contains(readAll(top+"/install.sh"), `"$@"`)
		for _, s := range subs {
			p.Defer = p.Defer && strings.Contains(readAll(s+"/install.sh"), "DEFER=")
		}
	}
	h := sha256.New()
	f, err := os.Open(zipPath)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	if _, err := io.Copy(h, f); err != nil {
		return nil, err
	}
	p.SHA256 = hex.EncodeToString(h.Sum(nil))
	return p, nil
}

// WriteTar streams the package as a tar with the top folder removed, keeping modes and symlinks (a copy through Windows tools
// loses both, and an engine that bundles binaries then fails).
func (p *Package) WriteTar(w io.Writer) error {
	zr, err := zip.OpenReader(p.Path)
	if err != nil {
		return err
	}
	defer zr.Close()
	tw := tar.NewWriter(w)
	for _, f := range zr.File {
		n, err := cleanName(f.Name)
		if err != nil {
			return err
		}
		rel := strings.TrimPrefix(strings.TrimPrefix(n, p.Top), "/")
		if rel == "" {
			continue
		}
		hdr := &tar.Header{Name: rel, ModTime: f.Modified, Uid: 0, Gid: 0}
		mode := f.Mode()
		switch {
		case f.FileInfo().IsDir():
			hdr.Typeflag, hdr.Mode = tar.TypeDir, 0o755
			if err := tw.WriteHeader(hdr); err != nil {
				return err
			}
		case mode&fs.ModeSymlink != 0:
			rc, err := f.Open()
			if err != nil {
				return err
			}
			target, err := io.ReadAll(io.LimitReader(rc, 4096))
			rc.Close()
			if err != nil {
				return err
			}
			hdr.Typeflag, hdr.Linkname, hdr.Mode = tar.TypeSymlink, string(target), 0o777
			if err := tw.WriteHeader(hdr); err != nil {
				return err
			}
		default:
			hdr.Typeflag, hdr.Size = tar.TypeReg, int64(f.UncompressedSize64)
			hdr.Mode = int64(mode.Perm())
			if hdr.Mode == 0 {
				hdr.Mode = 0o644
			}
			if err := tw.WriteHeader(hdr); err != nil {
				return err
			}
			rc, err := f.Open()
			if err != nil {
				return err
			}
			_, err = io.Copy(tw, rc)
			rc.Close()
			if err != nil {
				return err
			}
		}
	}
	return tw.Close()
}

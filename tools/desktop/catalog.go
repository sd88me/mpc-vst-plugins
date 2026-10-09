package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"
)

const defaultCatalogURL = "https://sd88me.github.io/mpc-vst-plugins/catalog.json"

// Asset is one downloadable zip of a version: the Gen2 (aarch64) build sits beside the main (armv7) one.
type Asset struct {
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
	URL    string `json:"url"`
}

// CatPlugin is what the app offers from the catalog: the newest stable, non-yanked version of every downloadable plugin.
type CatPlugin struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Author      string   `json:"author"`
	Kind        string   `json:"kind"`
	Summary     string   `json:"summary"`
	Version     string   `json:"version"`
	Size        int64    `json:"size"`
	SHA256      string   `json:"sha256"`
	URL         string   `json:"url"`
	Skin        string   `json:"skin"`
	ParamCompat int      `json:"param_compat"`
	UID         string   `json:"uid"`
	UserData    []string `json:"user_data"`
	Defer       *bool    `json:"defer"`         // true: the installer understands -n (one MPC restart for a batch); false: it restarts MPC itself; null: the catalog does not say
	OSCompat    []string `json:"os_compat"`     // the MPC OS generations it works on ("2.x", "3.x"); empty when the catalog does not say
	OSWhy       []string `json:"os_compat_why"` // why it is not 2.x, when it is not
	MaxGlibc    string   `json:"max_glibc"`     // the newest glibc its library needs; empty when the catalog does not say
	Gen2        bool     `json:"gen2"`          // the version also has a Gen2 (aarch64) zip; SHA256/URL/Size above are the Gen1 (armv7) one
	Aarch64     *Asset   `json:"aarch64,omitempty"`
}

// ForArch returns the plugin with the zip that fits a device whose `uname -m` is arch: the armv7 zip on Gen1 and Force, the aarch64
// zip on Gen2 (an error when the version has none, so a Gen2 device never gets a library it cannot load).
func (c CatPlugin) ForArch(arch string) (CatPlugin, error) {
	if arch != "aarch64" {
		return c, nil
	}
	if c.Kind == "addin" || c.Aarch64 == nil {
		return c, fmt.Errorf("%s %s has no Gen2 (aarch64) build yet", c.Name, c.Version)
	}
	c.Size, c.SHA256, c.URL = c.Aarch64.Size, c.Aarch64.SHA256, c.Aarch64.URL
	return c, nil
}

type rawCatalog struct {
	Schema  int `json:"schema"`
	Plugins []struct {
		ID           string `json:"id"`
		Name         string `json:"name"`
		Author       string `json:"author"`
		Kind         string `json:"kind"`
		Summary      string `json:"summary"`
		Distribution string `json:"distribution"`
		Latest       string `json:"latest"`
		Versions     []struct {
			Version     string           `json:"version"`
			Size        int64            `json:"size"`
			SHA256      string           `json:"sha256"`
			URL         string           `json:"url"`
			Channel     string           `json:"channel"`
			Yanked      bool             `json:"yanked"`
			Defer       *bool            `json:"defer"`
			OSCompat    []string         `json:"os_compat"`
			OSWhy       []string         `json:"os_compat_why"`
			MaxGlibc    string           `json:"max_glibc"`
			Assets      map[string]Asset `json:"assets"`
			ParamCompat int              `json:"param_compat"`
			Manifest    struct {
				Skin     string   `json:"skin"`
				UID      string   `json:"uid"`
				UserData []string `json:"user_data"`
			} `json:"manifest"`
		} `json:"versions"`
	} `json:"plugins"`
}

func parseCatalog(data []byte) ([]CatPlugin, error) {
	var rc rawCatalog
	if err := json.Unmarshal(data, &rc); err != nil {
		return nil, err
	}
	if rc.Schema != 1 {
		return nil, fmt.Errorf("catalog schema %d is not supported by this app", rc.Schema)
	}
	var out []CatPlugin
	for _, p := range rc.Plugins {
		if p.Distribution != "release" || !idRe.MatchString(p.ID) {
			continue
		}
		for _, v := range p.Versions {
			if v.Yanked || v.Channel != "stable" || v.Version != p.Latest || !isHTTPS(v.URL) || len(v.SHA256) != 64 {
				continue
			}
			var a64 *Asset
			if a, ok := v.Assets["aarch64"]; ok && isHTTPS(a.URL) && len(a.SHA256) == 64 {
				a64 = &a
			}
			out = append(out, CatPlugin{ID: p.ID, Name: p.Name, Author: p.Author, Kind: p.Kind, Summary: p.Summary, Version: v.Version,
				Size: v.Size, SHA256: v.SHA256, URL: v.URL, Skin: v.Manifest.Skin, ParamCompat: v.ParamCompat, UID: v.Manifest.UID, UserData: v.Manifest.UserData, Defer: v.Defer,
				OSCompat: v.OSCompat, OSWhy: v.OSWhy, MaxGlibc: v.MaxGlibc, Gen2: a64 != nil, Aarch64: a64})
			break
		}
	}
	sort.Slice(out, func(i, j int) bool { return strings.ToLower(out[i].Name) < strings.ToLower(out[j].Name) })
	return out, nil
}

func isHTTPS(u string) bool {
	p, err := url.Parse(u)
	return err == nil && p.Scheme == "https" && p.Host != ""
}

var httpClient = &http.Client{Timeout: 20 * time.Minute}

func FetchCatalog(u string) ([]CatPlugin, error) {
	resp, err := http.Get(u) //nolint:gosec // the catalog address is the app's own setting
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("catalog: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return nil, err
	}
	return parseCatalog(data)
}

// Download fetches a release zip over https into dest and checks it against the catalog's sha256 and size; a mismatch removes it.
func Download(c CatPlugin, dest string, progress func(done, total int64)) error {
	if !isHTTPS(c.URL) {
		return errors.New("the catalog gave a download link that is not https")
	}
	resp, err := httpClient.Get(c.URL)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("download: HTTP %d", resp.StatusCode)
	}
	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	limit := c.Size + 1
	if c.Size <= 0 || c.Size > maxUncompressed {
		limit = maxUncompressed
	}
	var done int64
	buf := make([]byte, 256<<10)
	body := io.LimitReader(resp.Body, limit)
	for {
		n, rerr := body.Read(buf)
		if n > 0 {
			h.Write(buf[:n])
			if _, werr := f.Write(buf[:n]); werr != nil {
				return werr
			}
			done += int64(n)
			if progress != nil {
				progress(done, c.Size)
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return rerr
		}
	}
	if c.Size > 0 && done != c.Size {
		os.Remove(dest)
		return fmt.Errorf("%s: downloaded %d bytes, the catalog says %d", c.Name, done, c.Size)
	}
	if got := hex.EncodeToString(h.Sum(nil)); got != c.SHA256 {
		os.Remove(dest)
		return fmt.Errorf("%s does not match its sha256 in the catalog: nothing was installed", c.Name)
	}
	return nil
}

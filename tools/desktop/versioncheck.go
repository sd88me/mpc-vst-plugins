package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// defaultReleasesURL lists the releases of the repository this app is built from. The check looks only at tags named
// desktop-v<version>, so other releases (plugins, the catalog) never count.
const defaultReleasesURL = "https://api.github.com/repos/sd88me/mpc-vst-plugins/releases?per_page=30"

var tagRe = regexp.MustCompile(`^desktop-v(\d+)\.(\d+)\.(\d+)$`)

type release struct {
	Tag        string `json:"tag_name"`
	URL        string `json:"html_url"`
	Draft      bool   `json:"draft"`
	Prerelease bool   `json:"prerelease"`
}

// parseVer reads "1.2.3" (a leading v is allowed); anything else, such as "dev", is not a version.
func parseVer(s string) ([3]int, bool) {
	var v [3]int
	parts := strings.Split(strings.TrimPrefix(s, "v"), ".")
	if len(parts) != 3 {
		return v, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return v, false
		}
		v[i] = n
	}
	return v, true
}

func verLess(a, b [3]int) bool {
	for i := range a {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return false
}

// newestRelease returns the highest published desktop-v<x.y.z> release (drafts and prereleases are skipped).
func newestRelease(rs []release) (ver string, url string, ok bool) {
	var best [3]int
	for _, r := range rs {
		m := tagRe.FindStringSubmatch(r.Tag)
		if m == nil || r.Draft || r.Prerelease {
			continue
		}
		v, _ := parseVer(m[1] + "." + m[2] + "." + m[3])
		if !ok || verLess(best, v) {
			best, ver, url, ok = v, fmt.Sprintf("%d.%d.%d", v[0], v[1], v[2]), r.URL, true
		}
	}
	return
}

// versionInfo is what /api/version returns: the page shows a banner only when newer is true.
type versionInfo struct {
	Current string `json:"current"`
	Latest  string `json:"latest,omitempty"`
	URL     string `json:"url,omitempty"`
	Newer   bool   `json:"newer"`
}

// checkVersion asks GitHub for the newest desktop release, at most once an hour. A dev build, a disabled check, being offline
// or any odd answer all mean "no news": it never blocks anything and never reports an error.
func (a *App) checkVersion() versionInfo {
	info := versionInfo{Current: version}
	cur, ok := parseVer(version)
	if !ok || a.releasesURL == "" {
		return info
	}
	a.mu.Lock()
	if time.Since(a.verAt) < time.Hour && !a.verAt.IsZero() {
		defer a.mu.Unlock()
		return a.verInfo
	}
	a.mu.Unlock()
	rs, err := fetchReleases(a.releasesURL)
	a.mu.Lock()
	defer a.mu.Unlock()
	a.verAt = time.Now()
	if err == nil {
		if ver, url, ok := newestRelease(rs); ok {
			if latest, _ := parseVer(ver); verLess(cur, latest) {
				info.Latest, info.URL, info.Newer = ver, url, true
			}
		}
	}
	a.verInfo = info
	return info
}

func fetchReleases(u string) ([]release, error) {
	c := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "mpc-installer/"+version)
	resp, err := c.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("releases: %s", resp.Status)
	}
	var rs []release
	if err := json.NewDecoder(http.MaxBytesReader(nil, resp.Body, 4<<20)).Decode(&rs); err != nil {
		return nil, err
	}
	return rs, nil
}

func (a *App) versionAPI(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, a.checkVersion())
}

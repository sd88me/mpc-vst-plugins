package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestNewestReleaseIgnoresDraftsPrereleasesAndOtherTags(t *testing.T) {
	rs := []release{
		{Tag: "desktop-v0.5.9", URL: "draft", Draft: true},
		{Tag: "desktop-v0.6.0-rc1", URL: "rc"},
		{Tag: "desktop-v0.5.10", URL: "u10"},
		{Tag: "desktop-v0.5.4", URL: "u4"},
		{Tag: "v9.9.9", URL: "other"},
		{Tag: "desktop-v1.0.0", URL: "pre", Prerelease: true},
	}
	ver, url, ok := newestRelease(rs)
	if !ok || ver != "0.5.10" || url != "u10" {
		t.Fatalf("0.5.10 is newer than 0.5.4 numerically: %q %q %v", ver, url, ok)
	}
	if _, _, ok := newestRelease(nil); ok {
		t.Error("no releases, no answer")
	}
}

func checkAgainst(t *testing.T, cur string, status int, body string) (versionInfo, int) {
	t.Helper()
	hits := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		w.WriteHeader(status)
		fmt.Fprint(w, body)
	}))
	defer srv.Close()
	old := version
	version = cur
	defer func() { version = old }()
	a := NewApp(defaultConfig(), "tok", "127.0.0.1:1", "http://127.0.0.1:1/c.json", t.TempDir())
	a.releasesURL = srv.URL
	v := a.checkVersion()
	a.checkVersion() // cached for an hour
	return v, hits
}

const rel = `[{"tag_name":"desktop-v0.5.6","html_url":"https://example/r/0.5.6","draft":false,"prerelease":false},{"tag_name":"desktop-v0.5.5","html_url":"x"}]`

func TestVersionCheckReportsANewerReleaseOnceAnHour(t *testing.T) {
	v, hits := checkAgainst(t, "0.5.5", 200, rel)
	if !v.Newer || v.Latest != "0.5.6" || v.URL != "https://example/r/0.5.6" || v.Current != "0.5.5" {
		t.Errorf("a newer release is reported: %+v", v)
	}
	if hits != 1 {
		t.Errorf("one request, then the cache: %d", hits)
	}
}

func TestVersionCheckSaysNothingWhenCurrentOrDevOrOfflineOrOdd(t *testing.T) {
	for _, c := range []struct {
		cur    string
		status int
		body   string
		hits   int
	}{{"0.5.6", 200, rel, 1}, {"0.9.0", 200, rel, 1}, {"dev", 200, rel, 0}, {"0.5.5", 500, "boom", 1}, {"0.5.5", 200, "not json", 1}, {"0.5.5", 200, "[]", 1}} {
		v, hits := checkAgainst(t, c.cur, c.status, c.body)
		if v.Newer || v.Latest != "" {
			t.Errorf("%+v must not announce anything: %+v", c, v)
		}
		if hits != c.hits {
			t.Errorf("%+v: %d requests", c, hits)
		}
	}
}

func TestVersionCheckCanBeSwitchedOff(t *testing.T) {
	old := version
	version = "0.5.5"
	defer func() { version = old }()
	a := NewApp(defaultConfig(), "tok", "127.0.0.1:1", "http://127.0.0.1:1/c.json", t.TempDir())
	a.releasesURL = ""
	if v := a.checkVersion(); v.Newer {
		t.Errorf("--no-update-check: %+v", v)
	}
}

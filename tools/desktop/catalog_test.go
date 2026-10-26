package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

const catJSON = `{"schema":1,"plugins":[
 {"id":"acid","name":"Acid","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.0.1","versions":[
   {"version":"1.0.1","size":10,"sha256":"%s","url":"https://example.com/a.zip","channel":"stable","yanked":false,"param_compat":1,"manifest":{"skin":"me - VST - Acid"}},
   {"version":"1.0.0","size":9,"sha256":"%s","url":"https://example.com/old.zip","channel":"stable","yanked":false,"param_compat":1,"manifest":{"skin":"me - VST - Acid"}}]},
 {"id":"byo","name":"BYO","author":"me","kind":"instrument","summary":"s","distribution":"build-yourself","latest":"1.0.0","versions":[]},
 {"id":"http-only","name":"Plain","author":"me","kind":"effect","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":1,"sha256":"%s","url":"http://example.com/p.zip","channel":"stable","yanked":false,"param_compat":1,"manifest":{"skin":"x"}}]},
 {"id":"yanked","name":"Y","author":"me","kind":"effect","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":1,"sha256":"%s","url":"https://example.com/y.zip","channel":"stable","yanked":true,"param_compat":1,"manifest":{"skin":"x"}}]}]}`

func TestParseCatalogOffersOnlyTheNewestStableDownloadableVersion(t *testing.T) {
	h := strings.Repeat("a", 64)
	got, err := parseCatalog([]byte(strings.NewReplacer("%s", h).Replace(catJSON)))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].ID != "acid" || got[0].Version != "1.0.1" || got[0].Skin != "me - VST - Acid" {
		t.Fatalf("unexpected catalog rows: %+v", got)
	}
	if _, err := parseCatalog([]byte(`{"schema":2,"plugins":[]}`)); err == nil {
		t.Error("an unknown schema must be refused")
	}
}

// The catalog's os_compat, os_compat_why, max_glibc and 2.x test (tested[].firmware) of the version the app offers reach the row; a catalog without them leaves them empty.
func TestParseCatalogCarriesTheMPCOSFields(t *testing.T) {
	h := strings.Repeat("a", 64)
	raw := `{"schema":1,"plugins":[
 {"id":"two","name":"Two","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.1.0","versions":[
   {"version":"1.1.0","size":1,"sha256":"` + h + `","url":"https://example.com/two.zip","channel":"stable","yanked":false,"os_compat":["2.x","3.x"],"max_glibc":"2.29","tested":[{"device":"MPC Live","firmware":"2.15.1"}],"manifest":{"skin":"x"}}]},
 {"id":"three","name":"Three","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":1,"sha256":"` + h + `","url":"https://example.com/three.zip","channel":"stable","yanked":false,"os_compat":["3.x"],"os_compat_why":["TUI:tabs[] version 3 (2.15.1 uses 1)"],"max_glibc":"2.34","tested":[{"device":"Force","firmware":"3.9.1"}],"manifest":{"skin":"x"}}]},
 {"id":"old","name":"Old","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"1.0.0","versions":[
   {"version":"1.0.0","size":1,"sha256":"` + h + `","url":"https://example.com/old.zip","channel":"stable","yanked":false,"manifest":{"skin":"x"}}]}]}`
	got, err := parseCatalog([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	by := map[string]CatPlugin{}
	for _, c := range got {
		by[c.ID] = c
	}
	if g := strings.Join(by["two"].OSCompat, ","); g != "2.x,3.x" || by["two"].MaxGlibc != "2.29" || len(by["two"].OSWhy) != 0 || !by["two"].Tested2x {
		t.Errorf("two: %+v", by["two"])
	}
	if g := strings.Join(by["three"].OSCompat, ","); g != "3.x" || by["three"].MaxGlibc != "2.34" || len(by["three"].OSWhy) != 1 || by["three"].Tested2x {
		t.Errorf("three: %+v", by["three"])
	}
	if o := by["old"]; len(o.OSCompat) != 0 || o.MaxGlibc != "" {
		t.Errorf("a catalog without the fields must leave them empty: %+v", o)
	}
}

func serveZip(t *testing.T, body []byte) CatPlugin {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write(body) }))
	t.Cleanup(srv.Close)
	old := httpClient
	httpClient = srv.Client()
	t.Cleanup(func() { httpClient = old })
	sum := sha256.Sum256(body)
	return CatPlugin{ID: "acid", Name: "Acid", Version: "1", Size: int64(len(body)), SHA256: hex.EncodeToString(sum[:]), URL: srv.URL + "/a.zip"}
}

func TestDownloadChecksTheHash(t *testing.T) {
	body := []byte(strings.Repeat("plugin bytes ", 1000))
	c := serveZip(t, body)
	dest := filepath.Join(t.TempDir(), "a.zip")
	if err := Download(c, dest, nil); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(dest); string(b) != string(body) {
		t.Fatal("wrong content")
	}
	bad := c
	bad.SHA256 = strings.Repeat("0", 64)
	dest2 := filepath.Join(t.TempDir(), "b.zip")
	err := Download(bad, dest2, nil)
	if err == nil || !strings.Contains(err.Error(), "sha256") {
		t.Fatalf("a wrong hash must fail, got %v", err)
	}
	if _, err := os.Stat(dest2); err == nil {
		t.Error("a download that fails the check must be deleted")
	}
	short := c
	short.Size += 5
	if err := Download(short, filepath.Join(t.TempDir(), "c.zip"), nil); err == nil {
		t.Error("a size mismatch must fail")
	}
	plain := c
	plain.URL = strings.Replace(c.URL, "https://", "http://", 1)
	if err := Download(plain, filepath.Join(t.TempDir(), "d.zip"), nil); err == nil {
		t.Error("only https downloads are allowed")
	}
}

// serveSite answers catalog.json and patches.json the way one catalog site does; codes are the HTTP status per path (200 = real file).
func serveSite(t *testing.T, catalogStatus, patchesStatus int, catalogBody string) (*httptest.Server, *int32) {
	t.Helper()
	var hits int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		code, body := catalogStatus, catalogBody
		if strings.HasSuffix(r.URL.Path, "patches.json") {
			code, body = patchesStatus, fmt.Sprintf(goodPatchJSON, strings.Repeat("a", 64))
		}
		w.WriteHeader(code)
		if code == 200 {
			_, _ = w.Write([]byte(body))
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &hits
}

func goodCatalog() string { return strings.NewReplacer("%s", strings.Repeat("a", 64)).Replace(catJSON) }

func TestCatalogFallsBackToTheOldAddressWhenTheNewOneIsNotThereYet(t *testing.T) {
	newSite, newHits := serveSite(t, 404, 404, "")
	oldSite, oldHits := serveSite(t, 200, 200, goodCatalog())
	a := NewApp(defaultConfig(), "tok", "127.0.0.1:1", newSite.URL+"/mpc-vst-plugins/catalog.json", t.TempDir())
	a.fallbacks = []string{oldSite.URL + "/mpc-vst-plugins/catalog.json"}
	cat, err := a.fetchCatalog()
	if err != nil || len(cat) != 1 || cat[0].ID != "acid" {
		t.Fatalf("fallback: %v %+v", err, cat)
	}
	if atomic.LoadInt32(newHits) != 1 || atomic.LoadInt32(oldHits) != 1 {
		t.Errorf("each address should be asked once: new %d old %d", *newHits, *oldHits)
	}
	// patches.json is asked the same way: a 404 at the new address must not read as "no patches published".
	ps, err := a.fetchPatches()
	if err != nil || len(ps) != 1 {
		t.Fatalf("patches fallback: %v %+v", err, ps)
	}
}

func TestCatalogUsesTheNewAddressAndNeverTouchesTheOldWhenItAnswers(t *testing.T) {
	newSite, _ := serveSite(t, 200, 200, goodCatalog())
	oldSite, oldHits := serveSite(t, 200, 200, goodCatalog())
	a := NewApp(defaultConfig(), "tok", "127.0.0.1:1", newSite.URL+"/c/catalog.json", t.TempDir())
	a.fallbacks = []string{oldSite.URL + "/c/catalog.json"}
	if _, err := a.fetchCatalog(); err != nil {
		t.Fatal(err)
	}
	if _, err := a.fetchPatches(); err != nil {
		t.Fatal(err)
	}
	if atomic.LoadInt32(oldHits) != 0 {
		t.Errorf("the old address was asked %d times although the new one answered", *oldHits)
	}
}

func TestCatalogFallsBackWhenTheNewAddressAnswersWithSomethingThatIsNotACatalog(t *testing.T) {
	newSite, _ := serveSite(t, 200, 200, "<html>a Pages 200 page, not a catalog</html>")
	oldSite, _ := serveSite(t, 200, 200, goodCatalog())
	a := NewApp(defaultConfig(), "tok", "127.0.0.1:1", newSite.URL+"/c/catalog.json", t.TempDir())
	a.fallbacks = []string{oldSite.URL + "/c/catalog.json"}
	if cat, err := a.fetchCatalog(); err != nil || len(cat) != 1 {
		t.Fatalf("non-catalog answer must fall back: %v %+v", err, cat)
	}
}

func TestCatalogErrorNamesEveryAddressThatFailed(t *testing.T) {
	newSite, _ := serveSite(t, 404, 404, "")
	oldSite, _ := serveSite(t, 500, 500, "")
	a := NewApp(defaultConfig(), "tok", "127.0.0.1:1", newSite.URL+"/c/catalog.json", t.TempDir())
	a.fallbacks = []string{oldSite.URL + "/c/catalog.json"}
	_, err := a.fetchCatalog()
	if err == nil || !strings.Contains(err.Error(), "HTTP 404") || !strings.Contains(err.Error(), "HTTP 500") || !strings.Contains(err.Error(), newSite.URL) {
		t.Fatalf("error should list both failures: %v", err)
	}
	// a custom --catalog has no fallback and keeps the plain error
	b := NewApp(defaultConfig(), "tok", "127.0.0.1:1", oldSite.URL+"/c/catalog.json", t.TempDir())
	if _, err := b.fetchCatalog(); err == nil || err.Error() != "catalog: HTTP 500" {
		t.Fatalf("single address error unchanged: %v", err)
	}
	// a 404 at one address and a server error at the other surfaces the error, not "no patches published"
	if _, err := a.fetchPatches(); err == nil || errors.Is(err, errNoPatches) {
		t.Fatalf("patches: want the server error, got %v", err)
	}
	// 404 everywhere is still "no patches published"
	c := NewApp(defaultConfig(), "tok", "127.0.0.1:1", newSite.URL+"/c/catalog.json", t.TempDir())
	c.fallbacks = []string{newSite.URL + "/d/catalog.json"}
	if _, err := c.fetchPatches(); !errors.Is(err, errNoPatches) {
		t.Fatalf("404 everywhere: want errNoPatches, got %v", err)
	}
}

func TestDefaultCatalogAddressesAreTheOrgThenTheOldSite(t *testing.T) {
	if defaultCatalogURL != "https://open-mpc.github.io/mpc-vst-plugins/catalog.json" || legacyCatalogURL != "https://sd88me.github.io/mpc-vst-plugins/catalog.json" {
		t.Fatalf("default %q legacy %q", defaultCatalogURL, legacyCatalogURL)
	}
}

package main

import (
	"crypto/subtle"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

//go:embed web/index.html
var indexHTML []byte

// App is the local web server. It listens on 127.0.0.1 only and every request must carry the random token the app printed, so
// nothing else on the network, and no web page open in the browser, can drive it. Nothing about the device is written to disk.
type App struct {
	cfg        Config
	token      string
	hosts      map[string]bool // accepted Host headers
	catalogURL string
	patchesURL string
	work       string

	mu      sync.Mutex
	dev     *Device
	uploads map[string]*Package
	cat     []CatPlugin
	catAt   time.Time
	job     *Job

	patches   []Patch
	patchesAt time.Time
	patchNote string            // why there are no patches (none published yet), shown by the page
	patchCode map[string][]byte // verified scripts by sha256, so connecting again does not download them again
}

func NewApp(cfg Config, token, hostport, catalogURL, work string) *App {
	port := hostport[strings.LastIndex(hostport, ":")+1:]
	return &App{cfg: cfg, token: token, catalogURL: catalogURL, patchesURL: patchesURLFor(catalogURL), work: work, uploads: map[string]*Package{}, patchCode: map[string][]byte{},
		hosts: map[string]bool{"127.0.0.1:" + port: true, "localhost:" + port: true}}
}

func (a *App) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", a.index)
	mux.HandleFunc("/api/state", a.state)
	mux.HandleFunc("/api/connect", a.connect)
	mux.HandleFunc("/api/disconnect", a.disconnect)
	mux.HandleFunc("/api/catalog", a.catalog)
	mux.HandleFunc("/api/upload", a.upload)
	mux.HandleFunc("/api/discard", a.discard)
	mux.HandleFunc("/api/plan", a.plan)
	mux.HandleFunc("/api/install", a.install)
	mux.HandleFunc("/api/device", a.devicePlugins)
	mux.HandleFunc("/api/remove", a.remove)
	mux.HandleFunc("/api/unregistered", a.unregistered)
	mux.HandleFunc("/api/register", a.register)
	mux.HandleFunc("/api/backups", a.backups)
	mux.HandleFunc("/api/prune", a.prune)
	mux.HandleFunc("/api/job", a.jobStatus)
	mux.HandleFunc("/api/patches", a.patchList)
	mux.HandleFunc("/api/patch/run", a.patchRun)
	return a.guard(mux)
}

func (a *App) guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("Cache-Control", "no-store")
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("Referrer-Policy", "no-referrer")
		h.Set("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'")
		if !a.hosts[r.Host] { // a page reaching us through a rebound DNS name has another Host
			http.Error(w, "unexpected host", http.StatusForbidden)
			return
		}
		if o := r.Header.Get("Origin"); o != "" && !a.hosts[strings.TrimPrefix(o, "http://")] {
			http.Error(w, "unexpected origin", http.StatusForbidden)
			return
		}
		got := r.Header.Get("X-MPC-Token")
		if r.URL.Path == "/" {
			got = r.URL.Query().Get("t")
		}
		if subtle.ConstantTimeCompare([]byte(got), []byte(a.token)) != 1 {
			http.Error(w, "open the link the app printed (it contains the access token)", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

func postOnly(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "POST only")
		return false
	}
	return true
}

func (a *App) index(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(indexHTML)
}

func (a *App) state(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	defer a.mu.Unlock()
	up := []*Package{}
	for _, p := range a.uploads {
		up = append(up, p)
	}
	out := map[string]any{"connected": a.dev != nil, "uploads": up}
	if a.dev != nil {
		out["device"] = a.dev.Info
		out["problems"] = a.dev.Info.problems()
	}
	if a.job != nil {
		out["job"] = a.job.ID
	}
	writeJSON(w, 200, out)
}

func (a *App) connect(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct{ Host, Password string }
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	dev, err := Dial(strings.TrimSpace(in.Host), in.Password, a.cfg)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	a.mu.Lock()
	if a.dev != nil {
		a.dev.Close()
	}
	a.dev = dev
	a.mu.Unlock()
	writeJSON(w, 200, map[string]any{"device": dev.Info, "problems": dev.Info.problems()})
}

func (a *App) disconnect(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	a.mu.Lock()
	if a.dev != nil {
		a.dev.Close()
		a.dev = nil
	}
	a.mu.Unlock()
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) catalog(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	if a.cat == nil || time.Since(a.catAt) > 10*time.Minute {
		a.mu.Unlock()
		cat, err := FetchCatalog(a.catalogURL)
		if err != nil {
			fail(w, 502, "cannot read the catalog: "+err.Error()+" (you can still install zips you have already downloaded)")
			return
		}
		a.mu.Lock()
		a.cat, a.catAt = cat, time.Now()
	}
	defer a.mu.Unlock()
	where := map[string]DevPlugin{} // plugin folder -> where it is (the internal drive wins)
	if a.dev != nil {
		for _, dp := range a.dev.Info.Plugins {
			if _, ok := where[dp.Folder]; !ok {
				where[dp.Folder] = dp
			}
		}
	}
	type row struct {
		CatPlugin
		Installed        bool   `json:"installed"`
		InstalledAt      string `json:"installedAt,omitempty"` // the place, when it is not the internal drive
		InstalledVersion string `json:"installedVersion,omitempty"`
		Update           bool   `json:"update"`
	}
	rows := []row{}
	for _, c := range a.cat {
		if c.Kind == "addin" { // an addin is found by its id in the addins folder, and its folder records the version
			iv, ok := "", false
			if a.dev != nil {
				for _, da := range a.dev.Info.Addins {
					if da.ID == c.ID {
						iv, ok = da.Version, true
					}
				}
			}
			rows = append(rows, row{c, ok, "", iv, iv != "" && iv != c.Version})
			continue
		}
		dp, ok := where[c.Skin]
		iv, at := "", ""
		if ok {
			iv = a.dev.Info.Stores[dp.Root][c.ID]
			if rt, found := a.dev.Info.root(dp.Root); found && !rt.Primary {
				at = rt.Label
			}
		}
		rows = append(rows, row{c, ok, at, iv, iv != "" && iv != c.Version})
	}
	writeJSON(w, 200, map[string]any{"plugins": rows})
}

func (a *App) upload(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 2*maxUncompressed)
	mr, err := r.MultipartReader()
	if err != nil {
		fail(w, 400, "expected a file upload")
		return
	}
	type res struct {
		Name    string   `json:"name"`
		Package *Package `json:"package,omitempty"`
		Error   string   `json:"error,omitempty"`
	}
	var out []res
	for {
		part, err := mr.NextPart()
		if err == io.EOF {
			break
		}
		if err != nil {
			fail(w, 400, err.Error())
			return
		}
		name := filepath.Base(part.FileName())
		if part.FileName() == "" {
			continue
		}
		handle := randHex(6)
		dest := filepath.Join(a.work, handle+".zip")
		f, err := os.Create(dest)
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		_, cerr := io.Copy(f, part)
		f.Close()
		if cerr != nil {
			os.Remove(dest)
			fail(w, 400, "upload failed: "+cerr.Error())
			return
		}
		p, perr := OpenPackage(dest, "upload")
		if perr != nil {
			os.Remove(dest)
			out = append(out, res{Name: name, Error: perr.Error()})
			continue
		}
		p.Handle = handle
		a.mu.Lock()
		a.uploads[handle] = p
		a.mu.Unlock()
		out = append(out, res{Name: name, Package: p})
	}
	writeJSON(w, 200, map[string]any{"results": out})
}

func (a *App) discard(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct{ Handle string }
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<12)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	a.mu.Lock()
	if p, ok := a.uploads[in.Handle]; ok {
		os.Remove(p.Path)
		delete(a.uploads, in.Handle)
	}
	a.mu.Unlock()
	writeJSON(w, 200, map[string]bool{"ok": true})
}

type selection struct {
	Catalog []string `json:"catalog"`
	Uploads []string `json:"uploads"`
	Root    string   `json:"root"` // the Synths folder to install into ("" = the internal drive)
	Confirm bool     `json:"confirm"`
}

// resolve turns a selection into install items. Caller holds a.mu.
func (a *App) resolve(s selection) ([]Item, error) {
	var items []Item
	seen := map[string]bool{}
	for _, id := range s.Catalog {
		if seen["c"+id] {
			continue
		}
		seen["c"+id] = true
		var found *CatPlugin
		for i := range a.cat {
			if a.cat[i].ID == id {
				c := a.cat[i]
				found = &c
			}
		}
		if found == nil {
			return nil, fmt.Errorf("%q is not in the catalog", id)
		}
		items = append(items, Item{Catalog: found})
	}
	for _, h := range s.Uploads {
		if seen["u"+h] {
			continue
		}
		seen["u"+h] = true
		p, ok := a.uploads[h]
		if !ok {
			return nil, errors.New("a zip you added is no longer there: add it again")
		}
		items = append(items, Item{Pkg: p})
	}
	if len(items) == 0 {
		return nil, errors.New("nothing selected")
	}
	return items, nil
}

func (a *App) plan(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var s selection
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&s); err != nil {
		fail(w, 400, "bad request")
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	items, err := a.resolve(s)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	type line struct {
		Title   string `json:"title"`
		Version string `json:"version"`
		Source  string `json:"source"`
		MB      int64  `json:"mb"`
	}
	var lines []line
	restarts := 0
	anyDefer, fromCatalog := false, false
	for _, it := range items {
		if it.Catalog != nil {
			lines = append(lines, line{it.Catalog.Name, it.Catalog.Version, "catalog", it.Catalog.Size >> 20})
			switch {
			case it.Catalog.Defer == nil:
				anyDefer, fromCatalog = true, true // an older catalog does not say: only known once the zip is downloaded
			case *it.Catalog.Defer:
				anyDefer = true
			default:
				restarts++ // its installer restarts MPC by itself
			}
		} else {
			lines = append(lines, line{it.Pkg.Title, it.Pkg.Version, "your zip", it.Pkg.Size >> 20})
			if it.Pkg.Defer {
				anyDefer = true
			} else {
				restarts++
			}
		}
	}
	if anyDefer {
		restarts++
	}
	writeJSON(w, 200, map[string]any{"items": lines, "restarts": restarts, "maybeMore": fromCatalog})
}

func (a *App) install(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var s selection
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&s); err != nil {
		fail(w, 400, "bad request")
		return
	}
	if !s.Confirm {
		fail(w, 400, "the install must be confirmed")
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	if a.job != nil {
		if st, _, _, _ := a.job.snapshot(0); st == "running" {
			fail(w, 409, "an install is already running")
			return
		}
	}
	items, err := a.resolve(s)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	root := a.dev.Info.primaryRoot()
	if s.Root != "" {
		var ok bool
		if root, ok = a.dev.Info.root(s.Root); !ok {
			fail(w, 400, "that is not a plugin location on the device")
			return
		}
	}
	j := &Job{ID: randHex(4), State: "running"}
	a.job = j
	dev := a.dev
	go RunInstall(dev, root, items, a.work, j, func() {
		a.mu.Lock()
		defer a.mu.Unlock()
		if a.dev == dev {
			dev.readInfo(dev.Info.Host, dev.Info.Fingerprint)
		}
	})
	writeJSON(w, 200, map[string]string{"job": j.ID})
}

func (a *App) jobStatus(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	j := a.job
	a.mu.Unlock()
	if j == nil {
		fail(w, 404, "no install has been started")
		return
	}
	since := 0
	fmt.Sscanf(r.URL.Query().Get("since"), "%d", &since)
	st, lines, next, result := j.snapshot(since)
	writeJSON(w, 200, map[string]any{"id": j.ID, "state": st, "lines": lines, "next": next, "result": result})
}

// knownPlugin says what the app can tell about a plugin folder on the device: which files are the user's own is only known for
// plugins from the catalog and for zips dropped into this session, so those are the ones it will remove.
type knownPlugin struct {
	DevPlugin
	ID        string   `json:"id"`
	Version   string   `json:"version,omitempty"`
	RootLabel string   `json:"rootLabel"`
	Known     bool     `json:"known"`
	Keep      []string `json:"keep"`
	Source    string   `json:"source,omitempty"`
	Addin     bool     `json:"addin"`
}

// classify matches the device's plugin folders to the catalog and to the dropped zips. Caller holds a.mu and a.dev != nil.
func (a *App) classify() []knownPlugin {
	out := []knownPlugin{}
	for _, dp := range a.dev.Info.Plugins {
		kp := knownPlugin{DevPlugin: dp, Keep: []string{}}
		for _, c := range a.cat {
			if c.Skin == dp.Folder {
				kp.ID, kp.Known, kp.Source = c.ID, true, "catalog"
				if c.UserData != nil {
					kp.Keep = c.UserData
				}
			}
		}
		if !kp.Known {
			for _, p := range a.uploads {
				for _, m := range p.Plugins {
					if m.Skin == dp.Folder {
						kp.ID, kp.Known, kp.Source = m.ID, true, "your zip"
						if m.UserData != nil {
							kp.Keep = m.UserData
						}
					}
				}
			}
		}
		kp.Version = a.dev.Info.Stores[dp.Root][kp.ID]
		if rt, ok := a.dev.Info.root(dp.Root); ok {
			kp.RootLabel = rt.Label
		}
		out = append(out, kp)
	}
	for _, da := range a.dev.Info.Addins { // listed after the plugins, as one more location; removable when it carries its uninstall.sh
		out = append(out, knownPlugin{DevPlugin: DevPlugin{Root: a.dev.cfg.AddinsDir, Folder: da.ID, Name: da.Name}, ID: da.ID,
			Version: da.Version, RootLabel: "Addins", Known: da.Removable, Keep: []string{}, Source: "addin", Addin: true})
	}
	return out
}

// ensureCat loads the catalog if it is not loaded yet, so plugins from it can be recognised; an offline catalog is not an error here.
func (a *App) ensureCat() {
	a.mu.Lock()
	ok := a.cat != nil && time.Since(a.catAt) <= 10*time.Minute
	a.mu.Unlock()
	if ok {
		return
	}
	if cat, err := FetchCatalog(a.catalogURL); err == nil {
		a.mu.Lock()
		a.cat, a.catAt = cat, time.Now()
		a.mu.Unlock()
	}
}

func (a *App) devicePlugins(w http.ResponseWriter, r *http.Request) {
	a.ensureCat()
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	writeJSON(w, 200, map[string]any{"plugins": a.classify(), "roots": a.dev.Info.Roots})
}

func (a *App) remove(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct {
		Items []struct {
			Root   string `json:"root"`
			Folder string `json:"folder"`
		} `json:"items"`
		Confirm bool `json:"confirm"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	if !in.Confirm {
		fail(w, 400, "the removal must be confirmed")
		return
	}
	a.ensureCat()
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	if a.job != nil {
		if st, _, _, _ := a.job.snapshot(0); st == "running" {
			fail(w, 409, "a job is already running")
			return
		}
	}
	byKey := map[string]knownPlugin{}
	for _, kp := range a.classify() {
		byKey[kp.Root+"\x00"+kp.Folder] = kp
	}
	var plans []RemovePlan
	seen := map[string]bool{}
	for _, it := range in.Items { // the plan is rebuilt here from what the device and the catalog say, never from the page
		key := it.Root + "\x00" + it.Folder
		if seen[key] {
			continue
		}
		seen[key] = true
		kp, ok := byKey[key]
		if !ok {
			fail(w, 400, fmt.Sprintf("%q is not a plugin folder on the device", it.Folder))
			return
		}
		if kp.Addin && !kp.Known {
			fail(w, 400, fmt.Sprintf("the addin %s has no uninstall.sh in its folder (it was not installed by the addin installer): remove it by hand", it.Folder))
			return
		}
		if !kp.Known {
			fail(w, 400, fmt.Sprintf("%s was not installed from the catalog, so the app cannot tell which files in it are yours. Drop its release zip above to manage it, or remove it by hand.", it.Folder))
			return
		}
		plans = append(plans, RemovePlan{Root: kp.Root, Folder: kp.Folder, UID: kp.UID, ID: kp.ID, Keep: kp.Keep, Addin: kp.Addin})
	}
	if len(plans) == 0 {
		fail(w, 400, "nothing selected")
		return
	}
	j := &Job{ID: randHex(4), State: "running"}
	a.job = j
	dev := a.dev
	go RunRemove(dev, plans, j, func() {
		a.mu.Lock()
		defer a.mu.Unlock()
		if a.dev == dev {
			dev.readInfo(dev.Info.Host, dev.Info.Fingerprint)
		}
	})
	writeJSON(w, 200, map[string]string{"job": j.ID})
}

// unregistered says which plugin folders MPC does not know yet (what registering would add), without changing anything.
func (a *App) unregistered(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	dev := a.dev
	a.mu.Unlock()
	if dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	plan, err := dev.SyncPlan()
	if err != nil {
		fail(w, 502, err.Error())
		return
	}
	labels := map[string]string{}
	for _, rt := range dev.Info.Roots {
		labels[rt.Path] = rt.Label
	}
	type item struct {
		SyncItem
		RootLabel string `json:"rootLabel"`
	}
	add := []item{}
	for _, it := range plan.Add {
		add = append(add, item{it, labels[it.Root]})
	}
	writeJSON(w, 200, map[string]any{"add": add, "remove": plan.Remove, "skipped": plan.Skipped})
}

func (a *App) register(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct {
		Confirm bool `json:"confirm"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<12)).Decode(&in); err != nil || !in.Confirm {
		fail(w, 400, "registering must be confirmed")
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	if a.job != nil {
		if st, _, _, _ := a.job.snapshot(0); st == "running" {
			fail(w, 409, "a job is already running")
			return
		}
	}
	j := &Job{ID: randHex(4), State: "running"}
	a.job = j
	dev := a.dev
	go RunRegister(dev, j, func() {
		a.mu.Lock()
		defer a.mu.Unlock()
		if a.dev == dev {
			dev.readInfo(dev.Info.Host, dev.Info.Fingerprint)
		}
	})
	writeJSON(w, 200, map[string]string{"job": j.ID})
}

func (a *App) backups(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	dev := a.dev
	a.mu.Unlock()
	if dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	bi, err := dev.Backups()
	if err != nil {
		fail(w, 502, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"backups": bi, "keepDefault": 10, "keepMin": minKeep, "keepMax": maxKeep})
}

func (a *App) prune(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct {
		Keep    int  `json:"keep"`
		Confirm bool `json:"confirm"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<12)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	if !in.Confirm {
		fail(w, 400, "the cleanup must be confirmed")
		return
	}
	if in.Keep < minKeep || in.Keep > maxKeep {
		fail(w, 400, fmt.Sprintf("keep between %d and %d backups: the newest one is never deleted", minKeep, maxKeep))
		return
	}
	a.mu.Lock()
	dev := a.dev
	busy := false
	if a.job != nil {
		if st, _, _, _ := a.job.snapshot(0); st == "running" {
			busy = true
		}
	}
	a.mu.Unlock()
	if dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	if busy {
		fail(w, 409, "an install or removal is running: wait for it to finish")
		return
	}
	n, err := dev.PruneBackups(in.Keep, nil)
	if err != nil {
		fail(w, 502, err.Error())
		return
	}
	bi, _ := dev.Backups()
	writeJSON(w, 200, map[string]any{"deleted": n, "backups": bi})
}

// patchList is read only: the manifest (cached ten minutes) and, when connected, each patch's state from its script's `status`.
// Nothing is applied here; while a job runs the device is not asked at all.
func (a *App) patchList(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	if a.patches == nil || time.Since(a.patchesAt) > 10*time.Minute {
		a.mu.Unlock()
		ps, err := FetchPatches(a.patchesURL)
		a.mu.Lock()
		switch {
		case errors.Is(err, errNoPatches):
			a.patches, a.patchesAt, a.patchNote = []Patch{}, time.Now(), "No device patches are published yet."
		case err != nil:
			a.mu.Unlock()
			fail(w, 502, "cannot read the patch list: "+err.Error())
			return
		default:
			a.patches, a.patchesAt, a.patchNote = ps, time.Now(), ""
		}
	}
	patches, note, dev := a.patches, a.patchNote, a.dev
	if a.job != nil {
		if st, _, _, _ := a.job.snapshot(0); st == "running" {
			dev, note = nil, "A job is running: patch states are checked when it is done."
		}
	}
	a.mu.Unlock()
	fetch := a.patchScript
	writeJSON(w, 200, map[string]any{"patches": PatchRows(dev, patches, fetch), "note": note, "connected": dev != nil})
}

// patchScript returns a patch's script, downloaded once and checked against the manifest's sha256 (never an unverified copy).
func (a *App) patchScript(p Patch) ([]byte, error) {
	a.mu.Lock()
	data, ok := a.patchCode[p.Script.SHA256]
	a.mu.Unlock()
	if ok {
		return data, nil
	}
	data, err := FetchPatchScript(p)
	if err != nil {
		return nil, err
	}
	a.mu.Lock()
	a.patchCode[p.Script.SHA256] = data
	a.mu.Unlock()
	return data, nil
}

// patchRun applies or undoes one patch from the published manifest. The patch is found by id in the manifest the app fetched, never
// described by the page; the user must have typed the confirmation word for that action; one job at a time. Progress is the job log.
func (a *App) patchRun(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct {
		ID      string `json:"id"`
		Action  string `json:"action"`
		Confirm string `json:"confirm"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<12)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	word := map[string]string{"install": ConfirmApply, "uninstall": ConfirmUndo}[in.Action]
	if word == "" {
		fail(w, 400, "unknown action")
		return
	}
	if in.Confirm != word {
		fail(w, 400, "type "+word+" to confirm")
		return
	}
	busy := func() bool {
		if a.job != nil {
			st, _, _, _ := a.job.snapshot(0)
			return st == "running"
		}
		return false
	}
	a.mu.Lock()
	var p *Patch
	for i := range a.patches {
		if a.patches[i].ID == in.ID {
			p = &a.patches[i]
		}
	}
	dev := a.dev
	switch {
	case dev == nil:
		a.mu.Unlock()
		fail(w, 400, "connect to the device first")
		return
	case p == nil:
		a.mu.Unlock()
		fail(w, 404, "that patch is not in the list (open the Advanced step first)")
		return
	case busy():
		a.mu.Unlock()
		fail(w, 409, "a job is already running")
		return
	}
	patch := *p
	a.mu.Unlock()
	if dev.Info.Arch != "" && patch.Supports.Arch != dev.Info.Arch {
		fail(w, 400, "this patch is built for "+patch.Supports.Arch+"; this device is "+dev.Info.Arch)
		return
	}
	if in.Action == "uninstall" && !patch.Reversible {
		fail(w, 400, "this patch cannot be undone from the app")
		return
	}
	script, err := a.patchScript(patch)
	if err != nil {
		fail(w, 502, err.Error())
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev != dev {
		fail(w, 409, "the device changed; try again")
		return
	}
	if busy() { // the lock was released while the script was fetched
		fail(w, 409, "a job is already running")
		return
	}
	j := &Job{ID: randHex(4), State: "running"}
	a.job = j
	go RunPatch(dev, patch, script, in.Action, j, func() {
		a.mu.Lock()
		defer a.mu.Unlock()
		if a.dev == dev {
			dev.readInfo(dev.Info.Host, dev.Info.Fingerprint)
		}
	})
	writeJSON(w, 200, map[string]string{"job": j.ID})
}

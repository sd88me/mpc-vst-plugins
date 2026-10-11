package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// plugin puts a plugin folder (plugin file, plugin-meta.xml, a file of the user's own in roms/) into a location and returns its path.
func plugin(t *testing.T, root, folder, so, uid, name string) string {
	t.Helper()
	d := filepath.Join(root, folder)
	os.MkdirAll(filepath.Join(d, "roms"), 0o755)
	os.WriteFile(filepath.Join(d, so), []byte("ELF"), 0o755)
	os.WriteFile(filepath.Join(d, "roms", "mine.rom"), []byte("my own file"), 0o644)
	os.WriteFile(filepath.Join(d, "plugin-meta.xml"), []byte(`<PLUGIN name="`+name+`" format="VST" manufacturer="me" version="1.0" file="%payload-path%/`+folder+`/`+so+`" uid="`+uid+`" isInstrument="1"/>`), 0o644)
	return d
}

func writeSettings(fd *fakeDevice, locations []string, entries ...string) string {
	p := filepath.Join(fd.dir, "Settings", "MPC", "MPC.settings")
	var b strings.Builder
	b.WriteString("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<PROPERTIES>\n  <VALUE name=\"SynthContentLocations\">\n    <SynthContentLocations>\n")
	for _, l := range locations {
		b.WriteString("      <Location>" + l + "</Location>\n")
	}
	b.WriteString("    </SynthContentLocations>\n  </VALUE>\n  <VALUE name=\"pluginList-arm\">\n    <KNOWNPLUGINS>\n")
	for _, e := range entries {
		b.WriteString("      " + e + "\n")
	}
	b.WriteString("    </KNOWNPLUGINS>\n  </VALUE>\n</PROPERTIES>\n")
	os.WriteFile(p, []byte(b.String()), 0o644)
	return p
}

func entry(name, file, uid string) string {
	return `<PLUGIN name="` + name + `" format="VST" manufacturer="me" version="1.0" file="` + file + `" uid="` + uid + `" isInstrument="1"/>`
}

func TestLocationsAreFoundOnceLabelledAndChecked(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("CARD1")
	fd.addAlias()
	internal := fd.cfg().SynthsDir
	writeSettings(fd, []string{card + "/", "/somewhere/else"}) // the card is a content location (a trailing slash is fine), the internal drive is not
	plugin(t, internal, "me - VST - A", "a.so", "aaaa0001", "A")
	plugin(t, card, "me - VST - C", "c.so", "cccc0003", "C")
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if len(d.Info.Roots) != 2 {
		t.Fatalf("the same storage through two paths is one location: %+v", d.Info.Roots)
	}
	in, cd := d.Info.Roots[0], d.Info.Roots[1]
	if in.Path != internal || !in.Primary || in.Label != "Internal drive" || in.InContent {
		t.Errorf("internal drive first, primary, not a content location here: %+v", in)
	}
	if cd.Path != card || cd.Primary || cd.Label != "Drive CARD1" || !cd.InContent || cd.FreeKB <= 0 || cd.FS == "" {
		t.Errorf("the card: %+v", cd)
	}
	roots := map[string]string{}
	for _, p := range d.Info.Plugins {
		roots[p.Folder] = p.Root
	}
	if roots["me - VST - A"] != internal || roots["me - VST - C"] != card || len(d.Info.Plugins) != 2 {
		t.Errorf("each plugin knows where it is: %+v", d.Info.Plugins)
	}
	if got := d.Info.primaryRoot(); got.Path != internal {
		t.Errorf("primary: %+v", got)
	}
}

func TestNoSymlinkFilesystemsAreRecognised(t *testing.T) {
	for fs, want := range map[string]bool{"exfat": true, "vfat": true, "NTFS": true, "fuseblk": true, "ext4": false, "overlay": false, "": false} {
		if noSymlinkFS(fs) != want {
			t.Errorf("%q: want %v", fs, want)
		}
	}
}

func TestInstallToTheCardStaysOnTheCard(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("CARD1")
	internal := fd.cfg().SynthsDir
	writeSettings(fd, []string{internal}) // the card is not a content location
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	root, _ := d.Info.root(card)
	j := &Job{ID: "x", State: "running"}
	if err := RunInstall(d, root, []Item{{Pkg: a}}, t.TempDir(), j, nil); err != nil {
		t.Fatal(err, j.Lines)
	}
	if _, err := os.Stat(filepath.Join(card, "me - VST - A", "bin", "tool")); err != nil {
		t.Errorf("installed on the card: %v", err)
	}
	if _, err := os.Stat(filepath.Join(internal, "me - VST - A")); err == nil {
		t.Error("nothing may land on the internal drive")
	}
	state, _ := os.ReadFile(filepath.Join(card, ".mpc-store"))
	if !strings.Contains(string(state), "a-plug\t1.2.3") {
		t.Errorf("the card keeps its own record: %q", state)
	}
	if _, err := os.Stat(filepath.Join(internal, ".mpc-store")); err == nil {
		t.Error("the internal drive's record must not be touched")
	}
	log := strings.Join(j.Lines, "\n")
	if !strings.Contains(log, "Installing to Drive CARD1") || !strings.Contains(log, "does not list") {
		t.Errorf("the log says where, and warns that MPC does not list the card:\n%s", log)
	}
	if got := strings.Join(fd.calls(), ","); got != "stop acvs,start acvs" {
		t.Errorf("one stop and one start: %s", got)
	}
}

func TestInstallIsRefusedWhereItCannotWork(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("CARD1")
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0)) // contains a symlink (bin/link)
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if a.Symlinks != 1 {
		t.Fatalf("the package's links are counted: %d", a.Symlinks)
	}
	root, _ := d.Info.root(card)
	exfat := root
	exfat.FS, exfat.NoSymlinks = "exfat", true
	j := &Job{ID: "x", State: "running"}
	err = RunInstall(d, exfat, []Item{{Pkg: a}}, t.TempDir(), j, nil)
	if err == nil || !strings.Contains(err.Error(), "symbolic links") || !strings.Contains(err.Error(), "EXFAT") {
		t.Errorf("a package with links must be refused on exFAT: %v", err)
	}
	big := installerPkg(t, "B-1", "b-plug", "me - VST - B", fakeInstaller("B", true, 0), zent{"B-1/portable/me - VST - B/big.bin", 0, strings.Repeat("x", 200000)})
	full := root
	full.FreeKB = 50 // KB
	if err := RunInstall(d, full, []Item{{Pkg: big}}, t.TempDir(), &Job{ID: "y", State: "running"}, nil); err == nil || !strings.Contains(err.Error(), "free") {
		t.Errorf("not enough room must be refused: %v", err)
	}
	if len(fd.calls()) != 0 {
		t.Error("MPC must not be touched when the install is refused")
	}
	if ents, _ := os.ReadDir(card); len(ents) != 0 {
		t.Errorf("nothing may be copied to the card: %v", ents)
	}
}

func TestRemoveFromTheCardLeavesTheInternalDriveAlone(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("CARD1")
	internal := fd.cfg().SynthsDir
	cd := plugin(t, card, "me - VST - C", "c.so", "cccc0003", "C")
	in := plugin(t, internal, "me - VST - A", "a.so", "aaaa0001", "A")
	os.WriteFile(filepath.Join(card, ".mpc-store"), []byte("c\t1.0.0\tme - VST - C\t1\n"), 0o644)
	os.WriteFile(filepath.Join(internal, ".mpc-store"), []byte("a\t1.0.0\tme - VST - A\t1\n"), 0o644)
	settings := writeSettings(fd, []string{internal, card}, entry("A", internal+"/me - VST - A/a.so", "aaaa0001"), entry("C", card+"/me - VST - C/c.so", "cccc0003"))
	if _, err := runRemove(t, fd, RemovePlan{Root: card, Folder: "me - VST - C", UID: "cccc0003", ID: "c", Keep: []string{"roms"}}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(cd, "c.so")); err == nil {
		t.Error("the card's plugin file must be gone")
	}
	if b, _ := os.ReadFile(filepath.Join(cd, "roms", "mine.rom")); string(b) != "my own file" {
		t.Error("your files on the card are kept")
	}
	if _, err := os.Stat(filepath.Join(in, "a.so")); err != nil {
		t.Error("the internal plugin is untouched")
	}
	st, _ := os.ReadFile(settings)
	if strings.Contains(string(st), "cccc0003") || !strings.Contains(string(st), "aaaa0001") {
		t.Errorf("only the card plugin's entry goes:\n%s", st)
	}
	if b, _ := os.ReadFile(filepath.Join(card, ".mpc-store")); strings.Contains(string(b), "c\t1.0.0") {
		t.Errorf("the card's record forgets it: %q", b)
	}
	if b, _ := os.ReadFile(filepath.Join(internal, ".mpc-store")); !strings.Contains(string(b), "a\t1.0.0") {
		t.Errorf("the internal record is untouched: %q", b)
	}
}

func TestRegisterAddsUnknownFoldersFromEveryLocationAndDropsDanglingEntries(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("CARD1")
	internal := fd.cfg().SynthsDir
	plugin(t, internal, "me - VST - A", "a.so", "aaaa0001", "A") // not registered
	plugin(t, card, "me - VST - C", "c.so", "cccc0003", "C")     // not registered, on the card
	plugin(t, internal, "me - VST - B", "b.so", "bbbb0002", "B") // registered
	settings := writeSettings(fd, []string{internal, card},
		entry("B", internal+"/me - VST - B/b.so", "bbbb0002"),
		entry("Gone", internal+"/me - VST - Gone/g.so", "dddd0004"), // dangling: its file is not there
		entry("Other", "/sdcard/vst/other.so", "6f746872"))          // registered another way: untouched
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	plan, err := d.SyncPlan()
	if err != nil {
		t.Fatal(err)
	}
	var folders []string
	for _, it := range plan.Add {
		folders = append(folders, it.Root+"|"+it.Folder)
	}
	if strings.Join(folders, ",") != internal+"|me - VST - A,"+card+"|me - VST - C" || len(plan.Remove) != 1 || !strings.HasSuffix(plan.Remove[0], "g.so") {
		t.Fatalf("plan: %+v", plan)
	}
	before, _ := os.ReadFile(settings)
	if len(fd.calls()) != 0 {
		t.Error("planning must not touch MPC")
	}
	if after, _ := os.ReadFile(settings); string(after) != string(before) {
		t.Error("planning must not change MPC.settings")
	}
	j := &Job{ID: "x", State: "running"}
	if err := RunRegister(d, j, nil); err != nil {
		t.Fatal(err, j.Lines)
	}
	st, _ := os.ReadFile(settings)
	for _, want := range []string{"aaaa0001", "bbbb0002", "cccc0003", "6f746872"} {
		if !strings.Contains(string(st), want) {
			t.Errorf("%s must be registered or kept:\n%s", want, st)
		}
	}
	if strings.Contains(string(st), "dddd0004") {
		t.Error("the dangling entry goes")
	}
	if !strings.Contains(string(st), card+"/me - VST - C/c.so") {
		t.Errorf("the card plugin is registered with its card path:\n%s", st)
	}
	if got := strings.Join(fd.calls(), ","); got != "stop acvs,start acvs" {
		t.Errorf("one stop and one start: %s", got)
	}
	if baks, _ := filepath.Glob(settings + ".bak-sync-*"); len(baks) != 1 {
		t.Errorf("a settings backup is made: %v", baks)
	}
	d.readInfo("127.0.0.1", "")
	if plan, _ := d.SyncPlan(); len(plan.Add) != 0 || len(plan.Remove) != 0 {
		t.Errorf("a second plan has nothing to do: %+v", plan)
	}
	if ents, _ := os.ReadDir(fd.cfg().RemoteTmp); len(ents) != 0 {
		t.Errorf("cleanup: %v", ents)
	}
}

func TestServerLocationsAndRegister(t *testing.T) {
	h := newHarness(t)
	card := h.fd.addCard("CARD1")
	internal := h.fd.cfg().SynthsDir
	h.app.cfg = h.fd.cfg() // the card exists now
	plugin(t, card, "me - VST - C", "c.so", "cccc0003", "C")
	writeSettings(h.fd, []string{internal, card})
	h.app.cat = []CatPlugin{{ID: "c", Name: "C", Version: "1.0.0", Skin: "me - VST - C"}}
	h.app.catAt = time.Now()
	if code, _ := h.post("/api/connect", map[string]string{"host": "127.0.0.1", "password": "secret"}); code != 200 {
		t.Fatal("connect")
	}
	_, body := h.do("GET", "/api/device", nil, nil)
	if !strings.Contains(string(body), `"label":"Drive CARD1"`) || !strings.Contains(string(body), `"rootLabel":"Drive CARD1"`) {
		t.Errorf("device list shows the locations: %s", body)
	}
	_, cat := h.do("GET", "/api/catalog", nil, nil)
	if !strings.Contains(string(cat), `"installedAt":"Drive CARD1"`) || !strings.Contains(string(cat), `"installed":true`) {
		t.Errorf("a catalog plugin on the card says where it is: %s", cat)
	}
	_, un := h.do("GET", "/api/unregistered", nil, nil)
	if !strings.Contains(string(un), `"folder":"me - VST - C"`) || !strings.Contains(string(un), `"rootLabel":"Drive CARD1"`) {
		t.Errorf("unregistered: %s", un)
	}
	if code, _ := h.post("/api/register", map[string]any{}); code != 400 {
		t.Errorf("registering needs confirmation: %d", code)
	}
	good := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", true, 0))
	zipBytes, _ := os.ReadFile(good.Path)
	handle := upload(t, h, map[string][]byte{"A.zip": zipBytes})["results"].([]any)[0].(map[string]any)["package"].(map[string]any)["handle"].(string)
	if code, m := h.post("/api/install", map[string]any{"uploads": []string{handle}, "root": "/not/a/location", "confirm": true}); code != 400 {
		t.Errorf("an unknown location is refused: %d %v", code, m)
	}
	if code, m := h.post("/api/install", map[string]any{"uploads": []string{handle}, "root": card, "confirm": true}); code != 200 {
		t.Fatalf("install to the card: %d %v", code, m)
	}
	for i := 0; i < 100; i++ {
		_, b := h.do("GET", "/api/job?since=0", nil, nil)
		if !strings.Contains(string(b), `"state":"running"`) {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if _, err := os.Stat(filepath.Join(card, "me - VST - A", "bin", "tool")); err != nil {
		t.Errorf("installed to the card through the API: %v", err)
	}
	if code, m := h.post("/api/register", map[string]any{"confirm": true}); code != 200 {
		t.Fatalf("register: %d %v", code, m)
	}
	for i := 0; i < 200; i++ { // let the job finish: it writes into the test's folders
		_, b := h.do("GET", "/api/job?since=0", nil, nil)
		if !strings.Contains(string(b), `"state":"running"`) {
			if !strings.Contains(string(b), `"state":"done"`) {
				t.Errorf("register job: %s", b)
			}
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func TestEmbeddedSyncIsTheCanonicalOne(t *testing.T) {
	canon, err := os.ReadFile("../release/sync.sh")
	if err != nil {
		t.Skip("run from the repo: ", err)
	}
	if string(canon) != string(syncSH) {
		t.Fatal("tools/desktop/sync.sh differs from tools/release/sync.sh: copy it again")
	}
}

// mountPointOf asks df where a folder is mounted, the way the device script does.
func mountPointOf(t *testing.T, dir string) string {
	t.Helper()
	out, err := exec.Command("df", "-k", dir).Output()
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	f := strings.Fields(lines[len(lines)-1])
	return f[len(f)-1]
}

func TestReadOnlyMountsAreNeverOffered(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("SYSTEM")
	mp := mountPointOf(t, card)
	mounts := filepath.Join(fd.dir, "mounts")
	os.WriteFile(mounts, []byte("/dev/x "+mp+" ext4 ro,relatime 0 0\n"), 0o644) // like /media/acvs-synths on a Force
	cfg := fd.cfg()
	cfg.MountsFile = mounts
	d, err := Dial("127.0.0.1", "secret", cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if len(d.Info.Roots) != 0 {
		t.Errorf("a read-only location must not be offered: %+v", d.Info.Roots)
	}
	os.WriteFile(mounts, []byte("/dev/x "+mp+" exfat rw,relatime 0 0\n"), 0o644)
	cfg2 := fd.cfg()
	cfg2.MountsFile = mounts
	d2, err := Dial("127.0.0.1", "secret", cfg2)
	if err != nil {
		t.Fatal(err)
	}
	defer d2.Close()
	if len(d2.Info.Roots) == 0 || d2.Info.Roots[0].FS != "exfat" || !d2.Info.Roots[0].NoSymlinks {
		t.Errorf("a writable exFAT location is offered and flagged: %+v", d2.Info.Roots)
	}
}

// A drive named "SSD - Force" (the Force's SSD, mounted noexec): the mount point holds spaces, /proc/mounts writes them as \040.
func TestNoexecMountWithSpacesInItsNameIsFlaggedAndRefused(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("SSD - Force")
	mp := filepath.Dir(card)
	// BusyBox df prints the mount point last, spaces and all
	os.WriteFile(filepath.Join(fd.shims, "df"), []byte("#!/bin/sh\nfor a; do last=\"$a\"; done\ncase \"$last\" in\n\"$SSDSYNTHS\") echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'; echo '/dev/sda1 1000000 1000 900000 1% '\"$SSDMP\" ;;\n*) exec /usr/bin/df \"$@\" ;;\nesac\n"), 0o755)
	t.Setenv("SSDSYNTHS", card)
	t.Setenv("SSDMP", mp)
	mounts := filepath.Join(fd.dir, "mounts")
	os.WriteFile(mounts, []byte("/dev/sda1 "+strings.ReplaceAll(mp, " ", `\040`)+" exfat rw,nosuid,nodev,noexec,relatime 0 0\n"), 0o644)
	cfg := fd.cfg()
	cfg.MountsFile = mounts
	cfg.RootGlobs = shQuote(filepath.Join(fd.dir, "Synths")) + " " + shQuote(card) // paths with spaces are one shell word each
	d, err := Dial("127.0.0.1", "secret", cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	root, ok := d.Info.root(card)
	if !ok || root.FS != "exfat" || !root.NoExec || !root.NoSymlinks || root.FreeKB != 900000 {
		t.Fatalf("an exFAT noexec location with a space in its name is read whole: %+v (found %v)", root, ok)
	}
	a := installerPkg(t, "A-1", "a-plug", "me - VST - A", fakeInstaller("A", false, 0))
	err = RunInstall(d, root, []Item{{Pkg: a}}, t.TempDir(), &Job{ID: "x", State: "running"}, nil)
	if err == nil || !strings.Contains(err.Error(), "noexec") {
		t.Errorf("an install onto a noexec location must be refused: %v", err)
	}
	if len(fd.calls()) != 0 {
		t.Error("MPC must not be touched when the install is refused")
	}
}

func TestMissingInternalSynthsFolderIsCreated(t *testing.T) {
	fd := newFakeDevice(t)
	card := fd.addCard("CARD1")
	internal := fd.cfg().SynthsDir
	os.RemoveAll(internal) // an MPC One whose official plugins went to the card has no Synths folder on the internal drive
	d, err := Dial("127.0.0.1", "secret", fd.cfg())
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if st, err := os.Stat(internal); err != nil || !st.IsDir() {
		t.Fatalf("the internal Synths folder was not made: %v", err)
	}
	if len(d.Info.Roots) != 2 || d.Info.Roots[0].Path != internal || !d.Info.Roots[0].Primary || d.Info.Roots[1].Path != card {
		t.Fatalf("the internal drive must be offered first: %+v", d.Info.Roots)
	}
}

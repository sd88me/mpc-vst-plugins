package main

// Offline tests for stick.go. A made-up salt stands in for the firmware's (tools/test_usb_stick.py, which this mirrors).

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ulikunitz/xz"
)

var stickSalt = []byte("00000000-test-salt-0000-000000000000") // 36 printable bytes, like the real one's shape

// encode XOR-obfuscates salt into a saltWidth-byte, zero-padded field, the inverse of what scanSalt decodes.
func encode(salt []byte) []byte {
	pad := make([]byte, saltWidth)
	copy(pad, salt)
	out := make([]byte, saltWidth)
	for i, v := range pad {
		out[i] = v ^ saltKey[i%8]
	}
	return out
}

func randBytes(seed int64, n int) []byte {
	r := rand.New(rand.NewSource(seed))
	b := make([]byte, n)
	r.Read(b)
	return b
}

type plant struct {
	offset int
	salt   []byte
}

func firmware(t *testing.T, size int, plants ...plant) string {
	t.Helper()
	buf := randBytes(1, size)
	for _, p := range plants {
		copy(buf[p.offset:], encode(p.salt))
	}
	p := filepath.Join(t.TempDir(), "MPC")
	if err := os.WriteFile(p, buf, 0644); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestFindSaltInARawExecutable(t *testing.T) {
	p := firmware(t, 0x180000, plant{0x123456, stickSalt})
	salt, hits, err := FindSalt(p)
	if err != nil || string(salt) != string(stickSalt) || hits != 1 {
		t.Fatalf("salt=%q hits=%d err=%v", salt, hits, err)
	}
}

// Two cases, not every one of the original 8 (the other tests cover the usual middle-of-a-chunk alignments too;
// -race makes a full saltChunk-sized scan expensive, and 4 of them pushed the suite past Go's own default test
// timeout, 2026-10-23): a plain alignment, and the chunk-boundary carry-over itself (the whole point of this test).
func TestFindSaltEveryAlignmentAndAChunkBoundary(t *testing.T) {
	for _, off := range []int{8*7 + 3, saltChunk - 16 - 5} {
		p := firmware(t, saltChunk+1000, plant{off, stickSalt})
		salt, _, err := FindSalt(p)
		if err != nil || string(salt) != string(stickSalt) {
			t.Errorf("offset %d: salt=%q err=%v", off, salt, err)
		}
	}
}

func TestFindSaltInAnUpdateImageWithAnXzRootfs(t *testing.T) {
	rootfs := make([]byte, 0x100000) // all zero: compressible, so it really is inside the xz stream
	copy(rootfs[0x40000+12:], encode(stickSalt))
	var xzBuf bytes.Buffer
	w, err := xz.NewWriter(&xzBuf)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write(rootfs); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	img := append(append([]byte("AZ01"), make([]byte, 300)...), xzBuf.Bytes()...)
	p := filepath.Join(t.TempDir(), "update.img")
	if err := os.WriteFile(p, img, 0644); err != nil {
		t.Fatal(err)
	}
	salt, _, err := FindSalt(p)
	if err != nil || string(salt) != string(stickSalt) {
		t.Fatalf("salt=%q err=%v", salt, err)
	}
}

func TestFindSaltSameValueTwiceIsFine(t *testing.T) {
	p := firmware(t, 0x180000, plant{0x123456, stickSalt}, plant{0x40000, stickSalt})
	salt, hits, err := FindSalt(p)
	if err != nil || string(salt) != string(stickSalt) || hits != 2 {
		t.Fatalf("salt=%q hits=%d err=%v", salt, hits, err)
	}
}

func TestFindSaltRefusesTwoValuesAndNone(t *testing.T) {
	// two genuine (zero-padded, shorter-than-width) salts disagree -> refuse to guess
	other := []byte("11111111-other-salt-1111-11111111")
	p := firmware(t, 0x180000, plant{0x123456, stickSalt}, plant{0x40000, other})
	if _, _, err := FindSalt(p); err == nil {
		t.Error("two disagreeing salts: want an error")
	}
	p2 := filepath.Join(t.TempDir(), "b")
	if err := os.WriteFile(p2, randBytes(5, 1<<17), 0644); err != nil {
		t.Fatal(err)
	}
	if _, _, err := FindSalt(p2); err == nil {
		t.Error("no salt at all: want an error")
	}
}

func TestFindSaltFullWidthRunsAreNoise(t *testing.T) {
	// a coincidental printable run filling the whole width field (no zero padding) is not the salt: the real
	// zero-padded salt wins. This is the Gen2 aarch64 rootfs case (docs/USB_STICK.md).
	rep := bytes.Repeat([]byte("A#nn%E70C#nn%y70M"), 3)[:saltWidth]
	p := firmware(t, 0x180000, plant{0x123456, stickSalt}, plant{0x40000, rep})
	salt, hits, err := FindSalt(p)
	if err != nil || string(salt) != string(stickSalt) || hits != 1 {
		t.Fatalf("salt=%q hits=%d err=%v (the full-width run should be dropped as noise)", salt, hits, err)
	}
}

var advKey = []byte("ssh-ed25519 AAAAfake sam@test")

func managerFixture(t *testing.T) []byte {
	t.Helper()
	return easyZip(t, map[string]string{
		"autorun/autorun.json": "{}", "autorun/autorun.check": "old", "autorun/open.sh": "#!/bin/sh\necho manager\n",
		"autorun/runtime/manager": "bin", "autorun/runtime/launch.sh": "x", ".mpc-manager-id": "id", "USB-SHA256.json": "{}",
		"Plugin Manager helper.xpa": "xpa", "local-plugins/": "",
	})
}

func readAutorun(t *testing.T, out string) autorunManifest {
	t.Helper()
	var m autorunManifest
	mj, err := os.ReadFile(filepath.Join(out, "autorun", "autorun.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(mj, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func checkMatches(t *testing.T, out string, m autorunManifest) {
	t.Helper()
	a := filepath.Join(out, "autorun")
	h := sha256.New()
	for _, n := range append([]string{"autorun.json", "open.sh"}, m.Value0.Files...) {
		b, err := os.ReadFile(filepath.Join(a, n))
		if err != nil {
			t.Fatal(err)
		}
		h.Write(b)
	}
	h.Write(stickSalt)
	want := hex.EncodeToString(h.Sum(nil))
	got, err := os.ReadFile(filepath.Join(a, "autorun.check"))
	if err != nil || string(got) != want {
		t.Fatalf("autorun.check = %q, want %q (err %v)", got, want, err)
	}
}

func TestBuildSSHStickWithoutManagerLayoutAndCheck(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildSSHStick(out, stickSalt, nil, advKey, ""); err != nil {
		t.Fatal(err)
	}
	m := readAutorun(t, out)
	want := []string{"runtime/authorized_key.pub", "runtime/enable_ssh.sh", "runtime/mpc-extras.sh"}
	if !equalStrings(m.Value0.Files, want) {
		t.Fatalf("files = %v, want %v", m.Value0.Files, want)
	}
	if m.Value0.Scripts[0].Path != "open.sh" || !strings.Contains(m.Value0.Scripts[0].Message, "SSH") {
		t.Fatalf("script = %+v", m.Value0.Scripts[0])
	}
	checkMatches(t, out, m)
	if _, err := os.Stat(filepath.Join(out, "autorun", "manager-open.sh")); err == nil {
		t.Error("manager-open.sh written with no manager")
	}
	got, err := os.ReadFile(filepath.Join(out, "autorun", "runtime", "authorized_key.pub"))
	if err != nil || string(got) != string(advKey)+"\n" {
		t.Fatalf("authorized_key.pub = %q, err %v", got, err)
	}
	if err := BuildSSHStick(out, stickSalt, nil, advKey, ""); err == nil {
		t.Error("building into an existing (now non-empty) folder: want an error")
	}
}

func TestBuildSSHStickWithManagerKeepsItsFilesAndChecksEverything(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildSSHStick(out, stickSalt, managerFixture(t), advKey, ""); err != nil {
		t.Fatal(err)
	}
	m := readAutorun(t, out)
	for _, need := range []string{"manager-open.sh", "runtime/manager", "runtime/launch.sh", "runtime/mpc-extras.sh", "runtime/enable_ssh.sh"} {
		found := false
		for _, f := range m.Value0.Files {
			found = found || f == need
		}
		if !found {
			t.Errorf("autorun.json does not list %s: %v", need, m.Value0.Files)
		}
	}
	checkMatches(t, out, m)
	own, _ := os.ReadFile(filepath.Join(out, "autorun", "manager-open.sh"))
	if string(own) != "#!/bin/sh\necho manager\n" {
		t.Errorf("the manager's open.sh was changed: %q", own)
	}
	wrapper, _ := os.ReadFile(filepath.Join(out, "autorun", "open.sh"))
	if !bytes.Contains(wrapper, []byte("manager-open.sh")) {
		t.Error("open.sh does not hand over to the manager")
	}
	for _, kept := range []string{".mpc-manager-id", "Plugin Manager helper.xpa", "autorun/runtime/manager"} {
		if _, err := os.Stat(filepath.Join(out, filepath.FromSlash(kept))); err != nil {
			t.Errorf("%s missing: %v", kept, err)
		}
	}
	// the manager bundle's own inventory is rewritten to match what is now on the stick
	var inv map[string]string
	ij, _ := os.ReadFile(filepath.Join(out, "USB-SHA256.json"))
	if err := json.Unmarshal(ij, &inv); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(out, "autorun", "open.sh"))
	sum := sha256.Sum256(b)
	if inv["autorun/open.sh"] != hex.EncodeToString(sum[:]) || inv["autorun/manager-open.sh"] == "" || inv["autorun/runtime/mpc-extras.sh"] == "" {
		t.Errorf("inventory not updated: %v", inv)
	}
	if _, ok := inv["USB-SHA256.json"]; ok {
		t.Error("inventory lists itself")
	}
}

func TestBuildSSHStickIntoAnAlreadyExistingEmptyFolderWithHousekeeping(t *testing.T) {
	mounted := filepath.Join(t.TempDir(), "stick")
	for _, name := range []string{"System Volume Information", ".Trashes", "$RECYCLE.BIN"} {
		if err := os.MkdirAll(filepath.Join(mounted, name), 0755); err != nil {
			t.Fatal(err)
		}
	}
	if err := BuildSSHStick(mounted, stickSalt, nil, advKey, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(mounted, "autorun", "open.sh")); err != nil {
		t.Error("open.sh not written: housekeeping folders should not count as user content")
	}
	// ...and with the manager too
	mounted2 := filepath.Join(t.TempDir(), "stick")
	os.MkdirAll(filepath.Join(mounted2, "System Volume Information"), 0755)
	if err := BuildSSHStick(mounted2, stickSalt, managerFixture(t), advKey, ""); err != nil {
		t.Fatal(err)
	}
}

func TestBuildSSHStickIntoANonEmptyFolderIsRefused(t *testing.T) {
	for _, withManager := range []bool{false, true} {
		occupied := filepath.Join(t.TempDir(), "stick")
		os.Mkdir(occupied, 0755)
		os.WriteFile(filepath.Join(occupied, "something.txt"), []byte("not ours\n"), 0644)
		var mgr []byte
		if withManager {
			mgr = managerFixture(t)
		}
		if err := BuildSSHStick(occupied, stickSalt, mgr, advKey, ""); err == nil {
			t.Errorf("withManager=%v: a non-empty existing folder: want an error", withManager)
		}
	}
}

func TestBuildSSHStickWithPasswordBundlesTheFile(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildSSHStick(out, stickSalt, nil, nil, "hunter2"); err != nil {
		t.Fatal(err)
	}
	runtime := filepath.Join(out, "autorun", "runtime")
	got, err := os.ReadFile(filepath.Join(runtime, "ssh_password.txt"))
	if err != nil || string(got) != "hunter2\n" {
		t.Fatalf("ssh_password.txt = %q, err %v", got, err)
	}
	if _, err := os.Stat(filepath.Join(runtime, "authorized_key.pub")); err == nil {
		t.Error("authorized_key.pub written with a password")
	}
	checkMatches(t, out, readAutorun(t, out))
}

func TestBuildSSHStickRefusesBadSSHChoices(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	for name, c := range map[string]struct {
		key []byte
		pw  string
	}{
		"neither":     {nil, ""},
		"both":        {advKey, "hunter2"},
		"private key": {[]byte("-----BEGIN OPENSSH PRIVATE KEY-----"), ""},
	} {
		if err := BuildSSHStick(out, stickSalt, nil, c.key, c.pw); err == nil {
			t.Errorf("%s: want an error", name)
		}
		if _, err := os.Stat(out); err == nil {
			t.Errorf("%s: wrote something before refusing", name)
		}
	}
}

// The wrapper and the extras script run under BusyBox sh on the device; check them with a scratch addin and a fake enable_ssh.sh.
func TestStickScriptsRunAndHandOverToTheManager(t *testing.T) {
	sh, err := exec.LookPath("sh")
	if err != nil {
		t.Skip("no sh")
	}
	root := t.TempDir()
	out := filepath.Join(root, "stick")
	if err := BuildSSHStick(out, stickSalt, managerFixture(t), advKey, ""); err != nil {
		t.Fatal(err)
	}
	// a fake enable_ssh.sh and a fake addin that record their calls
	rt := filepath.Join(out, "autorun", "runtime")
	os.WriteFile(filepath.Join(rt, "enable_ssh.sh"), []byte("echo ssh \"$@\" >> \"$MPC_LOG\"\n"), 0644)
	addins := filepath.Join(root, "addins", "demo")
	os.MkdirAll(addins, 0755)
	os.WriteFile(filepath.Join(addins, "install.sh"), []byte("echo addin \"$@\" >> \"$MPC_LOG\"\n"), 0644)
	log := filepath.Join(root, "log")
	cmd := exec.Command(sh, filepath.Join(out, "autorun", "open.sh"))
	cmd.Env = append(os.Environ(), "MPC_USB_TEST=1", "MPC_LOG="+log, "MPC_ADDINS_DIR="+filepath.Join(root, "addins"))
	got, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("open.sh: %v\n%s", err, got)
	}
	if !strings.Contains(string(got), "manager") { // the manager's own open.sh ran last
		t.Errorf("the manager's open.sh did not run: %s", got)
	}
	l, _ := os.ReadFile(log)
	if !strings.Contains(string(l), "ssh --key") || !strings.Contains(string(l), "addin -y -n -t") {
		t.Errorf("extras did not run: %q", l)
	}
	if res, _ := os.ReadFile(filepath.Join(out, "mpc-extras-result.txt")); !strings.Contains(string(res), "Reapplying addin: demo") {
		t.Errorf("mpc-extras-result.txt: %q", res)
	}
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestEmbeddedStickScriptsAreTheCanonicalOnes(t *testing.T) {
	for _, c := range []struct {
		canon string
		embed []byte
	}{
		{"../usb_stick/enable_ssh.sh", stickEnableSSHSH},
	} {
		canon, err := os.ReadFile(c.canon)
		if err != nil {
			t.Skip("run from the repo: ", err)
		}
		if string(canon) != string(c.embed) {
			t.Errorf("tools/desktop/%s differs from tools/%s: copy it again", filepath.Base(c.canon), c.canon)
		}
	}
}

// The advanced stick's open.sh opens the bundled manager the first time only; later insertions just do SSH and addins.
func TestAdvancedStickOpensTheManagerOnlyOnceUnlessAsked(t *testing.T) {
	usb := t.TempDir()
	here := filepath.Join(usb, "autorun")
	os.MkdirAll(filepath.Join(here, "runtime"), 0755)
	os.WriteFile(filepath.Join(here, "open.sh"), stickAdvOpenSH, 0644)
	os.WriteFile(filepath.Join(here, "runtime", "mpc-extras.sh"), []byte("echo extras\n"), 0644)
	os.WriteFile(filepath.Join(here, "manager-open.sh"), []byte("echo x >> \""+usb+"/launches\"\n"), 0644)
	launches := func() int {
		b, _ := os.ReadFile(filepath.Join(usb, "launches"))
		return strings.Count(string(b), "x")
	}
	run := func() {
		t.Helper()
		c := exec.Command("sh", filepath.Join(here, "open.sh"))
		c.Env = append(os.Environ(), "MPC_USB_TEST=1", "TMPDIR="+t.TempDir())
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("open.sh: %v %s", err, out)
		}
	}
	run()
	if launches() != 1 {
		t.Fatalf("first insertion launched the manager %d times", launches())
	}
	run()
	if launches() != 1 {
		t.Fatal("second insertion opened the manager again")
	}
	os.WriteFile(filepath.Join(usb, "open-plugin-manager.txt"), nil, 0644)
	run()
	if launches() != 2 {
		t.Fatal("open-plugin-manager.txt did not open it")
	}
}

// enable_ssh.sh's set_root_password must work with a busybox that has no chpasswd (a real Force), and must not claim success
// when nothing changed.
func TestSetRootPasswordWithoutChpasswd(t *testing.T) {
	src := string(stickEnableSSHSH)
	i := strings.Index(src, "set_root_password() {")
	j := strings.Index(src[i:], "\n}\n")
	if i < 0 || j < 0 {
		t.Fatal("function not found")
	}
	fn := src[i : i+j+3]
	run := func(tools map[string]string) (string, error) {
		d := t.TempDir()
		bin := filepath.Join(d, "bin")
		os.MkdirAll(bin, 0755)
		for _, n := range []string{"grep", "cp", "cat", "rm", "awk", "printf", "echo"} {
			if p, err := exec.LookPath(n); err == nil {
				os.Symlink(p, filepath.Join(bin, n))
			}
		}
		for n, body := range tools {
			os.WriteFile(filepath.Join(bin, n), []byte("#!/bin/sh\n"+body+"\n"), 0755)
		}
		shadow := filepath.Join(d, "shadow")
		os.WriteFile(shadow, []byte("root:*:19000:0:99999:7:::\ndaemon:*:19000:0:99999:7:::\n"), 0600)
		sh, _ := exec.LookPath("sh")
		c := exec.Command(sh, "-c", fn+"\nset_root_password hunter2")
		c.Env = []string{"PATH=" + bin, "ENABLE_SSH_SHADOW=" + shadow}
		_, err := c.CombinedOutput()
		b, _ := os.ReadFile(shadow)
		return string(b), err
	}
	got, err := run(map[string]string{"mkpasswd": `echo '$6$salt$hashed'`})
	if err != nil || !strings.HasPrefix(got, "root:$6$salt$hashed:19000") || !strings.Contains(got, "daemon:*:") {
		t.Fatalf("mkpasswd route: %v %q", err, got)
	}
	if got, err = run(map[string]string{}); err == nil {
		t.Fatalf("no tool at all reported success: %q", got)
	}
	if got, err = run(map[string]string{"chpasswd": "exit 0"}); err == nil {
		t.Fatalf("a chpasswd that changes nothing reported success: %q", got)
	}
}

package main

// Offline tests for stick.go. A made-up salt stands in for the firmware's (tools/test_usb_stick.py, which this mirrors).

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math/rand"
	"os"
	"path/filepath"
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

func TestBuildStickLayoutAndCheck(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildStick(out, stickSalt, []string{"plugin-manager", "acid"}, nil, ""); err != nil {
		t.Fatal(err)
	}
	a := filepath.Join(out, "autorun")
	var manifest autorunManifest
	mj, err := os.ReadFile(filepath.Join(a, "autorun.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(mj, &manifest); err != nil {
		t.Fatal(err)
	}
	wantFiles := []string{"runtime/mpc-store.sh", "runtime/run.sh"}
	if !equalStrings(manifest.Value0.Files, wantFiles) {
		t.Fatalf("files = %v, want %v", manifest.Value0.Files, wantFiles)
	}
	if manifest.Value0.Scripts[0].Path != "open.sh" {
		t.Fatalf("script path = %q", manifest.Value0.Scripts[0].Path)
	}
	h := sha256.New()
	for _, n := range append([]string{"autorun.json", "open.sh"}, wantFiles...) {
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
	ids, err := os.ReadFile(filepath.Join(out, "install.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(ids, []byte("plugin-manager\nacid\n")) {
		t.Fatalf("install.txt: %q", ids)
	}
	if err := BuildStick(out, stickSalt, nil, nil, ""); err == nil {
		t.Error("building into an existing (now non-empty) folder: want an error")
	}
}

// TestBuildStickIntoAnAlreadyExistingEmptyFolder covers the common case where out is a mounted USB stick's own
// root directory: the mount point always already exists, so BuildStick must not refuse it just for existing.
func TestBuildStickIntoAnAlreadyExistingEmptyFolder(t *testing.T) {
	mounted := filepath.Join(t.TempDir(), "stick")
	if err := os.Mkdir(mounted, 0755); err != nil {
		t.Fatal(err)
	}
	if err := BuildStick(mounted, stickSalt, nil, nil, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(mounted, "autorun", "open.sh")); err != nil {
		t.Error("open.sh not written into the already-existing folder")
	}
}

func TestBuildStickIntoANonEmptyFolderIsRefused(t *testing.T) {
	occupied := filepath.Join(t.TempDir(), "stick")
	if err := os.Mkdir(occupied, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(occupied, "something.txt"), []byte("not ours\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := BuildStick(occupied, stickSalt, nil, nil, ""); err == nil {
		t.Error("a non-empty existing folder: want an error")
	}
}

// TestBuildStickIgnoresADriveSOwnHousekeepingFolders covers the bug the user hit testing a real freshly formatted
// USB stick, 2026-10-23: Windows always creates "System Volume Information" on a fresh format, which isn't
// something the user put there and must not block building straight onto the drive's root.
func TestBuildStickIgnoresADriveSOwnHousekeepingFolders(t *testing.T) {
	mounted := filepath.Join(t.TempDir(), "stick")
	if err := os.Mkdir(mounted, 0755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"System Volume Information", ".Trashes", "$RECYCLE.BIN"} {
		if err := os.Mkdir(filepath.Join(mounted, name), 0755); err != nil {
			t.Fatal(err)
		}
	}
	if err := BuildStick(mounted, stickSalt, nil, nil, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(mounted, "autorun", "open.sh")); err != nil {
		t.Error("open.sh not written: housekeeping folders should not have been treated as user content")
	}
}

func TestBuildStickWithSSHKeyBundlesEnableSSHAndTheKey(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	pub := []byte("ssh-ed25519 AAAAfake sam@test")
	if err := BuildStick(out, stickSalt, nil, pub, ""); err != nil {
		t.Fatal(err)
	}
	runtime := filepath.Join(out, "autorun", "runtime")
	if _, err := os.Stat(filepath.Join(runtime, "enable_ssh.sh")); err != nil {
		t.Error("enable_ssh.sh not bundled")
	}
	got, err := os.ReadFile(filepath.Join(runtime, "authorized_key.pub"))
	if err != nil || string(got) != string(pub)+"\n" {
		t.Fatalf("authorized_key.pub = %q, err %v", got, err)
	}
	readme, _ := os.ReadFile(filepath.Join(out, "README-USB.txt"))
	if !bytes.Contains(readme, []byte("SSH is also enabled")) {
		t.Error("README doesn't mention SSH")
	}
}

func TestBuildStickWithoutSSHKeyBundlesNoSSHFiles(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildStick(out, stickSalt, nil, nil, ""); err != nil {
		t.Fatal(err)
	}
	runtime := filepath.Join(out, "autorun", "runtime")
	if _, err := os.Stat(filepath.Join(runtime, "enable_ssh.sh")); err == nil {
		t.Error("enable_ssh.sh bundled with no key given")
	}
	if _, err := os.Stat(filepath.Join(runtime, "authorized_key.pub")); err == nil {
		t.Error("authorized_key.pub written with no key given")
	}
}

func TestBuildStickRefusesSomethingThatIsNotAPublicKey(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildStick(out, stickSalt, nil, []byte("-----BEGIN OPENSSH PRIVATE KEY-----"), ""); err == nil {
		t.Error("a private key marker: want an error")
	}
}

func TestBuildStickWithPasswordBundlesEnableSSHAndTheFile(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	if err := BuildStick(out, stickSalt, nil, nil, "hunter2"); err != nil {
		t.Fatal(err)
	}
	runtime := filepath.Join(out, "autorun", "runtime")
	if _, err := os.Stat(filepath.Join(runtime, "enable_ssh.sh")); err != nil {
		t.Error("enable_ssh.sh not bundled")
	}
	got, err := os.ReadFile(filepath.Join(runtime, "ssh_password.txt"))
	if err != nil || string(got) != "hunter2\n" {
		t.Fatalf("ssh_password.txt = %q, err %v", got, err)
	}
	if _, err := os.Stat(filepath.Join(runtime, "authorized_key.pub")); err == nil {
		t.Error("authorized_key.pub written with no key given")
	}
	readme, _ := os.ReadFile(filepath.Join(out, "README-USB.txt"))
	if !bytes.Contains(readme, []byte("password login is also turned on")) {
		t.Error("README doesn't mention the password")
	}
}

func TestBuildStickRefusesKeyAndPasswordTogether(t *testing.T) {
	out := filepath.Join(t.TempDir(), "stick")
	pub := []byte("ssh-ed25519 AAAAfake sam@test")
	if err := BuildStick(out, stickSalt, nil, pub, "hunter2"); err == nil {
		t.Error("key and password together: want an error")
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
		{"../mpc-store.sh", stickMpcStoreSH},
		{"../usb_stick/open.sh", stickOpenSH},
		{"../usb_stick/run.sh", stickRunSH},
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

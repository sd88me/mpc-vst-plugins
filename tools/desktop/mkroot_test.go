package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A drive with no Synths folder is offered, gets one on request, and is then a plugin location; nothing else can be made.
func TestADriveWithoutSynthsGetsOne(t *testing.T) {
	fd := newFakeDevice(t)
	fd.addCard("CARD1") // already has Synths: not offered
	bare := filepath.Join(fd.dir, "Drives", "MY DRIVE")
	if err := os.MkdirAll(bare, 0o755); err != nil {
		t.Fatal(err)
	}
	writeSettings(fd, nil)
	// like a Force's /proc/mounts: the drive is a mount point of its own (exFAT, name with a space); az01-internal is MPC's /data;
	// "loose folder" is a plain folder under /media, not a mount: only the drive may be offered
	sys := filepath.Join(fd.dir, "Drives", "az01-internal")
	loose := filepath.Join(fd.dir, "Drives", "loose folder")
	os.MkdirAll(sys, 0o755)
	os.MkdirAll(loose, 0o755)
	mounts := filepath.Join(fd.dir, "mounts")
	os.WriteFile(mounts, []byte("/dev/root / ext4 rw,relatime 0 0\n"+
		"/dev/mmcblk0p8 "+sys+" ext4 rw,relatime 0 0\n"+
		"/dev/sda1 "+strings.ReplaceAll(bare, " ", `\040`)+" exfat rw,relatime,fmask=0022 0 0\n"), 0o644)
	cfg0 := fd.cfg()
	cfg0.MountsFile = mounts
	d, err := Dial("127.0.0.1", "secret", cfg0)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if len(d.Info.Drives) != 1 || d.Info.Drives[0].Path != bare || d.Info.Drives[0].Label != "Drive MY DRIVE" || d.Info.Drives[0].FS != "exfat" {
		t.Fatalf("drives offered: %+v", d.Info.Drives)
	}

	for _, bad := range []string{fd.dir, filepath.Join(fd.dir, "Drives", "CARD1"), "/etc", bare + "/../CARD1", sys, loose} {
		if err := d.MakeRoot(bad); err == nil {
			t.Fatalf("MakeRoot(%q) was accepted", bad)
		}
	}
	if err := d.MakeRoot(bare); err != nil {
		t.Fatal(err)
	}
	if st, err := os.Stat(filepath.Join(bare, "Synths")); err != nil || !st.IsDir() {
		t.Fatalf("no Synths folder made: %v", err)
	}
	if len(d.Info.Drives) != 0 {
		t.Fatalf("the drive is still offered after the rescan: %+v", d.Info.Drives)
	}

	cfg := cfg0 // a glob like the real device's "/media/*/Synths", which keeps "MY DRIVE" one word
	cfg.RootGlobs = filepath.Join(fd.dir, "Synths") + " " + filepath.Join(fd.dir, "Drives", "*", "Synths")
	d2, err := Dial("127.0.0.1", "secret", cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer d2.Close()
	found := false
	for _, r := range d2.Info.Roots {
		found = found || r.Path == filepath.Join(bare, "Synths")
	}
	if !found {
		t.Fatalf("the new folder is not a plugin location: %+v", d2.Info.Roots)
	}
}

package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/binary"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"

	"golang.org/x/crypto/ssh"
)

// fakeDevice is a tiny SSH server that runs every command with the local sh. Shim commands stand in for the device's
// uname, id, systemctl and pidof, and record what the app asked for, so the whole install path runs without hardware.
type fakeDevice struct {
	t      *testing.T
	addr   string
	dir    string // sandbox: tmp, Synths, settings and the shims live here
	shims  string
	logMu  sync.Mutex
	mpcLog string // systemctl calls, one per line
}

func newFakeDevice(t *testing.T) *fakeDevice { t.Helper(); return newFake(t, false) }

// newOpenFakeDevice: a device whose root has no password, so the "none" method logs in (some modified firmware).
func newOpenFakeDevice(t *testing.T) *fakeDevice { t.Helper(); return newFake(t, true) }

func newFake(t *testing.T, open bool) *fakeDevice {
	t.Helper()
	dir := t.TempDir()
	fd := &fakeDevice{t: t, dir: dir, shims: filepath.Join(dir, "shims"), mpcLog: filepath.Join(dir, "mpc.log")}
	os.MkdirAll(fd.shims, 0o755)
	os.MkdirAll(filepath.Join(dir, "tmp"), 0o755)
	os.MkdirAll(filepath.Join(dir, "Synths"), 0o755)
	os.MkdirAll(filepath.Join(dir, "Settings", "MPC"), 0o755)
	os.WriteFile(filepath.Join(dir, "Settings", "MPC", "MPC.settings"), []byte("<PROPERTIES/>"), 0o644)
	shim := func(name, body string) {
		os.WriteFile(filepath.Join(fd.shims, name), []byte("#!/bin/sh\n"+body+"\n"), 0o755)
	}
	shim("uname", "echo armv7l")
	shim("id", "echo 0")
	shim("pidof", "exit 1")
	// `systemctl cat <unit>` succeeds only for the unit named in the file "svc" (default acvs; Hakai uses inmusic-mpc); other calls are logged
	shim("systemctl", `if [ "$1" = cat ]; then [ "$2" = "$(cat `+filepath.Join(fd.dir, "svc")+` 2>/dev/null || echo acvs)" ]; exit; fi; echo "$1 $2" >> `+fd.mpcLog)

	_, priv, _ := ed25519.GenerateKey(rand.Reader)
	signer, _ := ssh.NewSignerFromKey(priv)
	conf := &ssh.ServerConfig{PasswordCallback: func(c ssh.ConnMetadata, pw []byte) (*ssh.Permissions, error) {
		if string(pw) == "secret" {
			return nil, nil
		}
		return nil, io.ErrUnexpectedEOF
	}, NoClientAuth: open}
	conf.AddHostKey(signer)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	fd.addr = ln.Addr().String()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go fd.serve(c, conf)
		}
	}()
	return fd
}

// addCard makes a second plugin location, like an SD card or USB drive (a "Drive CARD1" in the app), and returns its Synths folder.
func (fd *fakeDevice) addCard(name string) string {
	p := filepath.Join(fd.dir, "Drives", name, "Synths")
	os.MkdirAll(p, 0o755)
	return p
}

// addAlias makes the internal Synths folder reachable by a second path, like /sdcard and /media/az01-internal-sd on a Force.
func (fd *fakeDevice) addAlias() string {
	p := filepath.Join(fd.dir, "Aliases", "internal-again", "Synths")
	os.MkdirAll(filepath.Dir(p), 0o755)
	os.Symlink(filepath.Join(fd.dir, "Synths"), p)
	return p
}

func (fd *fakeDevice) cfg() Config {
	_, port, _ := net.SplitHostPort(fd.addr)
	roots := []string{filepath.Join(fd.dir, "Synths")}
	cards, _ := filepath.Glob(filepath.Join(fd.dir, "Drives", "*", "Synths"))
	aliases, _ := filepath.Glob(filepath.Join(fd.dir, "Aliases", "*", "Synths"))
	roots = append(append(roots, aliases...), cards...)
	return Config{Port: port, User: "root", RemoteTmp: filepath.Join(fd.dir, "tmp"), SynthsDir: filepath.Join(fd.dir, "Synths"),
		RootGlobs: strings.Join(roots, " "), MountsFile: "/proc/mounts", SettingsGlob: filepath.Join(fd.dir, "Settings", "*", "MPC.settings"),
		AddinsDir: filepath.Join(fd.dir, "addins")}
}

func (fd *fakeDevice) calls() []string {
	b, _ := os.ReadFile(fd.mpcLog)
	var out []string
	for _, l := range strings.Split(string(b), "\n") {
		if l = strings.TrimSpace(l); l != "" {
			out = append(out, l) // "stop acvs", "start acvs"
		}
	}
	return out
}

func (fd *fakeDevice) serve(nc net.Conn, conf *ssh.ServerConfig) {
	_, chans, reqs, err := ssh.NewServerConn(nc, conf)
	if err != nil {
		return
	}
	go ssh.DiscardRequests(reqs)
	for nch := range chans {
		if nch.ChannelType() != "session" {
			nch.Reject(ssh.UnknownChannelType, "no")
			continue
		}
		ch, creqs, _ := nch.Accept()
		go func() {
			defer ch.Close()
			for r := range creqs {
				if r.Type != "exec" {
					r.Reply(false, nil)
					continue
				}
				n := binary.BigEndian.Uint32(r.Payload)
				cmd := string(r.Payload[4 : 4+n])
				r.Reply(true, nil)
				c := exec.Command("sh", "-c", cmd)
				// the addin installer edits systemd units under SYSTEMD_ROOT and logs its systemctl calls instead of making them
				c.Env = append(os.Environ(), "PATH="+fd.shims+":"+os.Getenv("PATH"), "ADDIN_INSTALL_TEST=1",
					"SYSTEMD_ROOT="+filepath.Join(fd.dir, "root"), "ADDIN_TEST_LOG="+filepath.Join(fd.dir, "addin.log"))
				c.Stdin, c.Stdout, c.Stderr = ch, ch, ch.Stderr()
				code := 0
				if err := c.Run(); err != nil {
					if ee, ok := err.(*exec.ExitError); ok {
						code = ee.ExitCode()
					} else {
						code = 255
					}
				}
				ch.SendRequest("exit-status", false, ssh.Marshal(struct{ C uint32 }{uint32(code)}))
				return
			}
		}()
	}
}

func itoa(i int) string { return strconv.Itoa(i) }

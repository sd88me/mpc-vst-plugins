package main

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// An Osirus-shaped spec (the one the Osirus release declares): a 512 KB .bin that carries its version text, or an OS update .mid.
func osirusGroup() UserFileGroup {
	return UserFileGroup{Path: "osirus/roms", Label: "Virus ROMs", Rules: []UserFileRule{
		{Label: "Virus ROM", Ext: []string{".bin"}, Size: 524288, Signature: "(C)ACCESS [", Versions: []UserFileVersion{
			{Prefix: "vb", Label: "Virus B"}, {Prefix: "vc", Label: "Virus C"}, {Prefix: "v2", Label: "Virus A"}}},
		{Label: "Virus OS update (.mid)", Ext: []string{".mid"}, SizeMin: 460800, SizeMax: 614400, Header: "MThd", Unverified: true, Note: "the plugin checks it"},
	}}
}

func fakeRom(size int, ver string) []byte {
	b := bytes.Repeat([]byte{0xff}, size)
	copy(b[1000:], "(C)ACCESS [11-10-2003-12:15:42]["+ver+"]")
	return b
}

func TestUserFileRules(t *testing.T) {
	g := osirusGroup()
	mid := append([]byte("MThd"), make([]byte, 514607)...)
	for _, c := range []struct {
		name   string
		data   []byte
		status string
		label  string
	}{
		{"Access Virus C.BIN", fakeRom(524288, "vc_650b"), "ok", "Virus C"},
		{"b.bin", fakeRom(524288, "VB_490T"), "ok", "Virus B"},
		{"a.bin", fakeRom(524288, "v280g"), "ok", "Virus A"},
		{"x.bin", fakeRom(524288, "zz_1"), "bad", ""},             // a version the plugin does not know
		{"short.bin", fakeRom(1000, "vc_650b"), "bad", ""},        // wrong size
		{"noise.bin", bytes.Repeat([]byte{7}, 524288), "bad", ""}, // right size, not a Virus
		{"First_A_28.mid", mid, "maybe", "Virus OS update (.mid)"},
		{"song.mid", append([]byte("MThd"), make([]byte, 200)...), "bad", ""},
		{"notmidi.mid", bytes.Repeat([]byte{1}, 514611), "bad", ""},
		{"readme.txt", []byte("hi"), "ignored", ""},
	} {
		v := g.Validate(c.name, c.data)
		if v.Status != c.status || v.Label != c.label {
			t.Errorf("%s: got %s %q (%s), want %s %q", c.name, v.Status, v.Label, v.Message, c.status, c.label)
		}
		if c.status == "bad" && v.Message == "" {
			t.Errorf("%s: a rejected file says why", c.name)
		}
	}
	if (UserFileGroup{Path: "../x", Rules: g.Rules}).check() == nil || (UserFileGroup{Path: "osirus/roms"}).check() == nil || g.check() != nil {
		t.Error("group paths are checked like user_data, and a group needs rules")
	}
}

func uploadUserFiles(t *testing.T, h *harness, fields map[string]string, files map[string][]byte) (int, map[string]any) {
	t.Helper()
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	for k, v := range fields {
		mw.WriteField(k, v)
	}
	for name, data := range files {
		fw, _ := mw.CreateFormFile("file", name)
		fw.Write(data)
	}
	mw.Close()
	resp, out := h.do("POST", "/api/userfiles/upload", &body, map[string]string{"Content-Type": mw.FormDataContentType()})
	m := map[string]any{}
	json.Unmarshal(out, &m)
	return resp.StatusCode, m
}

func TestUploadChecksFilesAndCopiesTheGoodOnes(t *testing.T) {
	h := newHarness(t)
	syn, _ := seed(t, h.fd)
	h.app.cat = []CatPlugin{{ID: "a", Name: "A", Version: "1.0.0", Skin: "me - VST - A", UserData: []string{"roms"}, UserFiles: []UserFileGroup{osirusGroup()}}}
	h.app.catAt = time.Now()
	if code, _ := h.post("/api/connect", map[string]string{"host": "127.0.0.1", "password": "secret"}); code != 200 {
		t.Fatal("connect")
	}
	f := map[string]string{"root": syn, "folder": "me - VST - A", "group": "osirus/roms"}
	dir := filepath.Join(syn, "me - VST - A", "osirus", "roms")

	code, m := uploadUserFiles(t, h, f, map[string][]byte{"Virus C (6v6).BIN": fakeRom(524288, "vc_650b"), "junk.bin": bytes.Repeat([]byte{7}, 524288), "../../evil.bin": fakeRom(524288, "vc_650b")})
	if code != 200 {
		t.Fatalf("upload: %d %v", code, m)
	}
	if b, err := os.ReadFile(filepath.Join(dir, "Virus C (6v6).BIN")); err != nil || len(b) != 524288 {
		t.Errorf("the good ROM is on the device: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, "junk.bin")); err == nil {
		t.Error("a file that is not a Virus ROM must not be copied")
	}
	// a name with a path is reduced to its last part: it lands in the folder, never above it
	if _, err := os.Stat(filepath.Join(dir, "evil.bin")); err != nil {
		t.Errorf("evil.bin is kept as a plain name inside the folder: %v", err)
	}
	for _, p := range []string{filepath.Join(syn, "evil.bin"), filepath.Join(syn, "me - VST - A", "evil.bin"), filepath.Join(filepath.Dir(syn), "evil.bin")} {
		if _, err := os.Stat(p); err == nil {
			t.Errorf("%s: nothing leaves the folder", p)
		}
	}
	if ents, _ := os.ReadDir(dir); len(ents) != 2 {
		t.Errorf("two files and no partial ones left behind: %v", ents)
	}

	resp, out := h.do("GET", "/api/userfiles?root="+url.QueryEscape(syn)+"&folder="+url.QueryEscape("me - VST - A")+"&group="+url.QueryEscape("osirus/roms"), nil, nil)
	if resp.StatusCode != 200 || !strings.Contains(string(out), `"label":"Virus C"`) || !strings.Contains(string(out), `"ok":2`) {
		t.Errorf("the device listing checks what is there: %d %s", resp.StatusCode, out)
	}

	// refusals: another plugin's folder, a group the plugin does not declare
	if code, _ := uploadUserFiles(t, h, map[string]string{"root": syn, "folder": "me - VST - B", "group": "osirus/roms"}, map[string][]byte{"x.bin": fakeRom(524288, "vc")}); code != 400 {
		t.Errorf("an unknown plugin has no user-file folder: %d", code)
	}
	if code, _ := uploadUserFiles(t, h, map[string]string{"root": syn, "folder": "me - VST - A", "group": "../../etc"}, map[string][]byte{"x.bin": fakeRom(524288, "vc")}); code != 400 {
		t.Errorf("only a declared group is a target: %d", code)
	}

	if code, _ := h.post("/api/userfiles/delete", map[string]string{"root": syn, "folder": "me - VST - A", "group": "osirus/roms", "name": "../../x"}); code != 400 {
		t.Errorf("a path is not a file name: %d", code)
	}
	if code, _ := h.post("/api/userfiles/delete", map[string]string{"root": syn, "folder": "me - VST - A", "group": "osirus/roms", "name": "Virus C (6v6).BIN"}); code != 200 {
		t.Errorf("delete: %d", code)
	}
	if _, err := os.Stat(filepath.Join(dir, "Virus C (6v6).BIN")); err == nil {
		t.Error("the file is gone")
	}
}

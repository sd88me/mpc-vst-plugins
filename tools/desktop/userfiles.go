package main

// The user's own files (ROMs and the like) that a plugin needs but a release cannot carry. A plugin's manifest may declare them
// (`user_files`, from release.py --user-files): per group a folder inside the plugin folder and rules that say what a good file
// looks like (extension, size, a signature inside it). The app checks a file before it goes to the device, copies it into the
// folder, and lists what is there with the same checks, so a beginner sees "Virus C: OK" or "this is not a Virus ROM" instead of
// finding out when the plugin loads. The plugin reads these files when it loads; nothing here stops or starts MPC.

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"golang.org/x/crypto/ssh"
)

// UserFileRule is one kind of file a group accepts. A file matches the rule when its extension is in Ext (compared without case);
// the other fields then have to hold too.
type UserFileRule struct {
	Label     string   `json:"label"`              // what the file is, shown when it passes ("Virus ROM")
	Ext       []string `json:"ext"`                // ".bin"
	Size      int64    `json:"size,omitempty"`     // exact size in bytes
	SizeMin   int64    `json:"size_min,omitempty"` // or a range
	SizeMax   int64    `json:"size_max,omitempty"`
	Header    string   `json:"header,omitempty"`     // the file starts with this text
	HeaderHex string   `json:"header_hex,omitempty"` // or with these bytes, in hex ("c0de")
	Signature string   `json:"signature,omitempty"`  // the file contains this
	// Names: the file names this rule accepts (compared without case), for kinds the plugin tells apart only by name (two files
	// of one size). NameContains: text the name must contain. SaveAs: the name the plugin loads it by; an upload is saved under it
	// whatever the file is called on the computer, and a file already in the folder passes only under that name.
	Names        []string `json:"names,omitempty"`
	NameContains string   `json:"name_contains,omitempty"`
	SaveAs       string   `json:"save_as,omitempty"`
	// Versions: the text in the next [...] after Signature is matched by prefix, first match wins, and its label names the file.
	Versions []UserFileVersion `json:"versions,omitempty"`
	// Unverified: size and header can be checked here, the content cannot. A file that passes is listed as "looks right" with Note,
	// and the plugin has the last word when it loads.
	Unverified bool   `json:"unverified,omitempty"`
	Note       string `json:"note,omitempty"`
}

type UserFileVersion struct {
	Prefix string `json:"prefix"`
	Label  string `json:"label"`
}

// UserFileGroup is a folder of the user's files and what goes in it.
type UserFileGroup struct {
	Path        string         `json:"path"` // inside the plugin folder, the same form as user_data
	Label       string         `json:"label"`
	Description string         `json:"description,omitempty"`
	Hint        string         `json:"hint,omitempty"`
	Rules       []UserFileRule `json:"rules"`
}

// UserFileVerdict is the result of checking one file.
type UserFileVerdict struct {
	Name    string `json:"name"`
	Size    int64  `json:"size"`
	Status  string `json:"status"` // ok | maybe | bad | ignored
	Label   string `json:"label,omitempty"`
	Message string `json:"message,omitempty"`
	SaveAs  string `json:"saveAs,omitempty"` // an upload is stored under this name (the rule's save_as), "" its own
}

const (
	maxUserFile  = 64 << 20  // one file
	maxUserFiles = 128 << 20 // one upload
)

var userFileNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9 ._()+,'&-]{0,150}$`)

func (g UserFileGroup) check() error {
	if !safeRel(g.Path) {
		return fmt.Errorf("unsafe user-file folder %q", g.Path)
	}
	if len(g.Rules) == 0 {
		return fmt.Errorf("user-file group %q has no rules", g.Path)
	}
	for _, r := range g.Rules {
		if r.SaveAs != "" && (!userFileNameRe.MatchString(r.SaveAs) || !hasExt(r.SaveAs, r.Ext)) {
			return fmt.Errorf("user-file rule %q: bad save_as %q", r.Label, r.SaveAs)
		}
	}
	return nil
}

// hexBytes decodes a rule's header_hex (checked when the manifest is made); bad hex gives a header nothing matches.
func hexBytes(h string) []byte {
	b, err := hex.DecodeString(h)
	if err != nil || len(b) == 0 {
		return []byte("\x00not hex\x00")
	}
	return b
}

func hasExt(name string, exts []string) bool {
	e := strings.ToLower(path.Ext(name))
	for _, x := range exts {
		if strings.ToLower(x) == e {
			return true
		}
	}
	return false
}

// version reads the first [...] after sig in data.
func fileVersion(data []byte, sig string) (string, bool) {
	i := bytes.Index(data, []byte(sig))
	if i < 0 {
		return "", false
	}
	rest := data[i+len(sig):]
	open := bytes.IndexByte(rest, '[')
	if open < 0 {
		return "", false
	}
	closeAt := bytes.IndexByte(rest[open+1:], ']')
	if closeAt < 0 || closeAt > 64 {
		return "", false
	}
	return strings.ToLower(string(rest[open+1 : open+1+closeAt])), true
}

// Validate checks a file about to be uploaded against the group's rules; ValidateStored one already in the folder (by the
// name it has there, which must be a rule's save_as when it has one).
func (g UserFileGroup) Validate(name string, data []byte) UserFileVerdict {
	return g.validate(name, data, false)
}

func (g UserFileGroup) ValidateStored(name string, data []byte) UserFileVerdict {
	return g.validate(name, data, true)
}

// nameProblem says why name does not suit the rule ("" it does).
func (r UserFileRule) nameProblem(name string, stored bool) string {
	low := strings.ToLower(name)
	if stored && r.SaveAs != "" {
		if low != strings.ToLower(r.SaveAs) {
			return fmt.Sprintf("the plugin loads %s only as %s: delete this copy and add it again", strings.ToLower(r.Label), r.SaveAs)
		}
		return ""
	}
	if len(r.Names) > 0 {
		ok := false
		for _, n := range r.Names {
			ok = ok || low == strings.ToLower(n)
		}
		if !ok {
			return fmt.Sprintf("%s must be named %s", r.Label, strings.Join(r.Names, " or "))
		}
	}
	if r.NameContains != "" && !strings.Contains(low, strings.ToLower(r.NameContains)) {
		return fmt.Sprintf("the name of %s must contain %s: rename the file", strings.ToLower(r.Label), r.NameContains)
	}
	return ""
}

func (g UserFileGroup) validate(name string, data []byte, stored bool) UserFileVerdict {
	v := UserFileVerdict{Name: name, Size: int64(len(data))}
	var firstWhy string
	matched := false
	for _, r := range g.Rules {
		if !hasExt(name, r.Ext) {
			continue
		}
		matched = true
		size := int64(len(data))
		why := ""
		switch {
		case r.Size > 0 && size != r.Size:
			why = fmt.Sprintf("the size is %d bytes, %s needs exactly %d", size, strings.ToLower(r.Label), r.Size)
		case r.SizeMin > 0 && size < r.SizeMin, r.SizeMax > 0 && size > r.SizeMax:
			why = fmt.Sprintf("the size is %d bytes, %s is %d to %d", size, strings.ToLower(r.Label), r.SizeMin, r.SizeMax)
		case r.Header != "" && !bytes.HasPrefix(data, []byte(r.Header)), r.HeaderHex != "" && !bytes.HasPrefix(data, hexBytes(r.HeaderHex)):
			why = "this is not the right kind of file for " + strings.ToLower(r.Label)
		}
		if why == "" {
			why = r.nameProblem(name, stored)
		}
		label := r.Label
		if why == "" && r.Signature != "" {
			ver, found := fileVersion(data, r.Signature)
			if !found {
				why = "this does not look like " + strings.ToLower(r.Label) + " (its identification text is missing)"
			} else if len(r.Versions) > 0 {
				label = ""
				for _, cand := range r.Versions {
					if strings.HasPrefix(ver, strings.ToLower(cand.Prefix)) {
						label = cand.Label
						break
					}
				}
				if label == "" {
					why = fmt.Sprintf("its version %q is not one the plugin supports", ver)
				}
			}
		}
		if why != "" {
			if firstWhy == "" {
				firstWhy = why
			}
			continue
		}
		v.Label = label
		if !stored {
			v.SaveAs = r.SaveAs
		}
		if r.Unverified {
			v.Status, v.Message = "maybe", r.Note
		} else {
			v.Status = "ok"
		}
		return v
	}
	if !matched {
		v.Status, v.Message = "ignored", "not a file type this plugin uses"
		return v
	}
	v.Status, v.Message = "bad", firstWhy
	return v
}

// Summary: how many files are usable, for the line above the list.
func userFileSummary(vs []UserFileVerdict) (ok, maybe int) {
	for _, v := range vs {
		switch v.Status {
		case "ok":
			ok++
		case "maybe":
			maybe++
		}
	}
	return
}

// RunOut runs cmd on the device and returns its stdout as it is (a file's bytes), with the exit status.
func (d *Device) RunOut(cmd string) ([]byte, int, error) {
	s, err := d.conn().NewSession()
	if err != nil && d.host != "" {
		if rerr := d.reconnect(); rerr != nil {
			return nil, -1, fmt.Errorf("%v; %w", err, rerr)
		}
		s, err = d.conn().NewSession()
	}
	if err != nil {
		return nil, -1, err
	}
	defer s.Close()
	var out bytes.Buffer
	s.Stdout = &out
	err = s.Run(cmd)
	var ee *ssh.ExitError
	if errors.As(err, &ee) {
		return out.Bytes(), ee.ExitStatus(), nil
	}
	if err != nil {
		return nil, -1, err
	}
	return out.Bytes(), 0, nil
}

// userFilesDir is where a group lives on the device.
func userFilesDir(root, folder string, g UserFileGroup) string {
	return root + "/" + folder + "/" + g.Path
}

// listUserFiles reads the files of one group from the device and checks each.
func (d *Device) listUserFiles(dir string, g UserFileGroup) ([]UserFileVerdict, error) {
	out, code, err := d.RunOut(`D=` + shQuote(dir) + `; [ -d "$D" ] || exit 3; for f in "$D"/*; do [ -f "$f" ] && printf '%s\t%s\n' "$(wc -c < "$f")" "${f##*/}"; done; exit 0`)
	if err != nil {
		return nil, err
	}
	if code == 3 {
		return []UserFileVerdict{}, nil
	}
	vs := []UserFileVerdict{}
	for _, line := range strings.Split(string(out), "\n") {
		sz, name, ok := strings.Cut(strings.TrimSpace(line), "\t")
		n, perr := strconv.ParseInt(strings.TrimSpace(sz), 10, 64)
		if !ok || perr != nil || name == "" {
			continue
		}
		if !hasExtAny(name, g) || n > maxUserFile {
			status, msg := "ignored", "not a file type this plugin uses"
			if n > maxUserFile {
				status, msg = "bad", "too large"
			}
			vs = append(vs, UserFileVerdict{Name: name, Size: n, Status: status, Message: msg})
			continue
		}
		data, code, err := d.RunOut(`cat ` + shQuote(dir+"/"+name))
		if err != nil || code != 0 {
			vs = append(vs, UserFileVerdict{Name: name, Size: n, Status: "bad", Message: "could not be read on the device"})
			continue
		}
		vs = append(vs, g.ValidateStored(name, data))
	}
	sort.Slice(vs, func(i, j int) bool { return vs[i].Name < vs[j].Name })
	return vs, nil
}

func hasExtAny(name string, g UserFileGroup) bool {
	for _, r := range g.Rules {
		if hasExt(name, r.Ext) {
			return true
		}
	}
	return false
}

// userFilesTarget finds the installed plugin and group a request names. Caller holds a.mu. The request only names things; what
// the group allows comes from the catalog or the dropped zip.
func (a *App) userFilesTarget(root, folder, group string) (knownPlugin, UserFileGroup, string) {
	for _, kp := range a.classify() {
		if kp.Root != root || kp.Folder != folder {
			continue
		}
		for _, g := range kp.UserFiles {
			if g.Path == group && g.check() == nil {
				return kp, g, ""
			}
		}
		return kp, UserFileGroup{}, fmt.Sprintf("%s has no user-file folder %q", folder, group)
	}
	return knownPlugin{}, UserFileGroup{}, fmt.Sprintf("%q is not a plugin folder on the device", folder)
}

// GET /api/userfiles?root=&folder=&group= : what is in the folder now, checked.
func (a *App) userFilesList(w http.ResponseWriter, r *http.Request) {
	a.ensureCat()
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	q := r.URL.Query()
	kp, g, why := a.userFilesTarget(q.Get("root"), q.Get("folder"), q.Get("group"))
	if why != "" {
		fail(w, 400, why)
		return
	}
	vs, err := a.dev.listUserFiles(userFilesDir(kp.Root, kp.Folder, g), g)
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	ok, maybe := userFileSummary(vs)
	writeJSON(w, 200, map[string]any{"files": vs, "ok": ok, "maybe": maybe})
}

// POST /api/userfiles/upload (multipart: root, folder, group, file...) : check each file here, copy the good ones.
func (a *App) userFilesUpload(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxUserFiles+(1<<20))
	mr, err := r.MultipartReader()
	if err != nil {
		fail(w, 400, "bad request")
		return
	}
	vals := map[string]string{}
	type upFile struct {
		name string
		data []byte
	}
	var files []upFile
	for {
		part, err := mr.NextPart()
		if err == io.EOF {
			break
		}
		if err != nil {
			fail(w, 400, "the upload was cut short or is too large")
			return
		}
		if part.FileName() == "" {
			b, _ := io.ReadAll(io.LimitReader(part, 4096))
			vals[part.FormName()] = string(b)
			continue
		}
		b, err := io.ReadAll(io.LimitReader(part, maxUserFile+1))
		if err != nil {
			fail(w, 400, "the upload was cut short")
			return
		}
		files = append(files, upFile{name: path.Base(strings.ReplaceAll(part.FileName(), "\\", "/")), data: b})
	}
	a.ensureCat()
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	kp, g, why := a.userFilesTarget(vals["root"], vals["folder"], vals["group"])
	if why != "" {
		fail(w, 400, why)
		return
	}
	if len(files) == 0 {
		fail(w, 400, "no files")
		return
	}
	dir := userFilesDir(kp.Root, kp.Folder, g)
	results := []UserFileVerdict{}
	for _, f := range files {
		v := g.Validate(f.name, f.data)
		switch {
		case int64(len(f.data)) > maxUserFile:
			v = UserFileVerdict{Name: f.name, Size: int64(len(f.data)), Status: "bad", Message: "too large"}
		case !userFileNameRe.MatchString(f.name) || strings.Contains(f.name, ".."):
			v = UserFileVerdict{Name: f.name, Size: int64(len(f.data)), Status: "bad", Message: "the file name has characters the device cannot take; rename it with letters, digits, spaces and . _ - ( )"}
		}
		if v.Status == "ok" || v.Status == "maybe" {
			as := f.name
			if v.SaveAs != "" {
				as = v.SaveAs
			}
			tmp := dir + "/." + as + ".part"
			code, rerr := a.dev.Run("mkdir -p "+shQuote(dir)+" && cat > "+shQuote(tmp)+" && mv -f "+shQuote(tmp)+" "+shQuote(dir+"/"+as), bytes.NewReader(f.data), nil)
			if rerr != nil || code != 0 {
				a.dev.Run("rm -f "+shQuote(tmp), nil, nil)
				v.Status, v.Message = "bad", "could not be copied to the device"
			} else {
				v.Message = strings.TrimSpace(v.Message + " Copied to the device.")
				if as != f.name {
					v.Message += " Saved as " + as + "."
				}
			}
		}
		results = append(results, v)
	}
	writeJSON(w, 200, map[string]any{"files": results})
}

// POST /api/userfiles/delete {root, folder, group, name}
func (a *App) userFilesDelete(w http.ResponseWriter, r *http.Request) {
	if !postOnly(w, r) {
		return
	}
	var in struct{ Root, Folder, Group, Name string }
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&in); err != nil {
		fail(w, 400, "bad request")
		return
	}
	a.ensureCat()
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.dev == nil {
		fail(w, 400, "connect to the device first")
		return
	}
	kp, g, why := a.userFilesTarget(in.Root, in.Folder, in.Group)
	if why != "" {
		fail(w, 400, why)
		return
	}
	if in.Name == "" || strings.ContainsAny(in.Name, "/\\\x00") || in.Name == "." || in.Name == ".." {
		fail(w, 400, "bad file name")
		return
	}
	code, err := a.dev.Run("rm -f "+shQuote(userFilesDir(kp.Root, kp.Folder, g)+"/"+in.Name), nil, nil)
	if err != nil || code != 0 {
		fail(w, 500, "could not delete the file")
		return
	}
	writeJSON(w, 200, map[string]any{"deleted": in.Name})
}

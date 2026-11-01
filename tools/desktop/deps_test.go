package main

import (
	"strings"
	"testing"
)

func depCatalog(t *testing.T) []CatPlugin {
	h := strings.Repeat("a", 64)
	ver := func(v, extra string) string {
		return `{"version":"` + v + `","size":1,"sha256":"` + h + `","url":"https://example.com/` + v + `.zip","channel":"stable","yanked":false,"manifest":{"skin":"s"}` + extra + `}`
	}
	raw := `{"schema":1,"plugins":[
 {"id":"base","name":"Base","author":"me","kind":"instrument","summary":"s","distribution":"release","latest":"2.0.0","versions":[` +
		ver("2.0.0", "") + `,` + ver("1.0.0", "") + `]},
 {"id":"fx","name":"Fx","author":"me","kind":"effect","summary":"s","distribution":"release","latest":"1.1.0","versions":[` +
		ver("1.1.0", `,"depends":[{"id":"base","rules":[[">=","2.0.0"]],"pick":{"armv7":"2.0.0","aarch64":"2.0.0"}}]`) + `,` +
		ver("1.0.0", `,"depends":[{"id":"base","rules":[["<","2.0.0"]],"pick":{"armv7":"1.0.0","aarch64":"1.0.0"}}]`) + `]},
 {"id":"rival","name":"Rival","author":"me","kind":"effect","summary":"s","distribution":"release","latest":"1.0.0","versions":[` +
		ver("1.0.0", `,"conflicts":["fx"]`) + `]}]}`
	cat, err := parseCatalog([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	return cat
}

func catByID(cat []CatPlugin, id string) CatPlugin {
	c, _ := findVersion(cat, id, "")
	return c
}

func TestParseCatalogKeepsOlderVersionsAndDependencies(t *testing.T) {
	cat := depCatalog(t)
	fx := catByID(cat, "fx")
	if fx.Version != "1.1.0" || len(fx.Depends) != 1 || fx.Depends[0].Pick["armv7"] != "2.0.0" || fx.Depends[0].rulesText() != ">=2.0.0" {
		t.Fatalf("latest fx: %+v", fx)
	}
	if old, ok := findVersion(cat, "fx", "1.0.0"); !ok || old.Depends[0].Rules[0] != [2]string{"<", "2.0.0"} {
		t.Errorf("older fx not kept: %+v", old)
	}
	if len(cat) != 3 {
		t.Errorf("one row per plugin, got %d", len(cat))
	}
}

func TestSatisfies(t *testing.T) {
	for _, c := range []struct {
		v     string
		rules [][2]string
		want  bool
	}{
		{"1.2.0", nil, true},
		{"1.2.0", [][2]string{{">=", "1.0.0"}, {"<", "2.0.0"}}, true},
		{"2.0.0", [][2]string{{">=", "1.0.0"}, {"<", "2.0.0"}}, false},
		{"1.10.0", [][2]string{{">", "1.9.0"}}, true},
		{"1.2.0", [][2]string{{"=", "1.2.0"}}, true},
		{"1.2.1", [][2]string{{"<=", "1.2.0"}}, false},
	} {
		if got := satisfies(c.v, c.rules); got != c.want {
			t.Errorf("satisfies(%s, %v) = %v", c.v, c.rules, got)
		}
	}
}

func TestResolveDepsAddsUpgradesAndRefuses(t *testing.T) {
	cat := depCatalog(t)
	fx := catByID(cat, "fx")

	r := resolveDeps(cat, map[string]string{}, []CatPlugin{fx}, "armv7")
	if len(r.Items) != 2 || r.Items[1].ID != "base" || r.Items[1].Version != "2.0.0" || r.Added["base"] != "needed by Fx" || len(r.Refused) != 0 {
		t.Errorf("missing dependency not added: %+v", r)
	}
	r = resolveDeps(cat, map[string]string{"base": "2.0.0"}, []CatPlugin{fx}, "armv7")
	if len(r.Items) != 1 || len(r.Refused) != 0 {
		t.Errorf("a dependency that fits is left alone: %+v", r)
	}
	r = resolveDeps(cat, map[string]string{"base": "1.0.0"}, []CatPlugin{fx}, "aarch64")
	if len(r.Items) != 2 || r.Added["base"] != "needed by Fx (replaces 1.0.0)" {
		t.Errorf("too-old dependency not upgraded: %+v", r)
	}
	// 1.0.0 -> 2.0.0 is a major change: refused unless forced, as mpc-store.sh's --major rule
	if len(r.Refused) != 1 || r.Refused[0] != "Fx would update base to 2.0.0, a major change (saved projects using it will change)" {
		t.Errorf("major update of a dependency not refused: %+v", r.Refused)
	}
	other := catByID(cat, "rival")
	other.ID, other.Name = "aaa", "Aaa"
	two := append(append([]CatPlugin{}, cat...), other)
	for i := 0; i < 20; i++ { // map order is random: the refusals still come out in id order
		r = resolveDeps(two, map[string]string{"base": "2.0.0", "rival": "1.0.0", "aaa": "1.0.0"}, []CatPlugin{fx}, "armv7")
		if len(r.Refused) != 2 || r.Refused[0] != "Aaa (installed) conflicts with Fx" {
			t.Fatalf("refusals not in id order: %+v", r.Refused)
		}
	}
	r = resolveDeps(cat, map[string]string{"base": "3.0.0"}, []CatPlugin{mustVersion(t, cat, "fx", "1.0.0")}, "armv7")
	if len(r.Refused) != 1 || !strings.Contains(r.Refused[0], "back from 3.0.0 to 1.0.0") {
		t.Errorf("downgrade not refused: %+v", r.Refused)
	}
	r = resolveDeps(cat, map[string]string{"base": "?"}, []CatPlugin{fx}, "armv7")
	if len(r.Items) != 1 || len(r.Notes) != 1 || len(r.Refused) != 0 {
		t.Errorf("unknown installed version is left as it is, with a note: %+v", r)
	}
	noPick := fx
	noPick.Depends = []Dep{{ID: "base", Rules: [][2]string{{">=", "2.0.0"}}, Pick: map[string]string{"armv7": "2.0.0"}}}
	r = resolveDeps(cat, map[string]string{}, []CatPlugin{noPick}, "aarch64")
	if len(r.Refused) != 1 || !strings.Contains(r.Refused[0], "no build of it for this device") {
		t.Errorf("no build for the device not refused: %+v", r.Refused)
	}
}

func mustVersion(t *testing.T, cat []CatPlugin, id, v string) CatPlugin {
	c, ok := findVersion(cat, id, v)
	if !ok {
		t.Fatalf("%s %s not in the catalog", id, v)
	}
	return c
}

func TestResolveDepsKeepsInstalledDependentsWorking(t *testing.T) {
	cat := depCatalog(t)
	base2 := catByID(cat, "base")
	// Fx 1.0.0 needs Base <2.0.0; installing Base 2.0.0 updates Fx to 1.1.0, which fits it.
	r := resolveDeps(cat, map[string]string{"fx": "1.0.0", "base": "1.0.0"}, []CatPlugin{base2}, "armv7")
	if len(r.Items) != 2 || r.Items[1].ID != "fx" || r.Items[1].Version != "1.1.0" || !strings.HasPrefix(r.Added["fx"], "updated, because Fx 1.0.0 needs base <2.0.0") || len(r.Refused) != 0 {
		t.Errorf("installed dependent not updated: %+v", r)
	}
	// When Fx is already the newest and still doesn't fit, the install is refused.
	base1 := mustVersion(t, cat, "base", "1.0.0")
	r = resolveDeps(cat, map[string]string{"fx": "1.1.0", "base": "2.0.0"}, []CatPlugin{base1}, "armv7")
	if len(r.Refused) != 1 || !strings.Contains(r.Refused[0], "Fx 1.1.0 is installed and needs base >=2.0.0") {
		t.Errorf("breaking an installed dependent not refused: %+v", r.Refused)
	}
}

func TestResolveDepsRefusesConflictsBothWays(t *testing.T) {
	cat := depCatalog(t)
	rival := catByID(cat, "rival")
	if r := resolveDeps(cat, map[string]string{"fx": "1.1.0", "base": "2.0.0"}, []CatPlugin{rival}, "armv7"); len(r.Refused) != 1 || r.Refused[0] != "Rival conflicts with Fx" {
		t.Errorf("declared conflict with an installed plugin: %+v", r.Refused)
	}
	if r := resolveDeps(cat, map[string]string{"rival": "1.0.0", "base": "2.0.0"}, []CatPlugin{catByID(cat, "fx")}, "armv7"); len(r.Refused) != 1 || r.Refused[0] != "Rival (installed) conflicts with Fx" {
		t.Errorf("conflict declared by the installed side: %+v", r.Refused)
	}
}

func TestRemovalRefusals(t *testing.T) {
	cat := depCatalog(t)
	inst := map[string]string{"fx": "1.1.0", "base": "2.0.0"}
	if r := removalRefusals(cat, inst, map[string]bool{"base": true}); len(r) != 1 || !strings.HasPrefix(r[0], "Fx is installed and needs base") {
		t.Errorf("removing a dependency not refused: %v", r)
	}
	if r := removalRefusals(cat, inst, map[string]bool{"base": true, "fx": true}); len(r) != 0 {
		t.Errorf("removing both is fine: %v", r)
	}
}

package main

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Dependencies and conflicts between catalog plugins (docs/CATALOG_SPEC.md, "Dependencies"). catalog_build.py resolves each
// dependency to rules and a pick per device generation; this applies them the same way as mpc-store.sh's resolve(), so the app and
// the shell installer agree.

// Dep is one dependency of a catalog version: another plugin's id, the rules its version must meet ([op, X.Y.Z], all of them), and
// the version to install when the device has none that fits, per arch ("armv7", "aarch64").
type Dep struct {
	ID    string            `json:"id"`
	Rules [][2]string       `json:"rules"`
	Pick  map[string]string `json:"pick"`
}

func (d Dep) rulesText() string {
	if len(d.Rules) == 0 {
		return "any version"
	}
	var s []string
	for _, r := range d.Rules {
		s = append(s, r[0]+r[1])
	}
	return strings.Join(s, ",")
}

func vkey(v string) [3]int {
	var k [3]int
	for i, p := range strings.SplitN(v, ".", 3) {
		k[i], _ = strconv.Atoi(p)
	}
	return k
}

func vcmp(a, b string) int {
	x, y := vkey(a), vkey(b)
	for i := range x {
		if x[i] != y[i] {
			if x[i] > y[i] {
				return 1
			}
			return -1
		}
	}
	return 0
}

// satisfies says whether version v meets every rule.
func satisfies(v string, rules [][2]string) bool {
	for _, r := range rules {
		c := vcmp(v, r[1])
		ok := map[string]bool{">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "=": c == 0}[r[0]]
		if !ok {
			return false
		}
	}
	return true
}

func archKey(arch string) string {
	if arch == "aarch64" {
		return "aarch64"
	}
	return "armv7"
}

// Resolution is a batch after its dependencies: the plugins to install (what was asked first, then what it needs), why each added
// one is there, and what the install would break (refused unless forced).
type Resolution struct {
	Items   []CatPlugin
	Added   map[string]string // plugin id -> why it was added
	Refused []string
	Notes   []string
}

// findVersion is a plugin's listed version (the newest when version is "").
func findVersion(cat []CatPlugin, id, version string) (CatPlugin, bool) {
	for _, c := range cat {
		if c.ID != id {
			continue
		}
		if version == "" || version == c.Version {
			return c, true
		}
		for _, o := range c.versions {
			if o.Version == version {
				return o, true
			}
		}
	}
	return CatPlugin{}, false
}

// installedRow is the catalog's record of the version a device has (the newest when that version is no longer listed).
func installedRow(cat []CatPlugin, id, version string) (CatPlugin, bool) {
	if c, ok := findVersion(cat, id, version); ok && version != "" && version != "?" {
		return c, true
	}
	return findVersion(cat, id, "")
}

// resolveDeps grows a batch until everything in it, and everything installed that stays, has what it needs. installed: plugin id ->
// version, "?" when the plugin's folder is there but no version was recorded. arch: the device's `uname -m`.
func resolveDeps(cat []CatPlugin, installed map[string]string, want []CatPlugin, arch string) Resolution {
	res := Resolution{Added: map[string]string{}}
	plan := map[string]int{} // id -> index in res.Items
	for _, w := range want {
		if _, ok := plan[w.ID]; !ok {
			plan[w.ID] = len(res.Items)
			res.Items = append(res.Items, w)
		}
	}
	refused := map[string]bool{}
	refuse := func(s string) {
		if !refused[s] {
			refused[s] = true
			res.Refused = append(res.Refused, s)
		}
	}
	// An installed plugin replaced for a dependency keeps mpc-store.sh update's --major rule: a new major version (param_compat)
	// changes saved projects, so it is refused unless forced.
	major := func(who, id, cur, to string) {
		if cur != "" && cur != "?" && vkey(cur)[0] != vkey(to)[0] {
			refuse(fmt.Sprintf("%s would update %s to %s, a major change (saved projects using it will change)", who, id, to))
		}
	}
	add := func(c CatPlugin, why string) {
		plan[c.ID] = len(res.Items)
		res.Items = append(res.Items, c)
		res.Added[c.ID] = why
	}
	ids := make([]string, 0, len(installed))
	for id := range installed {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for pass := 0; pass < 50; pass++ {
		added := false
		for i := 0; i < len(res.Items); i++ { // what the batch needs
			it := res.Items[i]
			for _, d := range it.Depends {
				if j, ok := plan[d.ID]; ok {
					if !satisfies(res.Items[j].Version, d.Rules) {
						refuse(fmt.Sprintf("%s needs %s %s, but this batch installs %s %s", it.Name, d.ID, d.rulesText(), d.ID, res.Items[j].Version))
					}
					continue
				}
				cur := installed[d.ID]
				if cur == "?" {
					res.Notes = append(res.Notes, fmt.Sprintf("%s needs %s (%s); its folder is there but no version was recorded, so it is left as it is", it.Name, d.ID, d.rulesText()))
					continue
				}
				if cur != "" && satisfies(cur, d.Rules) {
					continue
				}
				pick := d.Pick[archKey(arch)]
				if pick == "" {
					refuse(fmt.Sprintf("%s needs %s (%s), and the catalog has no build of it for this device", it.Name, d.ID, d.rulesText()))
					continue
				}
				if cur != "" && vcmp(cur, pick) > 0 {
					refuse(fmt.Sprintf("%s needs %s %s: that would take %s back from %s to %s", it.Name, d.ID, d.rulesText(), d.ID, cur, pick))
					continue
				}
				c, ok := findVersion(cat, d.ID, pick)
				if !ok {
					refuse(fmt.Sprintf("%s needs %s %s, which is not in the catalog any more", it.Name, d.ID, pick))
					continue
				}
				major(it.Name, d.ID, cur, pick)
				why := "needed by " + it.Name
				if cur != "" {
					why += " (replaces " + cur + ")"
				}
				add(c, why)
				added = true
			}
		}
		for _, id := range ids { // what is installed and stays: does the batch still fit it?
			if _, ok := plan[id]; ok {
				continue
			}
			ir, ok := installedRow(cat, id, installed[id])
			if !ok {
				continue
			}
			for _, d := range ir.Depends {
				j, ok := plan[d.ID]
				if !ok || satisfies(res.Items[j].Version, d.Rules) {
					continue
				}
				pv := res.Items[j].Version
				if lr, ok := findVersion(cat, id, ""); ok && lr.Version != installed[id] && lr.fits(d.ID, pv) {
					major("installing "+d.ID+" "+pv, id, installed[id], lr.Version)
					add(lr, fmt.Sprintf("updated, because %s %s needs %s %s", ir.Name, installed[id], d.ID, d.rulesText()))
					added = true
				} else {
					refuse(fmt.Sprintf("%s %s is installed and needs %s %s, but this batch installs %s %s", ir.Name, installed[id], d.ID, d.rulesText(), d.ID, pv))
				}
				break
			}
		}
		if !added {
			break
		}
	}
	for _, it := range res.Items { // conflicts, declared by either side
		for _, c := range it.Conflicts {
			if _, ok := plan[c]; ok || installed[c] != "" {
				refuse(fmt.Sprintf("%s conflicts with %s", it.Name, nameOf(cat, c)))
			}
		}
		for _, id := range ids {
			if _, ok := plan[id]; ok {
				continue
			}
			if ir, ok := installedRow(cat, id, installed[id]); ok {
				for _, c := range ir.Conflicts {
					if c == it.ID {
						refuse(fmt.Sprintf("%s (installed) conflicts with %s", ir.Name, it.Name))
					}
				}
			}
		}
	}
	return res
}

// nameOf is a catalog id's display name (the id itself when the catalog doesn't list it).
func nameOf(cat []CatPlugin, id string) string {
	if c, ok := findVersion(cat, id, ""); ok {
		return c.Name
	}
	return id
}

// fits says whether this version's rule for dependency id (if any) accepts version v.
func (c CatPlugin) fits(id, v string) bool {
	for _, d := range c.Depends {
		if d.ID == id {
			return satisfies(v, d.Rules)
		}
	}
	return true
}

// removalRefusals lists the installed plugins that stay but need one of the ones being removed.
func removalRefusals(cat []CatPlugin, installed map[string]string, removing map[string]bool) []string {
	var out []string
	ids := make([]string, 0, len(installed))
	for id := range installed {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		if removing[id] {
			continue
		}
		if ir, ok := installedRow(cat, id, installed[id]); ok {
			for _, d := range ir.Depends {
				if removing[d.ID] {
					out = append(out, fmt.Sprintf("%s is installed and needs %s: remove %s too, or keep %s", ir.Name, d.ID, ir.Name, d.ID))
				}
			}
		}
	}
	return out
}

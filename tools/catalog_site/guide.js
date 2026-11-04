/* Install page guide: the desktop installer's questions (model, MPC OS), then the steps for this MPC with the download it needs.
   Runs only on a page with the guide block (catalog_md "::: guide"). Everything it says is also in the page below it. */
(function () {
  var root = document.getElementById("guide");
  if (!root) return;
  var REL = "https://github.com/open-mpc/mpc-vst-plugins/releases";
  var HERE = "on your computer", MPC = "on the MPC";
  var GROUPS = [["Gen1", 1, ["MPC Live / Live II", "MPC One / One+", "MPC X / X SE", "MPC Key 61 / Key 37", "Akai Force"]],
                ["Gen2", 2, ["MPC Live III", "MPC One G2", "MPC Key G2", "MPC XL"]]];
  var S = {}, hist = [];

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
  function link(text, href, cls) { var a = el("a", cls, text); a.href = href; return a; }
  function opt(title, sub, fn) {
    var b = el("button", "gopt"); b.type = "button";
    var s = el("span"); s.appendChild(el("b", null, title)); if (sub) s.appendChild(el("small", null, sub));
    b.appendChild(s); b.onclick = function () { hist.push(JSON.stringify(S)); fn(); draw(); }; return b;
  }
  function computer() {
    var u = navigator.userAgent;
    if (/Windows/.test(u)) return ["Windows", "-windows.zip"];
    if (/Mac OS X/.test(u)) return ["Mac", "-mac-apple-silicon.tar.gz (Apple chip) or -mac-intel.tar.gz (Intel)"];
    if (/Linux/.test(u) && !/Android/.test(u)) return ["Linux", "-linux.tar.gz"];
    return null;
  }
  function parts(li, p) { (typeof p === "string" ? [p] : p).forEach(function (x) { li.appendChild(typeof x === "string" ? document.createTextNode(x) : x); }); }
  function plan(list) {   /* [[text or parts, where, what happens next], ...] as the installer's numbered steps */
    var ol = el("ol", "gplan");
    list.forEach(function (s) { var li = el("li"), sp = el("span"); parts(sp, s[0]); if (s[2]) sp.appendChild(el("em", "gthen", s[2])); li.appendChild(sp); if (s[1]) li.appendChild(el("small", null, s[1])); ol.appendChild(li); });
    return ol;
  }
  function card(step, of, q, sub) {
    var c = el("section", "gcard"), dots = el("div", "gdots");
    for (var i = 1; i <= of; i++) dots.appendChild(el("i", i <= step ? "on" : null));
    c.appendChild(dots); c.appendChild(el("h2", "gq", q)); if (sub) c.appendChild(el("p", "gsub", sub));
    return c;
  }
  function nav(c) {
    var n = el("div", "gnav");
    if (hist.length) { var b = el("button", "gback", "Back"); b.type = "button"; b.onclick = function () { S = JSON.parse(hist.pop()); draw(); }; n.appendChild(b); }
    if (S.model) n.appendChild(el("span", "gfor", S.model + (S.os ? " · MPC OS " + (S.os === "310" ? "3.10" : S.os === "2x" ? "2.x" : "3.0 to 3.9.1") : "")));
    c.appendChild(n);
  }
  function installer(c, why) {
    var b = el("div", "gdl"), k = computer();
    b.appendChild(link("Download the desktop installer app", REL + "/latest", "gbtn"));
    var p = el("p", "gsub", why + " " + (k ? "For " + k[0] + ", get the file ending in " + k[1] + ". " : "") + "Unpack it and double-click mpc-installer. ");
    p.appendChild(link("How to start it", "#the-desktop-installer-app")); b.appendChild(p); c.appendChild(b);
  }

  var EASY = /*EASY_PIN*/null;
  var DL = null;   /* dl/downloads.json: the files this site publishes (tools/site_downloads.py); none on a local preview */
  /* The write box: with a file on this site, one button (choose the drive; the page downloads and writes). Otherwise, or as a
     fallback, choose a zip you downloaded, then the drive. run(file, root, progress) resolves to the message to show. */
  function writer(c, title, dl, zipName, hint, run) {
    var box = el("div", "gwrite");
    box.appendChild(el("b", null, title));
    if (typeof DriveWrite === "undefined" || !DriveWrite.supported()) {
      var brave = navigator.brave && typeof navigator.brave.isBrave === "function";
      var m = el("p", "gsub", brave ? "Brave turns this off. To use it, open " : "Writing from this page needs Chrome or Edge on a computer. Use one of the ways below instead.");
      if (brave) { m.appendChild(el("code", null, "brave://flags/#file-system-access-api")); m.appendChild(document.createTextNode(", set it to Enabled and relaunch Brave. Or use one of the ways below.")); }
      box.appendChild(m);
      c.appendChild(box); return;
    }
    var st = el("p", "gstatus");
    function go(getFile, btns) {
      DriveWrite.pick().then(function (root) {
        btns.forEach(function (b) { b.disabled = true; });
        st.className = "gstatus"; st.textContent = "Getting the files…";
        return getFile(function (d, n) { st.textContent = "Downloading: " + Math.round(d / 1048576) + (n ? " of " + Math.round(n / 1048576) : "") + " MB"; }).then(function (file) {
          st.textContent = "Writing to " + root.name + "…";
          return run(file, root, function (d, n) { st.textContent = "Writing to " + root.name + ": " + d + " of " + n + " files"; });
        }).then(function (msg) { st.className = "gstatus ok"; st.textContent = msg + " Eject the drive before you unplug it."; });
      }).catch(function (e) {
        if (e && e.name === "AbortError") return;
        st.className = "gstatus bad"; st.textContent = (e && e.message) || String(e);
      }).then(function () { btns.forEach(function (b) { b.disabled = b.dataset.need === "file" && !f; }); });
    }
    var f = null, row = el("div", "gwrow"), all = [];
    box.appendChild(el("p", "gsub", hint));
    if (dl) {
      var one = el("button", "gbtn", "Choose the drive and write"); one.type = "button"; all.push(one);
      one.onclick = function () { go(function (p) { return DriveWrite.download(dl.path, p); }, all); };
      row.appendChild(one); box.appendChild(row);
    }
    var inp = el("input"); inp.type = "file"; inp.accept = ".zip"; inp.hidden = true;
    var pz = el("button", "gback", "1. Choose the downloaded " + zipName), pd = el("button", dl ? "gback" : "gbtn", "2. Choose the drive and write");
    pz.type = pd.type = "button"; pd.disabled = true; pd.dataset.need = "file"; all.push(pd);
    inp.onchange = function () { f = inp.files[0] || null; pd.disabled = !f; st.className = "gstatus"; st.textContent = f ? "Zip: " + f.name : ""; };
    pz.onclick = function () { inp.click(); };
    pd.onclick = function () { go(function () { return Promise.resolve(f); }, all); };
    var r2 = el("div", "gwrow"); r2.appendChild(pz); r2.appendChild(pd); r2.appendChild(inp);
    if (dl) { var fb = el("details", "gothers"); fb.appendChild(el("summary", null, "Or use a zip you downloaded")); fb.appendChild(r2); box.appendChild(fb); }
    else box.appendChild(r2);
    box.appendChild(st); c.appendChild(box);
  }

  function draw() {
    root.textContent = "";
    var c;
    if (!S.model) {
      c = card(1, 3, "Which MPC do you have?", "A couple of questions, then the steps for your MPC.");
      GROUPS.forEach(function (g) {
        c.appendChild(el("div", "ggrp", g[0]));
        var m = el("div", "gmodels");
        g[2].forEach(function (name) { m.appendChild(opt(name, "", function () { S.model = name; S.gen = g[1]; S.force = /Force/.test(name); })); });
        c.appendChild(m);
      });
    } else if (!S.os) {
      c = card(2, 3, "Which MPC OS is on it?", "On the MPC: Menu > Preferences > Info shows the version.");
      var o = el("div", "gopts");
      o.appendChild(opt("3.0 to 3.9.1", "Recommended", function () { S.os = "old"; }));
      o.appendChild(opt("3.10", "Beta support", function () { S.os = "310"; }));
      if (S.gen !== 2) o.appendChild(opt("2.x", "", function () { S.os = "2x"; }));   /* Gen2 MPCs shipped with 3.x */
      c.appendChild(o);
    } else if (S.os === "2x") {
      c = card(3, 3, "MPC OS 2.x: install over SSH", "The Plugin Manager and its stick need MPC OS 3.x. On 2.x you install plugins over SSH (root SSH access to the MPC).");
      c.appendChild(plan([["In the catalog, pick plugins whose card says MPC OS: 2.x and 3.x", HERE, "Plugins made only for 3.x don't show their screen on 2.x."],
        ["Install them with the desktop installer app over Wi-Fi: Connect with the MPC's IP address and pick plugins", HERE, "It warns you before installing a plugin made only for 3.x. MPC restarts once."]]));
      installer(c, "The desktop installer app installs over SSH.");
      var x2 = el("p", "gsub", "Or update the MPC to MPC OS 3.x first, or install by hand: ");
      x2.appendChild(link("MPC OS 2.x", "#mpc-os-2-x")); c.appendChild(x2);
    } else if (S.os === "310") {
      c = card(3, 3, "MPC OS 3.10: beta support", "The Plugin Manager works on 3.10, but installing it there is still in beta. For now, the recommended way is to install it on MPC OS 3.9.1 first, then update the MPC to 3.10: the Plugin Manager and your plugins stay installed.");
      c.appendChild(plan([["Install MPC OS 3.9.1 on the MPC (Akai's update, from akaipro.com)", MPC, "Your projects and samples stay where they are."],
        ["Install the Plugin Manager with the 3.9.1 stick (next step)", MPC, "MPC restarts with the Plugin Manager."],
        ["Update the MPC to 3.10 again", MPC, "The Plugin Manager and the plugins it installed are still there."]]));
      var t = el("div", "gopts"); t.appendChild(opt("Show the 3.9.1 steps", "Recommended", function () { S.os = "old"; })); c.appendChild(t);
      var b3 = el("details", "gothers"); b3.appendChild(el("summary", null, "Stay on 3.10 (beta)"));
      installer(b3, "The desktop installer app's Plugin manager stick also works on 3.10 (beta)."); c.appendChild(b3);
    } else {
      c = card(3, 3, "Plugin Manager stick", "A stick that installs the Plugin Manager: you confirm one prompt and MPC restarts with it.");
      if (EASY) {
        if (!(DL && DL["pm-stick"])) { var dl = el("div", "gdl"); dl.appendChild(link("Download the Plugin Manager stick zip (" + EASY.version + ")", EASY.url, "gbtn")); c.appendChild(dl); }
        writer(c, "Write the stick from this page (Chrome or Edge)", DL && DL["pm-stick"], "stick zip", "Use an empty, freshly formatted USB stick, then choose it.",
          function (file, root, prog) { return DriveWrite.stickZip(file, root, EASY, prog).then(function (n) { return "Done: the stick is ready (" + n + " files). Now do step 1 below."; }); });
        c.appendChild(plan([["Save your project, plug the stick into the MPC and choose Open on the prompt", MPC, "The stick installs the Plugin Manager and MPC restarts by itself. You can then unplug the stick."],
          ["Create a new Plugin track, tap its plugin slot and choose OpenMPC Plugin Manager G2 from the plugin list", MPC, "Its screen lists the catalog. Install from there, or open the web address on its status line on your phone or computer (same Wi-Fi)."]]));
        var o2 = el("details", "gothers"); o2.appendChild(el("summary", null, "Other browser, or rather use the desktop app?"));
        installer(o2, "The desktop installer app makes the same stick."); c.appendChild(o2);
      }
      else installer(c, "On 3.9.1 or earlier the desktop installer app makes the stick.");
      if (!EASY) c.appendChild(plan([["Start the app, open Plugin manager stick and write it to an empty USB stick", HERE],
        ["Save your project, plug the stick into the MPC and choose Open on the prompt", MPC, "The stick installs the Plugin Manager and MPC restarts by itself. You can then unplug the stick."],
        ["Create a new Plugin track, tap its plugin slot and choose OpenMPC Plugin Manager G2 from the plugin list", MPC, "Its screen lists the catalog. Install from there, or open the web address on its status line on your phone or computer (same Wi-Fi)."]]));
      var adv = el("p", "gsub", "With root SSH the same app also installs over Wi-Fi, removes plugins, and manages backups and patches: ");
      adv.appendChild(link("details", "#installing-over-wi-fi-with-the-app-mpc-os-3-9-1-or-earlier")); c.appendChild(adv);
    }
    nav(c); root.appendChild(c);
  }
  root.hidden = false;
  draw();
  if (typeof fetch === "function") fetch("dl/downloads.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) { DL = d; draw(); } }).catch(function () {});
})();

/* Write a zip the user downloaded onto a USB stick, SD card or MPC drive, in the browser (Chrome/Edge: the File System Access API).
   The desktop installer's stick writers in a web page: nothing is uploaded, the zip is read and written on this computer.
   - stickZip(): a prebuilt stick (pinned by SHA-256, it runs as root on the MPC) onto an empty drive, like the installer.
   Used by guide.js; also loaded by tools/test_drivewrite.mjs under Node. */
var DriveWrite = (function () {
  var HOUSEKEEPING = { "system volume information": 1, "$recycle.bin": 1, ".trashes": 1, ".spotlight-v100": 1, ".fseventsd": 1, ".ds_store": 1 };
  var MAX = 64 << 20;

  function supported() { return typeof window !== "undefined" && typeof window.showDirectoryPicker === "function" && typeof DecompressionStream === "function"; }

  /* A zip's entries: [{name, dir, size, data()}]. Plain and deflate entries; no zip64, no encryption. */
  function readZip(buf) {
    var u = new Uint8Array(buf), v = new DataView(buf);
    if (u.length > MAX) throw new Error("That file is too big to be a Plugin Manager zip.");
    var e = -1;
    for (var i = u.length - 22; i >= Math.max(0, u.length - 65557); i--) if (v.getUint32(i, true) === 0x06054b50) { e = i; break; }
    if (e < 0) throw new Error("That file is not a zip.");
    var n = v.getUint16(e + 10, true), p = v.getUint32(e + 16, true), out = [];
    for (var k = 0; k < n; k++) {
      if (v.getUint32(p, true) !== 0x02014b50) throw new Error("The zip is damaged.");
      var flags = v.getUint16(p + 8, true), method = v.getUint16(p + 10, true), csize = v.getUint32(p + 20, true), size = v.getUint32(p + 24, true);
      var nl = v.getUint16(p + 28, true), xl = v.getUint16(p + 30, true), cl = v.getUint16(p + 32, true), off = v.getUint32(p + 42, true);
      var name = new TextDecoder().decode(u.subarray(p + 46, p + 46 + nl));
      if (flags & 1) throw new Error("The zip is encrypted.");
      if (method !== 0 && method !== 8) throw new Error("The zip uses a compression this page can't read.");
      if (csize === 0xffffffff || size === 0xffffffff) throw new Error("The zip is too large.");
      var start = off + 30 + v.getUint16(off + 26, true) + v.getUint16(off + 28, true);
      out.push(entry(name, u.subarray(start, start + csize), method, size));
      p += 46 + nl + xl + cl;
    }
    return out;
  }
  function entry(name, raw, method, size) {
    return { name: name, dir: /\/$/.test(name), size: size, data: function () {
      if (method === 0) return Promise.resolve(raw);
      var s = new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
      return new Response(s).arrayBuffer().then(function (b) {
        if (b.byteLength !== size) throw new Error("The zip is damaged (" + name + ").");
        return new Uint8Array(b);
      });
    } };
  }
  function parts(name) {   /* the path's folders and file, refusing anything that could land outside the drive */
    var ps = name.replace(/\/$/, "").split("/");
    if (!name || /^\//.test(name) || /[\\:]/.test(name) || ps.some(function (x) { return x === "" || x === "." || x === ".."; }))
      throw new Error("The zip has an unsafe file name: " + name);
    return ps;
  }
  function sha256(buf) {
    return crypto.subtle.digest("SHA-256", buf).then(function (h) {
      return Array.prototype.map.call(new Uint8Array(h), function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
    });
  }

  function dirIn(root, ps) {
    return ps.reduce(function (pr, x) { return pr.then(function (d) { return d.getDirectoryHandle(x, { create: true }); }); }, Promise.resolve(root));
  }
  function writeAll(root, entries, prefix, progress) {
    var files = entries.filter(function (x) { return !x.dir; }), done = 0;
    return files.reduce(function (pr, x) {
      return pr.then(function () {
        var ps = prefix.concat(parts(x.name)), file = ps.pop();
        return Promise.all([dirIn(root, ps), x.data()]).then(function (r) {
          return r[0].getFileHandle(file, { create: true }).then(function (fh) { return fh.createWritable(); }).then(function (w) {
            return w.write(r[1]).then(function () { return w.close(); });
          });
        }).then(function () { done++; if (progress) progress(done, files.length); });
      });
    }, Promise.resolve()).then(function () { return files.length; });
  }
  function contents(root) {
    var it = root.values(), seen = [];
    function next() {
      return it.next().then(function (r) {
        if (r.done) return seen;
        var n = r.value.name;
        if (n.charAt(0) !== "." && !HOUSEKEEPING[n.toLowerCase()]) seen.push(n);
        return seen.length >= 3 ? seen : next();
      });
    }
    return next();   /* up to three names that make the drive "not empty", to say why */
  }
  function pick() { return window.showDirectoryPicker({ id: "mpc-drive", mode: "readwrite" }); }

  /* buf, checked against a SHA-256 when one is given */
  function checked(buf, sha) {
    if (!sha) return Promise.resolve(buf);
    return sha256(buf).then(function (h) { if (h !== sha) throw new Error("The download didn't match its checksum. Reload the page and try again."); return buf; });
  }
  /* The file at a path on this site (same origin), with a progress callback; resolves to a file-like {arrayBuffer}. */
  function download(path, progress) {
    return fetch(path, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("Couldn't download " + path + " (" + r.status + ").");
      var total = +r.headers.get("content-length") || 0, got = 0, chunks = [], rd = r.body.getReader();
      function pump() {
        return rd.read().then(function (x) {
          if (x.done) { var b = new Blob(chunks); return { fromSite: true, arrayBuffer: function () { return b.arrayBuffer(); } }; }
          chunks.push(x.value); got += x.value.length; if (progress) progress(got, total); return pump();
        });
      }
      return pump();
    });
  }
  /* file: the stick zip; pin: {sha256, need:[paths]}; root must be empty. */
  function stickZip(file, root, pin, progress) {
    return file.arrayBuffer().then(function (buf) {
      return sha256(buf).then(function (h) {
        if (h !== pin.sha256) throw new Error("This isn't the expected stick zip (its checksum differs). Download it again from the link above.");
        var es = readZip(buf);
        es.forEach(function (x) { parts(x.name); });
        pin.need.forEach(function (n) { if (!es.some(function (x) { return x.name === n; })) throw new Error("The stick zip is missing " + n + "."); });
        return contents(root).then(function (found) {
          if (found.length) throw new Error("That drive isn't empty (it has " + found.join(", ") + "). The stick runs on the MPC, so it must hold only its own files: pick an empty, freshly formatted USB stick.");
          return writeAll(root, es, [], progress);
        });
      });
    });
  }
  return { supported: supported, pick: pick, download: download, readZip: readZip, stickZip: stickZip, checked: checked, sha256: sha256 };
})();
if (typeof module !== "undefined") module.exports = DriveWrite;

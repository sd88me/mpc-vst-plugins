// Host test for tools/catalog_site/drivewrite.js (the Install page's browser stick writer): node tools/test_drivewrite.mjs
// Zips are made by Python's zipfile; the drive is an in-memory stand-in for a FileSystemDirectoryHandle.
import { createRequire } from "module"; import { execFileSync } from "child_process"; import assert from "assert";
const DW = createRequire(import.meta.url)("./catalog_site/drivewrite.js");
function zip(files, method = "ZIP_DEFLATED") {
  const py = `import io,zipfile,sys,json\nb=io.BytesIO()\nz=zipfile.ZipFile(b,"w",zipfile.${method})\nfor n,d in json.loads(sys.argv[1]).items():\n  z.writestr(n,d)\nz.close()\nsys.stdout.buffer.write(b.getvalue())`;
  const out = execFileSync("python3", ["-c", py, JSON.stringify(files)]);
  return { arrayBuffer: async () => out.buffer.slice(out.byteOffset, out.byteOffset + out.length) };
}
class Dir { constructor(name) { this.name = name; this.k = new Map(); }
  async getDirectoryHandle(n, o) { if (!this.k.has(n)) { if (!o?.create) throw new Error("nf"); this.k.set(n, new Dir(n)); } return this.k.get(n); }
  async getFileHandle(n) { const d = this; return { createWritable: async () => { let b; return { write: async x => { b = Buffer.from(x); }, close: async () => d.k.set(n, b) }; } }; }
  async removeEntry(n) { if (!this.k.delete(n)) throw new Error("nf"); }
  values() { const it = [...this.k.keys()].map(name => ({ name }))[Symbol.iterator](); return { next: async () => it.next() }; }
}
let t = 0; async function test(n, fn) { await fn(); t++; console.log("ok", n); }
const NEED = ["autorun/autorun.json", ".mpc-manager-id"];
async function pinOf(z, need = NEED) { return { sha256: await DW.sha256(await z.arrayBuffer()), need }; }
const stick = zip({ "autorun/autorun.json": "{}", "autorun/open.sh": "#!/bin/sh", ".mpc-manager-id": "x" });
const pin = await pinOf(stick);
await test("stick zip onto an empty drive (housekeeping ignored)", async () => {
  const d = new Dir("S"); d.k.set("System Volume Information", new Dir("x")); d.k.set(".Trashes", new Dir("x"));
  assert.equal(await DW.stickZip(stick, d, pin), 3); assert.equal(d.k.get("autorun").k.get("open.sh").toString(), "#!/bin/sh");
});
await test("large and stored (not deflated) entries", async () => {
  const big = "a".repeat(100000), z = zip({ "autorun/autorun.json": "{}", ".mpc-manager-id": "x", "pm/x.so": big }, "ZIP_STORED"), d = new Dir("S");
  assert.equal(await DW.stickZip(z, d, await pinOf(z)), 3); assert.equal(d.k.get("pm").k.get("x.so").toString(), big);
});
for (const [n, files] of [["path escape", { "autorun/autorun.json": "", ".mpc-manager-id": "", "a/../../evil": "" }], ["absolute", { "autorun/autorun.json": "", ".mpc-manager-id": "", "/etc/x": "" }]])
  await test("refuses " + n, async () => { const z = zip(files); await assert.rejects(DW.stickZip(z, new Dir("S"), await pinOf(z)), /unsafe/); });
await test("not a zip", async () => {
  const f = { arrayBuffer: async () => new ArrayBuffer(100) };
  await assert.rejects(DW.stickZip(f, new Dir("S"), { sha256: await DW.sha256(new ArrayBuffer(100)), need: [] }), /not a zip/);
});
await test("stick refuses a drive with files", async () => { const d = new Dir("S"); d.k.set("Samples", new Dir("x")); await assert.rejects(DW.stickZip(stick, d, pin), /isn.t empty \(it has Samples\)/); assert.equal(d.k.size, 1); });
await test("stick refuses a different zip", async () => { await assert.rejects(DW.stickZip(stick, new Dir("S"), { ...pin, sha256: "0".repeat(64) }), /checksum/); });
await test("stick refuses a zip missing a needed file", async () => { await assert.rejects(DW.stickZip(stick, new Dir("S"), { ...pin, need: ["autorun/autorun.check"] }), /missing/); });
await test("a pinned download checksum", async () => {
  const b = await stick.arrayBuffer(); await DW.checked(b, pin.sha256); await assert.rejects(DW.checked(b, "0".repeat(64)), /checksum/);
});
console.log(t, "passed");

#!/usr/bin/env python3
"""Offline tests for tools/usb_g2 (run: python3 -I tools/test_usb_g2.py). A made-up salt stands in for the firmware's, and the
device is a set of scratch folders: fake mounts, a fake MPC.settings, and fake packages whose install.sh just records how it was run."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "usb_g2"))
import build_stick  # noqa: E402

SALT = b"00000000-test-salt-0000-000000000000"
VERSION = "0.2.0"
INSTALL_STUB = """#!/bin/sh
echo "ARGS: $*" > "$STUB_LOG"
echo "CWD: $(pwd)" >> "$STUB_LOG"
echo "PKG: %s" >> "$STUB_LOG"
exit ${STUB_RC:-0}
"""


def fake_package(path, arch, version=VERSION, plugin_id="plugin-manager-g2", with_installer=True):
    with zipfile.ZipFile(path, "w") as z:
        top = "Plugin-Manager-G2-%s" % version
        if with_installer:
            z.writestr(top + "/install.sh", INSTALL_STUB % arch)
        z.writestr(top + "/mpc-plugin.json", json.dumps({"id": plugin_id, "version": version, "arch": arch}))
    return path


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def zips(self, version=VERSION):
        folder = self.p / "zips"
        folder.mkdir(exist_ok=True)
        return {a: fake_package(folder / build_stick.zip_name(version, a), a, version) for a in build_stick.ARCHES}


class Builder(Tmp):
    def test_layout_and_check(self):
        out = build_stick.build(self.p / "stick", SALT, self.zips(), VERSION)
        autorun = out / "autorun"
        spec = json.loads((autorun / "autorun.json").read_text())["value0"]
        self.assertEqual(spec["files"], ["runtime/payload.sha256", "runtime/run.sh"])
        self.assertEqual(spec["scripts"][0]["path"], "open.sh")
        data = b"".join((autorun / n).read_bytes() for n in ["autorun.json", "open.sh"] + spec["files"])
        self.assertEqual((autorun / "autorun.check").read_bytes(), hashlib.sha256(data + SALT).hexdigest().encode())
        self.assertTrue((out / ".mpc-g2-stick").is_file())
        for arch in build_stick.ARCHES:
            self.assertTrue((out / "g2" / build_stick.zip_name(VERSION, arch)).is_file())

    def test_packages_are_not_covered_by_the_check_but_are_pinned_by_a_covered_file(self):
        out = build_stick.build(self.p / "stick", SALT, self.zips(), VERSION)
        listed = json.loads((out / "autorun/autorun.json").read_text())["value0"]["files"]
        self.assertFalse(any(f.startswith("g2/") for f in listed))
        manifest = (out / "autorun/runtime/payload.sha256").read_text().splitlines()
        self.assertEqual(len(manifest), 2)
        for line in manifest:
            digest, rel = line.split("  ")
            self.assertEqual(hashlib.sha256((out / rel).read_bytes()).hexdigest(), digest)

    def test_the_check_does_not_depend_on_the_package_contents(self):
        a = build_stick.build(self.p / "a", SALT, self.zips(), VERSION)
        self.assertTrue((a / "autorun/autorun.check").is_file())
        # a different package version changes payload.sha256, so the check changes with it: that is what pins the packages
        other = self.p / "other"
        other.mkdir()
        zips2 = {arch: fake_package(other / build_stick.zip_name("0.2.1", arch), arch, "0.2.1") for arch in build_stick.ARCHES}
        b = build_stick.build(self.p / "b", SALT, zips2, "0.2.1")
        self.assertNotEqual((a / "autorun/autorun.check").read_bytes(), (b / "autorun/autorun.check").read_bytes())

    def test_refuses_a_non_empty_folder_but_not_housekeeping(self):
        (self.p / "full").mkdir()
        (self.p / "full" / "mine.txt").write_text("x")
        with self.assertRaises(FileExistsError):
            build_stick.build(self.p / "full", SALT, self.zips(), VERSION)
        (self.p / "fresh").mkdir()
        (self.p / "fresh" / "System Volume Information").mkdir()
        build_stick.build(self.p / "fresh", SALT, self.zips(), VERSION)

    def test_refuses_wrong_packages(self):
        z = self.zips()
        with self.assertRaises(ValueError):
            build_stick.build(self.p / "s1", SALT, {"armv7": z["armv7"]}, VERSION)                       # one CPU only
        bad = fake_package(self.p / "bad.zip", "aarch64", plugin_id="something-else")
        with self.assertRaises(ValueError):
            build_stick.build(self.p / "s2", SALT, {"armv7": z["armv7"], "aarch64": bad}, VERSION)       # another plugin
        wrong_arch = fake_package(self.p / "w.zip", "armv7")
        with self.assertRaises(ValueError):
            build_stick.build(self.p / "s3", SALT, {"armv7": z["armv7"], "aarch64": wrong_arch}, VERSION)  # armv7 in the aarch64 slot
        no_installer = fake_package(self.p / "n.zip", "aarch64", with_installer=False)
        with self.assertRaises(ValueError):
            build_stick.build(self.p / "s4", SALT, {"armv7": z["armv7"], "aarch64": no_installer}, VERSION)
        with self.assertRaises(ValueError):
            build_stick.build(self.p / "s5", SALT, z, "0.2.0; rm -rf /")

    def test_zip_is_deterministic(self):
        out = build_stick.build(self.p / "stick", SALT, self.zips(), VERSION)
        a = build_stick.write_zip(out, self.p / "a.zip")
        b = build_stick.write_zip(out, self.p / "b.zip")
        self.assertEqual(a.read_bytes(), b.read_bytes())
        names = zipfile.ZipFile(a).namelist()
        self.assertIn(".mpc-g2-stick", names)
        self.assertIn("autorun/autorun.check", names)

    def test_zips_in_a_folder(self):
        z = self.zips()
        version, found = build_stick.zips_in(self.p / "zips")
        self.assertEqual((version, found), (VERSION, z))
        fake_package(self.p / "zips" / build_stick.zip_name("0.9.9", "aarch64"), "aarch64", "0.9.9")
        with self.assertRaises(ValueError):
            build_stick.zips_in(self.p / "zips")


class Device(Tmp):
    """open.sh with MPC_USB_TEST=1 against a scratch device."""

    def setUp(self):
        super().setUp()
        self.stick = build_stick.build(self.p / "stick", SALT, self.zips(), VERSION)
        self.fs = self.p / "fs"
        self.fs.mkdir()
        self.log = self.p / "stub.log"

    def candidate(self, name, exists=True, mount="rw,relatime", registered=True):
        folder = self.fs / name / "Synths"
        if exists:
            folder.mkdir(parents=True)
        self.mounts.append("/dev/fake %s ext4 %s 0 0\n" % (self.fs / name, mount))
        if registered:
            self.locations.append(str(folder))
        return str(folder)

    def run_device(self, candidates, arch="armv7", rc=0, tamper=None):
        settings = self.p / "MPC.settings"
        settings.write_text("<PROPERTIES><VALUE name=\"SynthContentLocations\"><SynthContentLocations>%s</SynthContentLocations></VALUE></PROPERTIES>" %
                            "".join("<Location>%s</Location>" % l for l in self.locations))
        mounts = self.p / "mounts"
        mounts.write_text("".join(self.mounts) + "/dev/root / ext4 ro 0 0\n")
        if tamper:
            (self.stick / "g2" / tamper).write_bytes(b"not the package")
        # a device has BusyBox unzip; a test host may not, so stand in for the one call run.sh makes: unzip -q -o <zip> -d <dir>
        shim = self.p / "bin" / "unzip"
        shim.parent.mkdir(exist_ok=True)
        shim.write_text("#!/bin/sh\nexec %s -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[3]).extractall(sys.argv[5])' \"$@\"\n" % sys.executable)
        shim.chmod(0o755)
        env = dict(os.environ, MPC_USB_TEST="1", MPC_G2_ARCH=arch, MPC_SETTINGS=str(settings), MPC_MOUNTS=str(mounts),
                   MPC_G2_CANDIDATES=" ".join(candidates), STUB_LOG=str(self.log), STUB_RC=str(rc), PATH=str(self.p / "bin") + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["sh", str(self.stick / "autorun/open.sh")], capture_output=True, text=True, env=env)
        result = (self.stick / "g2-install-result.txt").read_text() if (self.stick / "g2-install-result.txt").exists() else ""
        return r, result

    def test_installs_the_package_for_this_cpu_into_the_one_qualifying_folder(self):
        self.mounts, self.locations = [], []
        nvme = self.candidate("nvme")
        absent = self.candidate("sdcard", exists=False)
        r, result = self.run_device([absent, nvme], arch="aarch64")
        self.assertEqual(r.returncode, 0, result)
        stub = self.log.read_text()
        self.assertIn("ARGS: -y -t %s" % nvme, stub)
        self.assertIn("PKG: aarch64", stub)
        self.assertIn("Done.", result)
        self.assertTrue((self.stick / "MPC.settings.backup").is_file())

    def test_armv7_gets_the_armv7_package(self):
        self.mounts, self.locations = [], []
        sd = self.candidate("sdcard")
        r, result = self.run_device([sd], arch="armv7")
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("PKG: armv7", self.log.read_text())

    def test_a_swapped_package_is_refused_and_nothing_runs(self):
        self.mounts, self.locations = [], []
        sd = self.candidate("sdcard")
        r, result = self.run_device([sd], arch="armv7", tamper=build_stick.zip_name(VERSION, "armv7"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not match its checksum", result)
        self.assertFalse(self.log.exists())

    def test_no_candidate_means_nothing_is_installed(self):
        self.mounts, self.locations = [], []
        r, result = self.run_device([self.candidate("sdcard", exists=False)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no internal Synths folder qualifies", result)
        self.assertIn("does not exist", result)
        self.assertFalse(self.log.exists())

    def test_two_candidates_are_not_chosen_between(self):
        self.mounts, self.locations = [], []
        a, b = self.candidate("nvme"), self.candidate("storage")
        r, result = self.run_device([a, b])
        self.assertEqual(r.returncode, 1)
        self.assertIn("more than one Synths folder qualifies", result)
        self.assertFalse(self.log.exists())

    def test_a_folder_must_be_registered_writable_and_executable(self):
        self.mounts, self.locations = [], []
        unregistered = self.candidate("a", registered=False)
        readonly = self.candidate("b", mount="ro,relatime")
        noexec = self.candidate("c", mount="rw,noexec,relatime")
        good = self.candidate("d")
        r, result = self.run_device([unregistered, readonly, noexec, good])
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -t %s" % good, self.log.read_text())
        self.assertIn("is not a plugin location MPC lists", result)
        self.assertIn("read-write mount that allows executables", result)

    def test_the_packages_installer_failing_is_reported_with_its_status(self):
        self.mounts, self.locations = [], []
        sd = self.candidate("sdcard")
        r, result = self.run_device([sd], rc=3)
        self.assertEqual(r.returncode, 3)
        self.assertIn("failed (status 3)", result)

    def test_a_dry_run_chooses_and_verifies_but_changes_nothing(self):
        self.mounts, self.locations = [], []
        nvme = self.candidate("nvme")
        os.environ["MPC_G2_DRY_RUN"] = "1"
        try:
            r, result = self.run_device([nvme], arch="aarch64")
        finally:
            del os.environ["MPC_G2_DRY_RUN"]
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("Dry run: would install g2/Plugin-Manager-G2-0.2.0-mpc-aarch64.zip into %s" % nvme, result)
        self.assertFalse(self.log.exists(), "the package's installer must not run")
        self.assertFalse((self.stick / "MPC.settings.backup").exists())

    def test_a_cpu_that_is_not_an_mpc_is_refused(self):
        self.mounts, self.locations = [], []
        sd = self.candidate("sdcard")
        r, result = self.run_device([sd], arch="x86_64")
        self.assertEqual(r.returncode, 1)
        self.assertIn("this is for MPC OS devices", result)


if __name__ == "__main__":
    unittest.main()

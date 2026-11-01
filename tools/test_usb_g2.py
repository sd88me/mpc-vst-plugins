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
        self.sysfs = None

    def candidate(self, name, exists=True, mount="rw,relatime", registered=True, parent=False):
        folder = self.fs / name / "Synths"
        if exists:
            folder.mkdir(parents=True)
        elif parent:
            folder.parent.mkdir(parents=True)
        self.mounts.append("/dev/fake %s ext4 %s 0 0\n" % (self.fs / name, mount))
        if registered:
            self.locations.append(str(folder))
        return str(folder)

    def run_device(self, candidates, arch="armv7", rc=0, tamper=None, internal=None, drives=None, drives2=None, settings_text=None):
        settings = self.p / "MPC.settings"
        settings.write_text("<PROPERTIES><VALUE name=\"SynthContentLocations\"><SynthContentLocations>%s</SynthContentLocations></VALUE></PROPERTIES>" %
                            "".join("<Location>%s</Location>" % l for l in self.locations))
        if settings_text is not None:
            settings.write_text(settings_text)
        self.settings = settings
        mounts = self.p / "mounts"
        mounts.write_text("".join(self.mounts) + "/dev/root / ext4 ro 0 0\n")
        if tamper:
            (self.stick / "g2" / tamper).write_bytes(b"not the package")
        # a device has BusyBox unzip; a test host may not, so stand in for the one call run.sh makes: unzip -q -o <zip> -d <dir>
        shim = self.p / "bin" / "unzip"
        shim.parent.mkdir(exist_ok=True)
        shim.write_text("#!/bin/sh\nexec %s -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[3]).extractall(sys.argv[5])' \"$@\"\n" % sys.executable)
        shim.chmod(0o755)
        # busybox df wraps a long device name onto its own line unless -P is given, which leaves the numbers one line down
        df = self.p / "bin" / "df"
        df.write_text("#!/bin/sh\nfor last; do :; done\ncase \"$last\" in *sdcard*) AVAIL=${STUB_DF_SDCARD:-8000000} ;; *) AVAIL=${STUB_DF_AVAIL:-8000000} ;; esac\ncase \"$*\" in *P*) echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'; echo \"/dev/mapper/a-long-device-name 9000000 1000 ${AVAIL} 1% /x\" ;; *) echo 'Filesystem 1K-blocks Used Available Use% Mounted on'; echo '/dev/mapper/a-long-device-name'; echo \"  9000000 1000 ${AVAIL} 1% /x\" ;; esac\n")
        df.chmod(0o755)
        env = dict(os.environ, MPC_USB_TEST="1", MPC_G2_ARCH=arch, MPC_SETTINGS=str(settings), MPC_MOUNTS=str(mounts),
                   STUB_LOG=str(self.log), STUB_RC=str(rc), PATH=str(self.p / "bin") + os.pathsep + os.environ["PATH"])
        if candidates is not None:
            env["MPC_G2_CANDIDATES"] = " ".join(candidates)
        if self.sysfs is not None:
            env["MPC_G2_SYSFS"] = str(self.sysfs)
        if internal:
            env["MPC_G2_INTERNAL"] = " ".join(internal)
        if drives is not None:
            env["MPC_G2_DRIVES"] = " ".join(drives)
        env["MPC_G2_DRIVES2"] = " ".join(drives2) if drives2 is not None else "/nonexistent-g2-drive"   # never the host's own /media/az01-internal
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

    def test_a_listed_folder_that_is_not_there_yet_is_created_by_the_package(self):
        # a fresh Gen1 unit: MPC lists /sdcard/Synths but nothing ever made it (a tester's Gen1 stick found "does not exist" everywhere)
        self.mounts, self.locations = [], []
        fresh = self.candidate("sdcard", exists=False, parent=True)
        r, result = self.run_device([fresh])
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -t %s" % fresh, self.log.read_text())
        self.assertIn("it will be created", result)

    def test_a_missing_folder_that_is_not_listed_is_still_refused_and_the_log_says_what_the_device_has(self):
        self.mounts, self.locations = [], []
        fresh = self.candidate("sdcard", exists=False, parent=True, registered=False)
        os.environ["MPC_G2_DIAG_MOUNTS"] = "%s/[a-z]*" % self.fs   # fake mount points are not under /sdcard, /nvme ...
        try:
            r, result = self.run_device([fresh])
        finally:
            os.environ.pop("MPC_G2_DIAG_MOUNTS")
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not a plugin location MPC lists", result)
        self.assertIn("what this device has", result)
        self.assertRegex(result, r"/dev/fake \S+ ext4 rw,relatime free=\d+KB id=\d+:\d+")   # device, free space and folder id of each mount
        self.assertFalse(self.log.exists())

    def test_candidates_come_from_the_settings_and_only_internal_ones_count(self):
        # a Gen1 One: MPC lists /media/az01-internal/Synths and a card; no fixed path list is needed
        self.mounts, self.locations = [], []
        internal = self.candidate("az01-internal")
        card = self.candidate("card")
        r, result = self.run_device(None, internal=[str(self.fs / "az01-internal")])
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -t %s" % internal, self.log.read_text())
        self.assertNotIn("Candidate: " + card, result)
        self.assertIn("Listed: %s is not on the internal drive" % card, result)

    def test_two_paths_to_one_folder_count_once(self):
        self.mounts, self.locations = [], []
        a = self.candidate("nvme")
        link = self.fs / "link"
        link.symlink_to(self.fs / "nvme")
        self.mounts.append("/dev/fake %s ext4 rw,relatime 0 0\n" % link)
        self.locations.append(str(link / "Synths"))
        r, result = self.run_device(None, internal=[str(self.fs / "nvme"), str(link)])
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("the same folder as another candidate", result)

    def test_only_a_lasting_synths_folder_qualifies(self):
        self.mounts, self.locations = [], []
        ram = self.candidate("ram", mount="rw,relatime")
        self.mounts[-1] = "tmpfs %s tmpfs rw,relatime 0 0\n" % (self.fs / "ram")
        expansions = self.fs / "ex" / "Expansions"
        expansions.mkdir(parents=True)
        self.locations.append(str(expansions))
        r, result = self.run_device([ram, str(expansions)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("not kept across restarts", result)
        self.assertIn("is not a Synths folder", result)
        self.assertFalse(self.log.exists())

    # a Force whose MPC lists only Akai's own content: the internal drive gets a Synths folder that is added to MPC's list
    def drive(self, name, mount="rw,relatime", exists=True):
        d = self.fs / name
        if exists:
            d.mkdir(parents=True, exist_ok=True)
        self.mounts.append("/dev/fake %s ext4 %s 0 0\n" % (d, mount))
        return str(d)

    def ctl(self):
        f = self.log.with_name(self.log.name + ".ctl")
        return f.read_text().split() if f.exists() else []

    def test_with_no_internal_folder_listed_the_one_internal_drive_is_used_and_listed(self):
        self.mounts, self.locations = [], ["/media/SSD 512GB/Synths", "/usr/share/Akai/Content/Synths"]
        sd = self.drive("sdcard")
        r, result = self.run_device(None, drives=[sd, str(self.fs / "nvme")])
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -n -t %s/Synths" % sd, self.log.read_text())
        self.assertIn("<Location>%s/Synths</Location>" % sd, self.settings.read_text())
        self.assertIn("<Location>/media/SSD 512GB/Synths</Location>", self.settings.read_text())
        self.assertEqual(self.ctl(), ["stop", "start"])
        self.assertTrue(list(self.p.glob("MPC.settings.bak-g2loc-*")), "no backup beside the settings")

    def test_a_stub_folder_on_the_root_filesystem_is_not_an_internal_drive(self):
        self.mounts, self.locations = [], []
        stub = self.drive("sdcard")
        self.mounts.pop()   # not a mount of its own
        r, result = self.run_device(None, drives=[stub])
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not a drive of its own", result)
        self.assertEqual(self.ctl(), [])
        self.assertFalse(self.log.exists())

    def test_two_internal_drives_are_not_chosen_between(self):
        self.mounts, self.locations = [], []
        a, b = self.drive("sdcard"), self.drive("nvme")
        r, result = self.run_device(None, drives=[a, b])
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.ctl(), [])
        self.assertFalse(self.log.exists())

    def test_settings_without_a_list_of_plugin_folders_are_not_edited(self):
        self.mounts, self.locations = [], []
        sd = self.drive("sdcard")
        text = "<PROPERTIES><VALUE name=\"Other\">1</VALUE></PROPERTIES>"
        r, result = self.run_device(None, drives=[sd], settings_text=text)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no list of plugin folders", result)
        self.assertEqual(self.settings.read_text(), text)
        self.assertEqual(self.ctl(), [])

    def test_mpc_is_started_again_when_the_packages_installer_fails_after_listing(self):
        self.mounts, self.locations = [], []
        sd = self.drive("sdcard")
        r, result = self.run_device(None, drives=[sd], rc=3)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.ctl(), ["stop", "start"])
        self.assertIn("failed (status 3)", result)

    def test_a_dry_run_changes_no_settings_and_does_not_stop_mpc(self):
        self.mounts, self.locations = [], []
        sd = self.drive("sdcard")
        before = None
        env_extra = {"MPC_G2_DRY_RUN": "1"}
        os.environ.update(env_extra)
        try:
            r, result = self.run_device(None, drives=[sd])
            after = self.settings.read_text()
        finally:
            os.environ.pop("MPC_G2_DRY_RUN")
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("would also add", result)
        self.assertNotIn("<Location>%s/Synths" % sd, after)
        self.assertEqual(self.ctl(), [])

    def test_a_nearly_full_internal_drive_is_refused_with_the_figure_and_what_to_do(self):
        # a Force's /sdcard (the system partition) really had 17240 KB free: the stick must say so plainly
        self.mounts, self.locations = [], []
        sd = self.drive("sdcard")
        os.environ["STUB_DF_SDCARD"] = "17240"
        try:
            r, result = self.run_device(None, drives=[sd])
        finally:
            os.environ.pop("STUB_DF_SDCARD")
        self.assertEqual(r.returncode, 1)
        self.assertIn("17240 KB free", result)
        self.assertIn("64 MB is required", result)
        self.assertEqual(self.ctl(), [])
        self.assertFalse(self.log.exists())

    # a Force whose /sdcard is full but whose internal data partition (/media/az01-internal) has room: the second tier is used
    def run_tiers(self, sdcard_free="8000000", second=True, first_extra=None):
        self.mounts, self.locations = [], ["/media/SSD 512GB/Synths"]
        sd = self.drive("sdcard")
        data = self.drive("az01-internal") if second else str(self.fs / "az01-internal")
        os.environ["STUB_DF_SDCARD"] = sdcard_free
        try:
            first = [sd] + (first_extra(self) if first_extra else [])
            r, result = self.run_device(None, drives=first, drives2=[data])
        finally:
            os.environ.pop("STUB_DF_SDCARD")
        return sd, data, r, result

    def test_the_user_space_is_tried_first_even_when_the_model_drive_is_usable(self):
        sd, data, r, result = self.run_tiers()
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -n -t %s/Synths" % data, self.log.read_text())
        self.assertIn("<Location>%s/Synths</Location>" % data, self.settings.read_text())
        self.assertNotIn("trying the model's own drive", result)
        self.assertNotIn("<Location>%s/Synths</Location>" % sd, self.settings.read_text())
        self.assertEqual(self.ctl(), ["stop", "start"])

    def test_a_system_sd_with_little_room_is_not_needed_when_the_user_space_is_usable(self):
        sd, data, r, result = self.run_tiers(sdcard_free="17240")
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -n -t %s/Synths" % data, self.log.read_text())

    def test_the_model_drive_is_used_when_there_is_no_user_space_drive(self):
        sd, data, r, result = self.run_tiers(second=False)
        self.assertEqual(r.returncode, 0, result)
        self.assertIn("ARGS: -y -n -t %s/Synths" % sd, self.log.read_text())
        self.assertIn("trying the model's own drive", result)
        self.assertIn("/az01-internal is not there", result)

    def test_two_usable_model_drives_refuse_when_the_user_space_is_not_usable(self):
        sd, data, r, result = self.run_tiers(second=False, first_extra=lambda t: [t.drive("nvme")])
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.ctl(), [])
        self.assertFalse(self.log.exists())

    def test_the_user_space_must_be_a_drive_of_its_own_and_the_model_drive_must_have_room(self):
        sd, data, r, result = self.run_tiers(sdcard_free="17240", second=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("/az01-internal is not there", result)
        self.assertIn("has too little free space (17240 KB free", result)
        self.assertFalse(self.log.exists())

    def test_the_report_scans_every_drive_without_model_names(self):
        # r7 shadow scan: nothing chosen by it, but each partition gets a verdict: internal and usable, USB, system folder, noexec, duplicate
        self.mounts, self.locations = [], []
        self.sysfs = self.p / "sys" / "class" / "block"
        self.sysfs.mkdir(parents=True)
        def dev(name, bus):
            target = self.p / "sysdev" / bus / name
            target.mkdir(parents=True)
            (self.sysfs / name).symlink_to(target)
        dev("mmcblk0p8", "platform/mmc0")
        dev("mmcblk0p7", "platform/mmc0")
        dev("sdc1", "platform/usb7/7-1")
        data, data2, ssd = self.fs / "data", self.fs / "data2", self.fs / "ssd"
        for d in (data, data2, ssd):
            d.mkdir()
        self.mounts += ["/dev/mmcblk0p8 %s ext4 rw,relatime 0 0\n" % data,
                        "/dev/mmcblk0p8 %s ext4 rw,relatime 0 0\n" % data2,
                        "/dev/mmcblk0p7 /factory ext4 rw,relatime 0 0\n",
                        "/dev/sdc1 %s exfat rw,nosuid,nodev,noexec 0 0\n" % ssd]
        r, result = self.run_device([], drives=[])
        self.assertEqual(r.returncode, 1)
        self.assertIn("drive scan", result)
        self.assertRegex(result, r"%s \(mmcblk0p8, ext4, \d+ KB free\) would qualify" % data)
        self.assertNotIn(str(data2), result)   # the same partition twice is listed once
        self.assertRegex(result, r"/factory \(mmcblk0p7, ext4, [^)]*\) is a system folder")
        self.assertRegex(result, r"%s \(sdc1, exfat, \d+ KB free\) is on a USB bus" % ssd)
        self.assertFalse(self.log.exists())   # the scan chooses nothing

    def test_the_scan_knows_a_one_or_key_whose_internal_drive_is_a_loop_image(self):
        # an MPC One / Key 37: /storage is an exFAT image on /data through /dev/loop0; its SD card is a USB-attached drive
        self.mounts, self.locations = [], []
        self.sysfs = self.p / "sys" / "class" / "block"
        (self.sysfs / "loop0" / "loop").mkdir(parents=True)
        (self.sysfs / "loop0" / "loop" / "backing_file").write_text("/data/user-storage-image\n")
        (self.sysfs / "loop1" / "loop").mkdir(parents=True)
        (self.sysfs / "loop1" / "loop" / "backing_file").write_text("/media/SOMECARD/disk.img\n")
        storage, other = self.fs / "storage", self.fs / "other"
        storage.mkdir(); other.mkdir()
        self.mounts += ["/dev/loop0 %s exfat rw,relatime 0 0\n" % storage, "/dev/loop1 %s exfat rw,relatime 0 0\n" % other]
        r, result = self.run_device([], drives=[])
        self.assertRegex(result, r"%s \(loop0, exfat, \d+ KB free\) would qualify" % storage)
        self.assertRegex(result, r"%s \(loop1, exfat, \d+ KB free\) is a loop device not backed by an internal file" % other)

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
        self.assertIn("is read-only", result)
        self.assertIn("does not allow executables", result)

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

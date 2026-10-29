#!/usr/bin/env python3
"""Offline tests for tools/usb_stick (run: python3 -I tools/test_usb_stick.py). A made-up salt stands in for the firmware's."""
import hashlib
import json
import lzma
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "usb_stick"))
import make_stick  # noqa: E402
import saltscan  # noqa: E402

SALT = b"00000000-test-salt-0000-000000000000"   # 36 printable bytes, like the real one's shape


def encode(salt):
    pad = salt.ljust(saltscan.WIDTH, b"\0")
    return bytes(v ^ saltscan.KEY[i % 8] for i, v in enumerate(pad))


def firmware(salt=SALT, offset=0x1234568, size=0x1800000, seed=1, extra=()):
    rnd = random.Random(seed)
    buf = bytearray(rnd.randbytes(size))
    for off, s in [(offset, salt)] + list(extra):
        buf[off:off + saltscan.WIDTH] = encode(s)
    return bytes(buf)


class Scan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_raw_executable(self):
        (self.p / "MPC").write_bytes(firmware())
        salt, hits = saltscan.find_salt(self.p / "MPC")
        self.assertEqual(salt, SALT)
        self.assertEqual(hits, [("file", 0x1234568)])

    def test_every_alignment_and_a_chunk_boundary(self):
        for off in (8 * 7 + 3, 0x7ffff0 + 5, saltscan.CHUNK - 8, saltscan.CHUNK - 16 - 5):
            (self.p / "MPC").write_bytes(firmware(offset=off, size=saltscan.CHUNK * 2 + 1000))
            salt, hits = saltscan.find_salt(self.p / "MPC")
            self.assertEqual((salt, hits[0][1]), (SALT, off))

    def test_update_image_with_xz_rootfs(self):
        rootfs = bytearray(0x100000)                      # compressible, so it really is inside the xz stream
        rootfs[0x40000 + 12:0x40000 + 12 + saltscan.WIDTH] = encode(SALT)
        img = b"AZ01" + bytes(300) + lzma.compress(bytes(rootfs), format=lzma.FORMAT_XZ)
        (self.p / "update.img").write_bytes(img)
        salt, hits = saltscan.find_salt(self.p / "update.img")
        self.assertEqual(salt, SALT)
        self.assertTrue(hits[0][0].startswith("xz@"))

    def test_same_value_twice_is_fine(self):
        (self.p / "MPC").write_bytes(firmware(extra=[(0x400000, SALT)]))
        self.assertEqual(len(saltscan.find_salt(self.p / "MPC")[1]), 2)

    def test_refuses_two_values_and_none(self):
        # two genuine (zero-padded, shorter-than-WIDTH) salts disagree -> refuse to guess
        (self.p / "a").write_bytes(firmware(extra=[(0x400000, b"11111111-other-salt-1111-11111111")]))
        with self.assertRaises(ValueError):
            saltscan.find_salt(self.p / "a")
        (self.p / "b").write_bytes(random.Random(5).randbytes(1 << 20))
        with self.assertRaises(ValueError):
            saltscan.find_salt(self.p / "b")

    def test_full_width_runs_are_noise(self):
        # a coincidental printable run filling the whole WIDTH-byte field (no zero padding) is not the salt:
        # the real zero-padded salt wins. This is the Gen2 aarch64 rootfs case.
        noise = (b"A#nn%E70C#nn%y70M" * 3)[:saltscan.WIDTH]  # exactly WIDTH printable bytes, no zero padding
        self.assertEqual(len(noise), saltscan.WIDTH)
        (self.p / "MPC").write_bytes(firmware(extra=[(0x400000, noise)]))
        salt, hits = saltscan.find_salt(self.p / "MPC")
        self.assertEqual(salt, SALT)              # the zero-padded salt wins, the full-width run is dropped
        self.assertEqual(len(hits), 1)            # only the salt's location is reported


class Stick(unittest.TestCase):
    def test_layout_and_check(self):
        with tempfile.TemporaryDirectory() as d:
            out = make_stick.build(Path(d) / "stick", SALT, ROOT / "mpc-store.sh", ["plugin-manager-g2", "acid"])
            a = out / "autorun"
            m = json.loads((a / "autorun.json").read_text())["value0"]
            self.assertEqual(m["files"], ["runtime/mpc-store.sh", "runtime/run.sh"])
            self.assertEqual(m["scripts"][0]["path"], "open.sh")
            want = hashlib.sha256(b"".join((a / n).read_bytes() for n in ["autorun.json", "open.sh"] + m["files"]) + SALT).hexdigest()
            self.assertEqual((a / "autorun.check").read_text(), want)
            self.assertEqual((out / "install.txt").read_text().split("\n")[1:3], ["plugin-manager-g2", "acid"])
            with self.assertRaises(FileExistsError):
                make_stick.build(out, SALT, ROOT / "mpc-store.sh", [])

    def test_building_into_an_already_existing_empty_folder_works(self):
        # the common case when "out" is a mounted USB stick's own root: the mount point already exists.
        with tempfile.TemporaryDirectory() as d:
            mounted = Path(d) / "stick"
            mounted.mkdir()
            out = make_stick.build(mounted, SALT, ROOT / "mpc-store.sh", [])
            self.assertTrue((out / "autorun" / "open.sh").exists())

    def test_building_into_a_non_empty_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            occupied = Path(d) / "stick"
            occupied.mkdir()
            (occupied / "something.txt").write_text("not ours\n")
            with self.assertRaises(FileExistsError):
                make_stick.build(occupied, SALT, ROOT / "mpc-store.sh", [])

    def test_a_freshly_formatted_drives_own_housekeeping_folders_dont_count_as_not_empty(self):
        # a freshly formatted Windows drive always has "System Volume Information"; this must not block building
        # straight onto the drive's root (the bug the user hit testing a real freshly formatted stick, 2026-10-23).
        with tempfile.TemporaryDirectory() as d:
            mounted = Path(d) / "stick"
            mounted.mkdir()
            (mounted / "System Volume Information").mkdir()
            (mounted / ".Trashes").mkdir()
            out = make_stick.build(mounted, SALT, ROOT / "mpc-store.sh", [])
            self.assertTrue((out / "autorun" / "open.sh").exists())

    def test_changing_a_file_changes_the_check(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_stick.build(Path(d) / "s", SALT, ROOT / "mpc-store.sh", []) / "autorun"
            files = ["runtime/mpc-store.sh", "runtime/run.sh"]
            before = make_stick.autorun_check(a, files, SALT)
            (a / "runtime" / "run.sh").write_text("# changed\n")
            self.assertNotEqual(before, make_stick.autorun_check(a, files, SALT))

    def test_ssh_key_bundles_enable_ssh_and_the_key_itself(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pub = d / "id_ed25519.pub"
            pub.write_text("ssh-ed25519 AAAAfake sam@test\n")
            out = make_stick.build(d / "stick", SALT, ROOT / "mpc-store.sh", [], ssh_key=pub)
            runtime = out / "autorun" / "runtime"
            self.assertTrue((runtime / "enable_ssh.sh").exists())
            self.assertEqual((runtime / "authorized_key.pub").read_text(), pub.read_text())
            m = json.loads((out / "autorun" / "autorun.json").read_text())["value0"]
            self.assertEqual(sorted(m["files"]), ["runtime/authorized_key.pub", "runtime/enable_ssh.sh", "runtime/mpc-store.sh", "runtime/run.sh"])
            self.assertIn("SSH is also enabled", (out / "README-USB.txt").read_text())

    def test_no_ssh_key_means_no_ssh_files(self):
        with tempfile.TemporaryDirectory() as d:
            out = make_stick.build(Path(d) / "stick", SALT, ROOT / "mpc-store.sh", [])
            runtime = out / "autorun" / "runtime"
            self.assertFalse((runtime / "enable_ssh.sh").exists())
            self.assertFalse((runtime / "authorized_key.pub").exists())
            self.assertNotIn("SSH is also enabled", (out / "README-USB.txt").read_text())

    def test_ssh_password_bundles_enable_ssh_and_a_password_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = make_stick.build(Path(d) / "stick", SALT, ROOT / "mpc-store.sh", [], ssh_password="hunter2")
            runtime = out / "autorun" / "runtime"
            self.assertTrue((runtime / "enable_ssh.sh").exists())
            self.assertEqual((runtime / "ssh_password.txt").read_text(), "hunter2\n")
            self.assertFalse((runtime / "authorized_key.pub").exists())
            self.assertIn("password login is also turned on", (out / "README-USB.txt").read_text())

    def test_ssh_key_and_password_together_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pub = d / "id_ed25519.pub"
            pub.write_text("ssh-ed25519 AAAAfake sam@test\n")
            with self.assertRaises(ValueError):
                make_stick.build(d / "stick", SALT, ROOT / "mpc-store.sh", [], ssh_key=pub, ssh_password="hunter2")


class RunScript(unittest.TestCase):
    """run.sh against a stub mpc-store.sh: which ids it passes, the settings copy, the result file, the exit status."""
    def run_it(self, install_txt, rc=0):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work = d / "usb", d / "work"
            usb.mkdir()
            work.mkdir()
            (work / "mpc-store.sh").write_text(f'echo "store args: $*"\nexit {rc}\n')
            (d / "MPC.settings").write_text("<settings/>\n")
            if install_txt is not None:
                (usb / "install.txt").write_text(install_txt)
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            res = (usb / "mpc-install-result.txt").read_text()
            return r.returncode, res, (usb / "MPC.settings.backup").exists(), work.exists()

    def test_default_is_the_plugin_manager(self):
        rc, res, backup, left = self.run_it(None)
        self.assertEqual(rc, 0)
        self.assertIn("store args: -y install plugin-manager-g2", res)
        self.assertTrue(backup)
        self.assertFalse(left)

    def test_ids_from_install_txt_and_junk_ignored(self):
        rc, res, *_ = self.run_it("# comment\nacid  \n$(rm -rf x)\nplugin-manager-g2 # trailing\n; ls\n")
        self.assertIn("store args: -y install acid plugin-manager-g2", res)
        self.assertNotIn("rm -rf", res.split("store args")[1])

    def test_failure_is_reported_and_status_kept(self):
        rc, res, *_ = self.run_it("acid\n", rc=3)
        self.assertEqual(rc, 3)
        self.assertIn("Install failed (status 3)", res)

    def run_with_addins(self, addin_ids, install_txt=None):
        """Like run_it, but with MPC_ADDINS_DIR pointing at <id>/install.sh stubs that log their own args, instead
        of the real /data/mpc-addins (docs/ADDINS.md, "A device with no persistent /etc")."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work, addins = d / "usb", d / "work", d / "addins"
            usb.mkdir(); work.mkdir(); addins.mkdir()
            (work / "mpc-store.sh").write_text('echo "store args: $*"\n')
            (d / "MPC.settings").write_text("<settings/>\n")
            if install_txt is not None:
                (usb / "install.txt").write_text(install_txt)
            for aid in addin_ids:
                p = addins / aid
                p.mkdir()
                (p / "install.sh").write_text(f'echo "addin {aid} install args: $*" >> "{d}/addin.log"\n')
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"), MPC_ADDINS_DIR=str(addins))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            log = (d / "addin.log").read_text() if (d / "addin.log").exists() else ""
            res = (usb / "mpc-install-result.txt").read_text()
            return r.returncode, res, log

    def test_every_installed_addin_is_reapplied_before_the_catalog_install(self):
        rc, res, log = self.run_with_addins(["remote", "skipback"])
        self.assertEqual(rc, 0)
        self.assertRegex(log, r"addin remote install args: -y -n -t \S*/addins/remote\n")
        self.assertRegex(log, r"addin skipback install args: -y -n -t \S*/addins/skipback\n")
        self.assertLess(log.index("remote"), log.index("skipback"))   # directory order
        self.assertIn("Reapplying addin: remote", res)
        self.assertIn("Reapplying addin: skipback", res)
        self.assertLess(res.index("Reapplying addin: remote"), res.index("store args"))   # both before the catalog install

    def test_no_addins_installed_is_a_quiet_no_op(self):
        rc, res, log = self.run_with_addins([])
        self.assertEqual(rc, 0)
        self.assertEqual(log, "")
        self.assertNotIn("Reapplying", res)

    def test_a_folder_without_install_sh_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work, addins = d / "usb", d / "work", d / "addins"
            usb.mkdir(); work.mkdir(); addins.mkdir()
            (work / "mpc-store.sh").write_text('echo "store args: $*"\n')
            (d / "MPC.settings").write_text("<settings/>\n")
            (addins / "empty").mkdir()   # a leftover folder with no install.sh in it (e.g. mid-uninstall)
            p = addins / "remote"; p.mkdir()
            (p / "install.sh").write_text(f'echo "addin remote install args: $*" >> "{d}/addin.log"\n')
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"), MPC_ADDINS_DIR=str(addins))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            res = (usb / "mpc-install-result.txt").read_text()
            self.assertEqual(r.returncode, 0)
            self.assertIn("Reapplying addin: remote", res)
            self.assertNotIn("empty", res)

    def test_a_failing_addin_reapply_is_warned_and_does_not_stop_the_catalog_install(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work, addins = d / "usb", d / "work", d / "addins"
            usb.mkdir(); work.mkdir(); addins.mkdir()
            (work / "mpc-store.sh").write_text('echo "store args: $*"\n')
            (d / "MPC.settings").write_text("<settings/>\n")
            p = addins / "broken"; p.mkdir()
            (p / "install.sh").write_text("exit 1\n")
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"), MPC_ADDINS_DIR=str(addins))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            res = (usb / "mpc-install-result.txt").read_text()
            self.assertEqual(r.returncode, 0)
            self.assertIn("warning: reapplying addin broken failed (status 1)", res)
            self.assertIn("store args: -y install plugin-manager-g2", res)

    def test_ssh_is_enabled_before_the_addin_reapply_and_catalog_install(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work, addins = d / "usb", d / "work", d / "addins"
            usb.mkdir(); work.mkdir(); addins.mkdir()
            (work / "mpc-store.sh").write_text('echo "store args: $*"\n')
            (work / "enable_ssh.sh").write_text(f'echo "enable_ssh args: $*" >> "{d}/ssh.log"\n')
            (work / "authorized_key.pub").write_text("ssh-ed25519 AAAAfake sam@test\n")
            (d / "MPC.settings").write_text("<settings/>\n")
            p = addins / "remote"; p.mkdir()
            (p / "install.sh").write_text(f'echo "addin remote install args: $*" >> "{d}/addin.log"\n')
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"), MPC_ADDINS_DIR=str(addins))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            res = (usb / "mpc-install-result.txt").read_text()
            self.assertEqual(r.returncode, 0)
            self.assertIn("enable_ssh args: --key " + str(work / "authorized_key.pub"), (d / "ssh.log").read_text())
            self.assertIn("Enabling SSH", res)
            self.assertLess(res.index("Enabling SSH"), res.index("Reapplying addin: remote"))

    def test_ssh_password_is_used_when_no_key_is_on_the_stick(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work, addins = d / "usb", d / "work", d / "addins"
            usb.mkdir(); work.mkdir(); addins.mkdir()
            (work / "mpc-store.sh").write_text('echo "store args: $*"\n')
            (work / "enable_ssh.sh").write_text(f'echo "enable_ssh args: $*" >> "{d}/ssh.log"\n')
            (work / "ssh_password.txt").write_text("hunter2\n")
            (d / "MPC.settings").write_text("<settings/>\n")
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"), MPC_ADDINS_DIR=str(addins))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            res = (usb / "mpc-install-result.txt").read_text()
            self.assertEqual(r.returncode, 0)
            self.assertIn("enable_ssh args: --password hunter2", (d / "ssh.log").read_text())
            self.assertIn("Enabling SSH (password", res)

    def test_no_ssh_key_on_the_stick_skips_enabling_it(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            usb, work = d / "usb", d / "work"
            usb.mkdir(); work.mkdir()
            (work / "mpc-store.sh").write_text('echo "store args: $*"\n')
            (d / "MPC.settings").write_text("<settings/>\n")
            env = dict(os.environ, MPC_USB_TEST="1", MPC_SETTINGS=str(d / "MPC.settings"), MPC_ADDINS_DIR=str(d / "noaddins"))
            r = subprocess.run(["sh", str(ROOT / "usb_stick" / "run.sh"), str(usb), str(work)], env=env, capture_output=True)
            res = (usb / "mpc-install-result.txt").read_text()
            self.assertEqual(r.returncode, 0)
            self.assertNotIn("Enabling SSH", res)

    def test_on_demand_sshd_goes_in_its_own_unit_even_when_stopping_a_missing_unit_fails(self):
        # The last block of enable_ssh.sh (the read-only-root branch) under `sh -e`, as on a device where `systemctl stop` of a unit that does
        # not exist yet exits 5. Found on a Live III 2026-10-27: that exit aborted the script before sshd was started.
        text = (ROOT / "usb_stick" / "enable_ssh.sh").read_text()
        start = text.index("    if command -v systemd-run")
        end = text.index("\n    fi\n", start) + len("\n    fi\n")
        block = text[start:end]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            bin_ = d / "bin"; bin_.mkdir()
            (bin_ / "systemctl").write_text("#!/bin/sh\nexit 5\n")
            (bin_ / "systemd-run").write_text(f'#!/bin/sh\necho "systemd-run $*" >> "{d}/calls"\n')
            (bin_ / "sshd").write_text(f'#!/bin/sh\necho "sshd $*" >> "{d}/calls"\n')
            for f in bin_.iterdir():
                f.chmod(0o755)
            script = f'HK="-h /k"; AUTHOPTS="-o X=y"; set -e\n{block.replace("/usr/sbin/sshd", str(bin_ / "sshd"))}\necho reached-the-end\n'
            r = subprocess.run(["sh", "-c", script], env=dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}"), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("reached-the-end", r.stdout)
            calls = (d / "calls").read_text()
            self.assertIn("systemd-run --unit=mpc-usb-sshd --collect", calls)
            self.assertIn(" -D ", calls)


if __name__ == "__main__":
    unittest.main()

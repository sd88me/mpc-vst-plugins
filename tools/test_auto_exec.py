#!/usr/bin/env python3
"""Tests for tools/mpc_patch/auto_exec/auto-exec-patch.sh (an executable Synths folder on every noexec drive).

Real mounts, as in test_drive_exec.py: as root, in a private mount namespace, tmpfs mounts with noexec stand for the drives, and a
small shared library is really dlopen()ed. systemctl and pidof are shims. Run:  python3 tools/test_auto_exec.py   (CI: sudo)
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_drive_exec as T   # shared rig: namespace, shims, probe library

DIR = os.path.join(HERE, "mpc_patch", "auto_exec")
SCRIPT = os.path.join(DIR, "auto-exec-patch.sh")
IN_NS = T.IN_NS
SH = T.SH
needs_ns = T.needs_ns
read, write, sh = T.read, T.write, T.sh


class Rig(T.Rig):
    def setUp(self):
        super().setUp()
        if IN_NS:
            self.env["AEX_PREFIX"] = self.root
            self.env["AUTO_EXEC_STATE"] = self.root + "/run/auto-exec"

    def cleanup_mounts(self):
        for d in sorted(self.drives, key=len, reverse=True):
            sh("umount '%s/Synths' 2>/dev/null; umount '%s' 2>/dev/null" % (d, d))

    def run_patch(self, *args, stdin=""):
        return subprocess.run([SH, SCRIPT, *args], env=self.env, input=stdin, capture_output=True, text=True, timeout=120)

    def helper(self, *args):
        return subprocess.run([SH, self.root + "/etc/auto-exec/auto-exec.sh", *args], env=self.env, capture_output=True, text=True, timeout=60)

    def install(self):
        r = self.run_patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def drive_with_plugin(self, name, options="noexec,nosuid,nodev"):
        d = self.make_drive(name, options)
        p = os.path.join(d, "Synths", "me - VST - X")
        os.makedirs(p)
        if self.probe:
            shutil.copy(self.probe, p + "/probe.so")
        return d, p + "/probe.so"


@needs_ns
class Mechanism(Rig):
    def test_every_noexec_drive_gets_an_executable_synths_folder_and_removal_undoes_it(self):
        ssd, so1 = self.drive_with_plugin("SSD - Force")
        usb, so2 = self.drive_with_plugin("E6CA-9201")
        sd, so3 = self.drive_with_plugin("Open", "nosuid,nodev")           # already executable: left alone
        nofolder = self.make_drive("No Synths")
        parent = {d: (self.mountinfo(d)[0][0], self.options(d)) for d in (ssd, usb, sd, nofolder)}
        if self.probe:
            self.assertFalse(self.dlopen_ok(so1))
            self.assertFalse(self.dlopen_ok(so2))
        st = self.state(self.run_patch("status").stdout)
        self.assertEqual((st["state"], st["supported"]), ("stock", "1"))
        self.install()
        for d in (ssd, usb):
            self.assertNotIn("noexec", self.options(d + "/Synths").split(","), d)
            self.assertIn("noexec", self.options(d).split(","), "the drive itself stays noexec")
            self.assertIn("nosuid", self.options(d + "/Synths").split(","), "other flags are kept")
        self.assertEqual(len(self.mountinfo(sd + "/Synths")), 0, "an executable drive gets no extra mount")
        self.assertEqual(len(self.mountinfo(nofolder + "/Synths")), 0)
        self.assertFalse(os.path.exists(nofolder + "/Synths"), "no folder is created")
        for d in parent:
            self.assertEqual((self.mountinfo(d)[0][0], self.options(d)), parent[d], "parent mounts are untouched")
        if self.probe:
            self.assertTrue(self.dlopen_ok(so1))
            self.assertTrue(self.dlopen_ok(so2))
            shutil.copy(self.probe, ssd + "/outside.so")
            self.assertFalse(self.dlopen_ok(ssd + "/outside.so"), "files outside Synths stay blocked")
        self.assertIn("enable --now auto-exec.timer", read(self.log))
        for f in ("etc/systemd/system/auto-exec.service", "etc/systemd/system/auto-exec.timer", "usr/lib/systemd/system/auto-exec-bootstrap.service"):
            self.assertTrue(os.path.isfile(os.path.join(self.root, f)), f)
        self.assertTrue(os.listdir(self.root + "/data/mpc-vst-plugins/backups"))
        st = self.state(self.run_patch("status").stdout)
        self.assertEqual((st["state"], st["backup"]), ("patched", "1"))
        r = self.run_patch("uninstall", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for d in (ssd, usb):
            self.assertEqual(len(self.mountinfo(d + "/Synths")), 0)
        if self.probe:
            self.assertFalse(self.dlopen_ok(so1), "after removal the drive is noexec again")
        self.assertFalse(os.path.exists(self.root + "/etc/auto-exec"))
        self.assertTrue(os.path.isfile(so1), "plugins are never touched")

    def test_the_bootstrap_lands_in_the_root_filesystem_under_a_usr_overlay(self):
        # A Force where something mounts an overlay over /usr after boot (seen 2026-10-22): systemd reads the wants link
        # before that mount exists, so the unit must be written underneath it. A bind mount stands for the overlay.
        boot = "usr/lib/systemd/system/auto-exec-bootstrap.service"
        link = "usr/lib/systemd/system/multi-user.target.wants/auto-exec-bootstrap.service"
        upper = tempfile.mkdtemp(prefix="usr-upper-", dir=self.work)
        os.makedirs(self.root + "/usr", exist_ok=True)
        sh("mount --bind '%s' '%s/usr'" % (upper, self.root))
        try:
            self.install()
            st = self.state(self.run_patch("status").stdout)
            self.assertNotEqual(st.get("reason"), "bootstrap-missing")
            self.assertFalse(os.path.exists(os.path.join(upper, boot[4:])), "nothing goes into the overlay")
        finally:
            sh("umount '%s/usr'" % self.root)
        self.assertTrue(os.path.isfile(os.path.join(self.root, boot)))
        self.assertTrue(os.path.islink(os.path.join(self.root, link)))

    def test_status_reports_a_bootstrap_that_only_an_overlay_holds(self):
        # 0.3.0's failure mode: the unit is visible through /usr but not in the root filesystem.
        self.install()
        unit = self.root + "/usr/lib/systemd/system"
        upper = tempfile.mkdtemp(prefix="usr-upper-", dir=self.work)
        shutil.copytree(unit, upper + "/s", symlinks=True)
        os.remove(unit + "/auto-exec-bootstrap.service")
        os.remove(unit + "/multi-user.target.wants/auto-exec-bootstrap.service")
        sh("mount --bind '%s/s' '%s'" % (upper, unit))
        try:
            st = self.state(self.run_patch("status").stdout)
            self.assertEqual((st["state"], st.get("reason")), ("partial", "bootstrap-missing"))
        finally:
            sh("umount '%s'" % unit)

    def test_a_drive_plugged_in_later_is_picked_up_and_an_unplugged_one_released(self):
        self.install()
        usb, so = self.drive_with_plugin("E6CA-9201")
        self.assertEqual(len(self.mountinfo(usb + "/Synths")), 0, "not before the next pass")
        self.assertEqual(self.helper("apply").returncode, 0)
        self.assertEqual(len(self.mountinfo(usb + "/Synths")), 1)
        for _ in range(3):
            self.helper("apply")
        self.assertEqual(len(self.mountinfo(usb + "/Synths")), 1, "applying again does not stack mounts")
        sh("umount -l '%s'" % usb)                                        # the drive goes away (our child mount is lazily detached with it)
        self.assertEqual(self.helper("apply").returncode, 0)
        self.assertEqual(len(self.mountinfo(usb + "/Synths")), 0)
        self.assertEqual(read(self.root + "/run/auto-exec/owned.mounts").strip(), "", "and forgotten")

    def test_release_lets_a_drive_be_unmounted_and_a_busy_one_refuses(self):
        if not self.probe:
            self.skipTest("no C compiler")
        self.install()
        usb, so = self.drive_with_plugin("E6CA-9201")
        self.helper("apply")
        self.assertNotEqual(sh("umount '%s'" % usb).returncode, 0, "with the child mount the drive is busy")
        holder = subprocess.Popen([sys.executable, "-c", "import ctypes,sys,time; ctypes.CDLL(sys.argv[1]); print('loaded', flush=True); time.sleep(60)", so], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "loaded")
            r = self.helper("release")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("busy", r.stdout)
            self.assertEqual(len(self.mountinfo(usb + "/Synths")), 1)
        finally:
            holder.send_signal(signal.SIGKILL)
            holder.wait()
            holder.stdout.close()
        self.assertEqual(self.run_patch("release").returncode, 0)
        self.assertEqual(sh("umount '%s'" % usb).returncode, 0)

    def test_verify_says_whether_mpc_itself_sees_the_executable_folders(self):
        def vline(out):
            ls = [l for l in out.splitlines() if l.startswith("VERIFY ")]
            self.assertEqual(len(ls), 1, out)
            self.assertEqual(out.strip().splitlines()[-1], ls[0])
            return dict(kv.split("=") for kv in ls[0].split()[1:])
        r = self.run_patch("verify")
        self.assertEqual((r.returncode, vline(r.stdout)["result"]), (1, "not-installed"))
        self.install()
        self.assertEqual(vline(self.run_patch("verify").stdout)["result"], "not-active", "no drive yet")
        usb, _ = self.drive_with_plugin("E6CA-9201")
        self.helper("apply")
        self.assertEqual(vline(self.run_patch("verify").stdout)["result"], "mpc-stopped")
        write(self.pidfile, "4242\n")
        blind = os.path.join(self.root, "mpc-mountinfo")
        write(blind, "\n".join(l for l in read("/proc/self/mountinfo").splitlines() if "/Synths" not in l) + "\n")
        self.env["AEX_MPC_MOUNTINFO"] = blind
        r = self.run_patch("verify")
        self.assertEqual((r.returncode, vline(r.stdout)["result"]), (1, "mpc-blind"))
        self.env["AEX_MPC_MOUNTINFO"] = "/proc/self/mountinfo"
        r = self.run_patch("verify")
        self.assertEqual((r.returncode, vline(r.stdout)["result"]), (0, "no-plugins"))
        write(usb + "/Synths/me - VST - X/plugin-meta.xml", "<x/>")
        v = vline(self.run_patch("verify").stdout)
        self.assertEqual((v["result"], v["plugins"]), ("ok", "1"))

    def test_a_failed_install_rolls_everything_back(self):
        usb, _ = self.drive_with_plugin("E6CA-9201")
        self.env["DEX_FAIL_ENABLE"] = "1"
        r = self.run_patch("install", "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rolling back", r.stdout)
        self.assertEqual(len(self.mountinfo(usb + "/Synths")), 0)
        self.assertFalse(os.path.exists(self.root + "/etc/auto-exec"))
        self.assertFalse(os.path.exists(self.root + "/usr/lib/systemd/system/auto-exec-bootstrap.service"))
        self.assertIn("noexec", self.options(usb).split(","))


@needs_ns
class Refusals(Rig):
    def test_nothing_is_installed_without_the_typed_word(self):
        r = self.run_patch("install", stdin="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cancelled", r.stderr)
        self.assertFalse(os.path.exists(self.root + "/etc/auto-exec"))
        self.assertEqual(self.run_patch("install", stdin="PATCH\n").returncode, 0)
        self.assertNotEqual(self.run_patch("uninstall", stdin="no\n").returncode, 0)
        self.assertTrue(os.path.isdir(self.root + "/etc/auto-exec"))

    def test_hostile_drive_names_and_internal_storage_are_never_touched(self):
        self.install()
        drives = [self.drive_with_plugin(n)[0] for n in ("bad'name", "a$(touch /tmp/aex-pwned)", "semi;colon", "back\\slash", "az01-internal-x", "acvs-synths")]
        self.helper("apply")
        for d in drives:
            self.assertEqual(len(self.mountinfo(d + "/Synths")), 0, d)
        self.assertFalse(os.path.exists("/tmp/aex-pwned"))

    def test_a_symlinked_or_foreign_synths_folder_is_left_alone(self):
        self.install()
        a = self.make_drive("Linked")
        os.makedirs(a + "/real")
        os.symlink(a + "/real", a + "/Synths")
        b = self.make_drive("Foreign")
        os.makedirs(b + "/Synths")
        subprocess.run(["mount", "--bind", b + "/Synths", b + "/Synths"], check=True)
        self.assertEqual(self.helper("apply").returncode, 0)
        self.assertEqual(len(self.mountinfo(a + "/real")), 0)
        self.assertEqual(len(self.mountinfo(b + "/Synths")), 1, "the foreign mount is not stacked on")
        self.assertIn("noexec", self.options(b + "/Synths").split(","))
        self.run_patch("uninstall", "--confirmed")
        self.assertEqual(len(self.mountinfo(b + "/Synths")), 1, "and not removed")

    def test_other_installs_and_versions_are_reported_and_never_touched(self):
        for etc, reason in (("etc/drive-exec", "other-install"), ("etc/force-vst-exec", "other-install")):
            os.makedirs(self.root + "/" + etc)
            st = self.state(self.run_patch("status").stdout)
            self.assertEqual((st["state"], st["reason"]), ("unsupported", reason))
            self.assertNotEqual(self.run_patch("install", "--confirmed").returncode, 0)
            self.assertFalse(os.path.exists(self.root + "/etc/auto-exec"))
            shutil.rmtree(self.root + "/" + etc)
        os.makedirs(self.root + "/etc/auto-exec")
        write(self.root + "/etc/auto-exec/VERSION", "0.0.1\n")
        st = self.state(self.run_patch("status").stdout)
        self.assertEqual(st["reason"], "other-version")
        self.assertNotEqual(self.run_patch("uninstall", "--confirmed").returncode, 0)
        self.assertEqual(read(self.root + "/etc/auto-exec/VERSION"), "0.0.1\n")

    def test_an_older_version_is_updated_in_place(self):
        # The installer app only runs the current script, so it must replace 0.3.0 / 0.3.1 itself (with their own uninstallers).
        usb, _ = self.drive_with_plugin("E6CA-9201")
        for commit, old in (("7184764", "0.3.0"), ("af05a83", "0.3.1")):
            r = subprocess.run(["git", "-C", HERE, "show", commit + ":tools/mpc_patch/auto_exec/auto-exec-patch.sh"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "needs the git history (CI: fetch-depth 0): " + r.stderr)
            old_script = os.path.join(self.work, "old-%s.sh" % old)
            write(old_script, r.stdout)
            r = subprocess.run([SH, old_script, "install", "--confirmed"], env=self.env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(read(self.root + "/etc/auto-exec/VERSION").strip(), old)
            st = self.state(self.run_patch("status").stdout)
            self.assertEqual((st["state"], st["supported"]), ("old-patch", "1"))
            r = self.install()
            self.assertIn("Version %s removed." % old, r.stdout)
            self.assertEqual(read(self.root + "/etc/auto-exec/VERSION").strip(), "0.3.2")
            self.assertEqual(len(self.mountinfo(usb + "/Synths")), 1, "exactly one executable mount after the update")
            self.assertEqual(self.state(self.run_patch("status").stdout)["state"], "patched")
            self.assertEqual(self.run_patch("uninstall", "--confirmed").returncode, 0)
            self.assertFalse(os.path.exists(self.root + "/etc/auto-exec"))
        # an old version can also just be removed with this script
        subprocess.run([SH, old_script, "install", "--confirmed"], env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(self.run_patch("uninstall", "--confirmed").returncode, 0)
        self.assertFalse(os.path.exists(self.root + "/etc/auto-exec"))
        self.assertEqual(len(self.mountinfo(usb + "/Synths")), 0)

    def test_a_loaded_plugin_blocks_removal_until_it_is_gone(self):
        if not self.probe:
            self.skipTest("no C compiler")
        usb, so = self.drive_with_plugin("E6CA-9201")
        self.install()
        holder = subprocess.Popen([sys.executable, "-c", "import ctypes,sys,time; ctypes.CDLL(sys.argv[1]); print('loaded', flush=True); time.sleep(60)", so], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "loaded")
            write(self.pidfile, str(holder.pid))
            r = self.run_patch("uninstall", "--confirmed")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("MPC is using a plugin", r.stdout)
            self.assertEqual(len(self.mountinfo(usb + "/Synths")), 1)
            self.assertTrue(os.path.isdir(self.root + "/etc/auto-exec"))
        finally:
            holder.send_signal(signal.SIGKILL)
            holder.wait()
            holder.stdout.close()
        os.remove(self.pidfile)
        self.assertEqual(self.run_patch("uninstall", "--confirmed").returncode, 0)


class Generated(unittest.TestCase):
    def test_the_script_embeds_exactly_the_files_in_src(self):
        text = read(SCRIPT)
        found = dict((m.group(1), m.group(3)) for m in re.finditer(r'cat > "\$d/([^"]+)" <<\'(AEX_EOF_\w+)\'\n(.*?)\n\2\n', text, re.S))
        self.assertEqual(set(found), {"auto-exec.sh", "uninstall.sh", "bootstrap.sh", "root-bootstrap.sh", "auto-exec.service",
                                      "auto-exec.timer", "auto-exec-bootstrap.service"})
        for name, body in found.items():
            self.assertEqual(body + "\n", read(os.path.join(DIR, "src", name)), name)

    def test_the_script_is_up_to_date_with_its_generator(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        subprocess.run([sys.executable, os.path.join(DIR, "build_script.py"), os.path.join(out, "x.sh")], check=True, capture_output=True)
        self.assertEqual(read(SCRIPT), read(os.path.join(out, "x.sh")), "run tools/mpc_patch/auto_exec/build_script.py and commit the result")

    def test_every_shell_file_parses(self):
        for f in [SCRIPT] + [os.path.join(DIR, "src", n) for n in os.listdir(os.path.join(DIR, "src")) if n.endswith(".sh")]:
            r = subprocess.run([SH, "-n", f], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + r.stderr)

    def test_no_bracket_expression_holds_an_escaped_slash(self):
        # BusyBox awk (the device's) reads `[^\/]` as "not a backslash or a slash", so a mount point with a space (\040 in
        # mountinfo, "Force SSD") was skipped; gawk and mawk here do not, so the mount tests cannot see it (2026-10-22).
        for f in [SCRIPT] + [os.path.join(DIR, "src", n) for n in os.listdir(os.path.join(DIR, "src"))]:
            self.assertNotIn("[^\\/]", read(f), f)


def main():
    if os.geteuid() == 0 and not IN_NS and shutil.which("unshare"):
        if subprocess.run(["unshare", "-m", "--propagation", "private", "true"], capture_output=True).returncode == 0:
            env = dict(os.environ, DEX_IN_NS="1")
            os.execvpe("unshare", ["unshare", "-m", "--propagation", "private", sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env)
    unittest.main()


if __name__ == "__main__":
    main()

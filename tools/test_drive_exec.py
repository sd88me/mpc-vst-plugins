#!/usr/bin/env python3
"""Tests for tools/mpc_patch/drive_exec/drive-exec-patch.sh (the executable-mount patch for a noexec drive).

The mount mechanism is tested for real: as root, in a private mount namespace (`unshare -m`), a tmpfs mounted noexec at
/media/<name> stands for the Force's SSD, and a small shared library is really dlopen()ed before the patch, with it, and after
removing it. systemctl and pidof are shims; the files the patch writes go to a scratch folder (DEX_PREFIX). Without root,
unshare or a C compiler the tests that need them are skipped. Run:  python3 tools/test_drive_exec.py   (CI: sudo)
"""
import ctypes
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "mpc_patch", "drive_exec")
SCRIPT = os.path.join(DIR, "drive-exec-patch.sh")
IN_NS = os.environ.get("DEX_IN_NS") == "1"
SH = shutil.which("dash") or shutil.which("sh")
GCC = shutil.which("gcc") or shutil.which("cc")
needs_ns = unittest.skipUnless(IN_NS, "needs root and `unshare -m` (run this file directly, as root)")

PROBE_C = "int VSTPluginMain(void) { return 42; }\n"
SHIM_SYSTEMCTL = textwrap.dedent("""\
    #!/bin/sh
    echo "$*" >> "$DEX_SHIMLOG"
    [ "$1" = enable ] && [ -n "${DEX_FAIL_ENABLE:-}" ] && exit 1
    exit 0
    """)
SHIM_PIDOF = textwrap.dedent("""\
    #!/bin/sh
    [ -f "$DEX_PIDFILE" ] && { cat "$DEX_PIDFILE"; exit 0; }
    exit 1
    """)


def write(path, text, mode=None):
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path) as f:
        return f.read()


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


class Rig(unittest.TestCase):
    """A scratch root, shims, and helpers to make drives."""

    @classmethod
    def setUpClass(cls):
        if not IN_NS:
            return
        os.makedirs("/media", exist_ok=True)
        subprocess.run(["mount", "-t", "tmpfs", "tmpfs", "/media"], check=True)   # hides the real /media inside this namespace only
        cls.work = tempfile.mkdtemp(prefix="fve-")
        cls.probe = None
        if GCC:
            src = os.path.join(cls.work, "probe.c")
            write(src, PROBE_C)
            cls.probe = os.path.join(cls.work, "probe.so")
            if subprocess.run([GCC, "-shared", "-fPIC", "-o", cls.probe, src], capture_output=True).returncode != 0:
                cls.probe = None

    @classmethod
    def tearDownClass(cls):
        if IN_NS:
            shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not IN_NS:
            return
        self.root = tempfile.mkdtemp(prefix="root-", dir=self.work)       # stands for / (DEX_PREFIX)
        self.shims = os.path.join(self.root, "shims")
        os.makedirs(self.shims)
        for name, body in (("systemctl", SHIM_SYSTEMCTL), ("pidof", SHIM_PIDOF)):
            write(os.path.join(self.shims, name), body, 0o755)
        self.log = os.path.join(self.root, "systemctl.log")
        self.pidfile = os.path.join(self.root, "pid")
        self.env = dict(os.environ, DEX_PREFIX=self.root, DEX_SHIMLOG=self.log, DEX_PIDFILE=self.pidfile,
                        PATH=self.shims + ":" + os.environ["PATH"])
        self.drives = []
        self.addCleanup(self.cleanup_mounts)

    def cleanup_mounts(self):
        for d in sorted(self.drives, key=len, reverse=True):
            sh("umount '%s/Synths' 2>/dev/null; umount '%s/vst' 2>/dev/null; umount '%s' 2>/dev/null" % (d, d, d))

    def make_drive(self, name, options="noexec,nosuid,nodev"):
        path = "/media/" + name
        os.makedirs(path, exist_ok=True)
        subprocess.run(["mount", "-t", "tmpfs", "-o", options + ",size=8m", "tmpfs", path], check=True)
        self.drives.append(path)
        return path

    def run_patch(self, *args, stdin=""):
        return subprocess.run([SH, SCRIPT, *args], env=self.env, input=stdin, capture_output=True, text=True, timeout=120)

    def mountinfo(self, path):
        esc = path.replace("\\", "\\134").replace(" ", "\\040")
        rows = [l.split() for l in read("/proc/self/mountinfo").splitlines() if l.split()[4] == esc]
        return rows

    def options(self, path):
        rows = self.mountinfo(path)
        return rows[-1][5] if rows else None

    def state(self, out):
        lines = [l for l in out.splitlines() if l.startswith("STATE ")]
        self.assertEqual(len(lines), 1, out)
        self.assertEqual(out.strip().splitlines()[-1], lines[0], "the STATE line must be last")
        return dict(kv.split("=") for kv in lines[0].split()[1:])

    def dlopen_ok(self, so):
        r = subprocess.run([sys.executable, "-c", "import ctypes,sys; ctypes.CDLL(sys.argv[1]).VSTPluginMain; print('OK')", so], capture_output=True, text=True)
        return r.returncode == 0 and "OK" in r.stdout


@needs_ns
class Mechanism(Rig):
    def test_install_makes_only_the_synths_folder_executable_and_removal_undoes_it(self):
        drive = self.make_drive("SSD - Force")                         # a name with spaces, like a real SSD volume
        plugin = os.path.join(drive, "Synths", "me - VST - X")
        os.makedirs(plugin)
        if self.probe:
            shutil.copy(self.probe, os.path.join(plugin, "probe.so"))
        parent_before = (self.mountinfo(drive)[0][0], self.options(drive))
        so = os.path.join(plugin, "probe.so")
        if self.probe:
            self.assertFalse(self.dlopen_ok(so), "a noexec drive must refuse to map the library")
        st = self.state(self.run_patch("status", "--root", drive).stdout)
        self.assertEqual((st["state"], st["supported"]), ("stock", "1"))
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        target = drive + "/Synths"
        self.assertNotIn("noexec", self.options(target).split(","), "the folder must allow execution")
        self.assertIn("noexec", self.options(drive).split(","), "the drive itself stays noexec")
        self.assertEqual((self.mountinfo(drive)[0][0], self.options(drive)), parent_before, "the parent mount is untouched")
        if self.probe:
            self.assertTrue(self.dlopen_ok(so), "the library must load from the executable folder")
            outside = os.path.join(drive, "outside.so")
            shutil.copy(self.probe, outside)
            self.assertFalse(self.dlopen_ok(outside), "files outside the folder stay blocked")
        cfg = read(self.root + "/etc/drive-exec/config")
        self.assertEqual(cfg, "DRIVE_ROOT='/media/SSD - Force'\nEXEC_DIR='Synths'\n")
        calls = read(self.log)
        self.assertIn("enable --now drive-exec.timer", calls)
        for f in ("etc/systemd/system/drive-exec.service", "etc/systemd/system/drive-exec.timer",
                  "usr/lib/systemd/system/drive-exec-bootstrap.service"):
            self.assertTrue(os.path.isfile(os.path.join(self.root, f)), f)
        self.assertTrue(os.path.islink(self.root + "/usr/lib/systemd/system/multi-user.target.wants/drive-exec-bootstrap.service"))
        self.assertTrue(os.listdir(self.root + "/data/mpc-vst-plugins/backups"), "a patch-only backup is made")
        st = self.state(self.run_patch("status").stdout)
        self.assertEqual((st["state"], st["supported"], st["backup"]), ("patched", "1", "1"))
        # remove it
        r = self.run_patch("uninstall", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.mountinfo(target)), 0, "the executable mount is gone")
        self.assertEqual((self.mountinfo(drive)[0][0], self.options(drive)), parent_before)
        if self.probe:
            self.assertFalse(self.dlopen_ok(so), "after removal the drive is noexec again")
        self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"))
        self.assertFalse(os.path.exists(self.root + "/etc/systemd/system/drive-exec.timer"))
        self.assertFalse(os.path.exists(self.root + "/usr/lib/systemd/system/drive-exec-bootstrap.service"))
        self.assertTrue(os.path.isdir(plugin), "plugins and skins are never touched")
        st = self.state(self.run_patch("status", "--root", drive).stdout)
        self.assertEqual(st["state"], "stock")

    def test_verify_says_whether_mpc_itself_sees_the_executable_folder(self):
        def vline(out):
            ls = [l for l in out.splitlines() if l.startswith("VERIFY ")]
            self.assertEqual(len(ls), 1, out)
            self.assertEqual(out.strip().splitlines()[-1], ls[0], "the VERIFY line must be last")
            return dict(kv.split("=") for kv in ls[0].split()[1:])
        r = self.run_patch("verify")
        self.assertEqual((r.returncode, vline(r.stdout)["result"]), (1, "not-installed"))
        drive = self.make_drive("SD Card")
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("VERIFY result=mpc-stopped", r.stdout, "install ends by verifying")
        self.assertEqual(vline(self.run_patch("verify").stdout)["result"], "mpc-stopped")
        write(self.pidfile, "4242\n")
        blind = os.path.join(self.root, "mpc-mountinfo")      # a mount namespace that never got the bind mount
        write(blind, "\n".join(l for l in read("/proc/self/mountinfo").splitlines() if "/Synths" not in l) + "\n")
        self.env["DEX_MPC_MOUNTINFO"] = blind
        r = self.run_patch("verify")
        self.assertEqual((r.returncode, vline(r.stdout)["result"]), (1, "mpc-blind"))
        self.assertIn("restart", r.stdout)
        self.env["DEX_MPC_MOUNTINFO"] = "/proc/self/mountinfo"
        r = self.run_patch("verify")
        self.assertEqual((r.returncode, vline(r.stdout)["result"], vline(r.stdout)["plugins"]), (0, "no-plugins", "0"))
        os.makedirs(drive + "/Synths/me - VST - X")
        write(drive + "/Synths/me - VST - X/plugin-meta.xml", "<x/>")
        v = vline(self.run_patch("verify").stdout)
        self.assertEqual((v["result"], v["plugins"]), ("ok", "1"))
        self.run_patch("uninstall", "--confirmed")

    def test_the_original_vst_folder_works_too(self):
        drive = self.make_drive("ForceHD")
        r = self.run_patch("install", "--root", drive, "--exec-dir", "vst", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("noexec", self.options(drive + "/vst").split(","))
        self.assertIn("noexec", self.options(drive).split(","))
        self.assertEqual(len(self.mountinfo(drive + "/Synths")), 0)

    def test_applying_twice_does_not_stack_mounts(self):
        drive = self.make_drive("SSD - Force")
        self.assertEqual(self.run_patch("install", "--root", drive, "--confirmed").returncode, 0)
        env = dict(self.env, DRIVE_EXEC_CONFIG=self.root + "/etc/drive-exec/config", DRIVE_EXEC_STATE=self.root + "/run/drive-exec")
        for _ in range(3):
            r = subprocess.run([SH, self.root + "/etc/drive-exec/drive-exec.sh", "apply"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.mountinfo(drive + "/Synths")), 1)

    def test_a_drive_that_is_not_there_is_waited_for_not_an_error(self):
        drive = self.make_drive("SSD - Force")
        self.assertEqual(self.run_patch("install", "--root", drive, "--confirmed").returncode, 0)
        sh("umount '%s/Synths'" % drive)
        env = dict(self.env, DRIVE_EXEC_CONFIG=self.root + "/etc/drive-exec/config", DRIVE_EXEC_STATE=self.root + "/run/drive-exec")
        st = self.state(self.run_patch("status").stdout)
        self.assertEqual(st["state"], "partial", "installed, but the executable mount is not active")
        sh("umount '%s'" % drive)
        r = subprocess.run([SH, self.root + "/etc/drive-exec/drive-exec.sh", "apply"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Waiting for", r.stdout)

    def test_a_loaded_plugin_blocks_removal_until_it_is_gone(self):
        if not self.probe:
            self.skipTest("no C compiler")
        drive = self.make_drive("SSD - Force")
        os.makedirs(drive + "/Synths/x")
        shutil.copy(self.probe, drive + "/Synths/x/probe.so")
        self.assertEqual(self.run_patch("install", "--root", drive, "--confirmed").returncode, 0)
        holder = subprocess.Popen([sys.executable, "-c", "import ctypes,sys,time; ctypes.CDLL(sys.argv[1]); print('loaded', flush=True); time.sleep(60)", drive + "/Synths/x/probe.so"], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "loaded")
            write(self.pidfile, str(holder.pid))
            r = self.run_patch("uninstall", "--confirmed")
            self.assertNotEqual(r.returncode, 0, "removal must refuse while MPC maps a plugin from the folder")
            self.assertIn("MPC is using a plugin", r.stdout)
            self.assertEqual(len(self.mountinfo(drive + "/Synths")), 1, "the mount stays")
            self.assertTrue(os.path.isdir(self.root + "/etc/drive-exec"), "and so do the files")
        finally:
            holder.send_signal(signal.SIGKILL)
            holder.wait()
            holder.stdout.close()
        os.remove(self.pidfile)
        self.assertEqual(self.run_patch("uninstall", "--confirmed").returncode, 0)

    def test_a_failed_install_rolls_everything_back(self):
        drive = self.make_drive("SSD - Force")
        self.env["DEX_FAIL_ENABLE"] = "1"
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rolling back", r.stdout)
        self.assertEqual(len(self.mountinfo(drive + "/Synths")), 0, "the mount is removed again")
        self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"))
        self.assertFalse(os.path.exists(self.root + "/etc/systemd/system/drive-exec.timer"))
        self.assertFalse(os.path.exists(self.root + "/usr/lib/systemd/system/drive-exec-bootstrap.service"))
        self.assertIn("noexec", self.options(drive).split(","))


@needs_ns
class Refusals(Rig):
    def test_nothing_is_installed_without_the_typed_word(self):
        drive = self.make_drive("SSD - Force")
        r = self.run_patch("install", "--root", drive, stdin="")     # empty stdin: cancelled
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cancelled", r.stderr)
        self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"))
        self.assertEqual(len(self.mountinfo(drive + "/Synths")), 0)
        r = self.run_patch("install", "--root", drive, stdin="PATCH\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_unsafe_or_unsuitable_names_are_refused(self):
        drive = self.make_drive("SSD - Force")
        for args, why in ((("--root", "/media/x; rm -rf /"), "shell characters"), (("--root", "/media/.."), "dot dot"),
                          (("--root", "/media/a/b"), "two levels"), (("--root", "/etc"), "not under /media"),
                          (("--root", "/media/az01-internal"), "internal storage"), (("--root", "/media/acvs-synths"), "system storage"),
                          (("--root", drive, "--exec-dir", "../x"), "folder escape"), (("--root", drive, "--exec-dir", ".hidden"), "hidden folder"),
                          (("--root", drive, "--exec-dir", "a'b"), "quote in the folder"), (("--root", drive, "--exec-dir", "a/b"), "folder with a slash")):
            r = self.run_patch("install", *args, "--confirmed")
            self.assertNotEqual(r.returncode, 0, why)
            self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"), why)

    def test_a_mounted_drive_with_a_hostile_name_is_refused(self):
        # these really are mounted noexec; only the name check stands between them and a config that a root service sources
        for name in ("bad'name", "a$(touch /tmp/fve-pwned)", "semi;colon", "back\\slash", "-dash"[1:] + "`x`"):
            drive = self.make_drive(name)
            r = self.run_patch("install", "--root", drive, "--confirmed")
            self.assertNotEqual(r.returncode, 0, name)
            self.assertIn("not a usable drive path", r.stderr, name)
            self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"), name)
            self.assertEqual(len(self.mountinfo(drive + "/Synths")), 0, name)
        self.assertFalse(os.path.exists("/tmp/fve-pwned"))
        # and with exactly one such drive, the automatic choice does not pick it either
        self.assertEqual(self.state(self.run_patch("status").stdout)["reason"], "no-noexec-drive")

    def test_a_drive_that_already_allows_execution_is_left_alone(self):
        drive = self.make_drive("Open", options="nosuid,nodev")
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not needed", r.stderr)
        st = self.state(self.run_patch("status", "--root", drive).stdout)
        self.assertEqual((st["state"], st["supported"], st["reason"]), ("unsupported", "0", "not-needed"))

    def test_the_drive_is_found_by_itself_only_when_there_is_exactly_one(self):
        st = self.state(self.run_patch("status").stdout)
        self.assertEqual((st["state"], st["supported"], st["reason"]), ("unsupported", "0", "no-noexec-drive"))
        a = self.make_drive("SSD - Force")
        out = self.run_patch("status").stdout
        self.assertIn("/media/SSD - Force", out)
        self.assertEqual(self.state(out)["state"], "stock")
        self.make_drive("Other")
        r = self.run_patch("install", "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--root", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"))
        os.rmdir(a + "/Synths") if os.path.isdir(a + "/Synths") else None
        sh("umount /media/Other")
        r = self.run_patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.mountinfo(a + "/Synths")), 1)

    def test_a_second_install_and_an_existing_mount_are_refused(self):
        drive = self.make_drive("SSD - Force")
        self.assertEqual(self.run_patch("install", "--root", drive, "--confirmed").returncode, 0)
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already installed", r.stderr)
        self.assertEqual(len(self.mountinfo(drive + "/Synths")), 1)

    def test_a_foreign_mount_on_the_folder_is_refused(self):
        drive = self.make_drive("SSD - Force")
        os.makedirs(drive + "/Synths")
        subprocess.run(["mount", "--bind", drive + "/Synths", drive + "/Synths"], check=True)
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already a mount point", r.stderr)
        self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"))

    def test_another_version_is_reported_and_never_touched(self):
        drive = self.make_drive("SSD - Force")
        os.makedirs(self.root + "/etc/drive-exec")
        write(self.root + "/etc/drive-exec/VERSION", "0.1.3\n")
        st = self.state(self.run_patch("status", "--root", drive).stdout)
        self.assertEqual((st["state"], st["supported"], st["reason"]), ("unsupported", "0", "other-version"))
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        r = self.run_patch("uninstall", "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read(self.root + "/etc/drive-exec/VERSION"), "0.1.3\n")

    def test_the_contributors_original_install_is_reported_and_never_touched(self):
        drive = self.make_drive("SSD - Force")
        os.makedirs(self.root + "/etc/force-vst-exec")                  # where "ForceHD VST Exec" 0.1.3 installs itself
        write(self.root + "/etc/force-vst-exec/VERSION", "0.1.3\n")
        st = self.state(self.run_patch("status", "--root", drive).stdout)
        self.assertEqual((st["state"], st["supported"], st["reason"]), ("unsupported", "0", "other-install"))
        r = self.run_patch("install", "--root", drive, "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("original ForceHD VST Exec", r.stderr)
        self.assertEqual(len(self.mountinfo(drive + "/Synths")), 0)
        self.assertEqual(read(self.root + "/etc/force-vst-exec/VERSION"), "0.1.3\n", "his files are never touched")
        self.assertFalse(os.path.exists(self.root + "/etc/drive-exec"))

    def test_the_helper_rejects_a_config_with_anything_but_plain_names(self):
        drive = self.make_drive("SSD - Force")
        self.assertEqual(self.run_patch("install", "--root", drive, "--confirmed").returncode, 0)
        env = dict(self.env, DRIVE_EXEC_CONFIG=self.root + "/etc/drive-exec/config", DRIVE_EXEC_STATE=self.root + "/run/drive-exec")
        for bad in ("DRIVE_ROOT='/media/x$(touch /tmp/pwned)'\nEXEC_DIR='Synths'\n", "DRIVE_ROOT='/media/..'\nEXEC_DIR='Synths'\n",
                    "DRIVE_ROOT='/media/SSD - Force'\nEXEC_DIR='../etc'\n", "DRIVE_ROOT='/media/az01-internal'\nEXEC_DIR='Synths'\n"):
            write(self.root + "/etc/drive-exec/config", bad)
            r = subprocess.run([SH, self.root + "/etc/drive-exec/drive-exec.sh", "status"], env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertRegex(r.stdout, "Unsupported|internal")
        self.assertFalse(os.path.exists("/tmp/pwned"))


class Generated(unittest.TestCase):
    def test_the_script_embeds_exactly_the_files_in_src(self):
        text = read(SCRIPT)
        found = dict((m.group(1), m.group(3)) for m in re.finditer(r'cat > "\$d/([^"]+)" <<\'(DEX_EOF_\w+)\'\n(.*?)\n\2\n', text, re.S))
        self.assertEqual(set(found), {"drive-exec.sh", "uninstall.sh", "bootstrap.sh", "root-bootstrap.sh", "drive-exec.service",
                                      "drive-exec.timer", "drive-exec-bootstrap.service"})
        for name, body in found.items():
            self.assertEqual(body + "\n", read(os.path.join(DIR, "src", name)), name)

    def test_the_script_is_up_to_date_with_its_generator(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        subprocess.run([sys.executable, os.path.join(DIR, "build_script.py"), os.path.join(out, "x.sh")], check=True, capture_output=True)
        self.assertEqual(read(SCRIPT), read(os.path.join(out, "x.sh")), "run tools/mpc_patch/drive_exec/build_script.py and commit the result")

    def test_every_shell_file_parses(self):
        for f in [SCRIPT] + [os.path.join(DIR, "src", n) for n in os.listdir(os.path.join(DIR, "src")) if n.endswith(".sh")]:
            r = subprocess.run([SH, "-n", f], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + r.stderr)


def main():
    if os.geteuid() == 0 and not IN_NS and shutil.which("unshare"):
        probe = subprocess.run(["unshare", "-m", "--propagation", "private", "true"], capture_output=True)
        if probe.returncode == 0:
            env = dict(os.environ, DEX_IN_NS="1")
            os.execvpe("unshare", ["unshare", "-m", "--propagation", "private", sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env)
    unittest.main()


if __name__ == "__main__":
    main()

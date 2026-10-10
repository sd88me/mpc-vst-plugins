#!/usr/bin/env python3
"""Offline tests for tools/mpc_patch/hwremap/hwremap-patch.sh.

A scratch folder stands for the device (HW_PREFIX). systemctl and pidof are shims. The library the script
unpacks is compared with src/hwremap.so when that file is present (it is not committed; the generated script is).
The hwremap.c host test is compiled and run when the compiler accepts it (Linux; it uses pipe2).
"""
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "mpc_patch", "hwremap")
SCRIPT = os.path.join(DIR, "hwremap-patch.sh")
SO = os.path.join(DIR, "src", "hwremap.so")
LIVE = os.path.join(DIR, "configs", "mpc-live.conf")
FORCE = os.path.join(DIR, "configs", "force.conf")
SH = shutil.which("dash") or shutil.which("sh")

LAUNCHER = textwrap.dedent("""\
    #!/bin/sh
    export LD_PRELOAD="customBufferSizeMPC.so $CURSOR_SO"
    LD_PRELOAD="/usr/lib/libforce_cursor.so"
    LD_PRELOAD=/usr/lib/foo.so
    # a comment about LD_PRELOAD= must stay a comment
    """)
LAUNCHER_PATCHED = textwrap.dedent("""\
    #!/bin/sh
    export LD_PRELOAD="customBufferSizeMPC.so /usr/lib/hwremap.so $CURSOR_SO"
    LD_PRELOAD="/usr/lib/libforce_cursor.so /usr/lib/hwremap.so"
    LD_PRELOAD=/usr/lib/foo.so:/usr/lib/hwremap.so
    # a comment about LD_PRELOAD= must stay a comment
    """)

SHIM_SYSTEMCTL = textwrap.dedent("""\
    #!/bin/sh
    echo "$*" >> "$HW_SHIMLOG"
    case "$1" in
        cat)
            case "$2" in
                acvs) [ "${HW_NO_ACVS:-}" = 1 ] && exit 1; exit 0 ;;
                inmusic-mpc) [ "${HW_INMUSIC:-}" = 1 ] && exit 0; exit 1 ;;
                *) exit 1 ;;
            esac
            ;;
        show)
            printf '%s\\n' "${HW_ENVIRONMENT:-Environment=LD_PRELOAD=/usr/lib/libforce_cursor.so}"
            ;;
        stop|start|daemon-reload) exit 0 ;;
    esac
    exit 0
    """)
SHIM_PIDOF = textwrap.dedent("""\
    #!/bin/sh
    if [ -n "${HW_PID:-}" ]; then echo "$HW_PID"; exit 0; fi
    exit 1
    """)


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path) as f:
        return f.read()


RULE = __import__("re").compile(
    r"^(log|hold|longms|holdms|dblms|touchms)\s+\d+$"
    r"|^(dbl|held|tap|long)?\s*\d+\s+([dubphxt]?[0-9a-fA-Fx]+(,\d+)?|m\w+)(\s+[dubphxt]?[0-9a-fA-Fx]+(,\d+)?)*$"
    r"|^combo\s+\d+\s+\d+(\s+\S+)+$")


def rules(text):
    """The active rule lines of a config (comments and blanks dropped)."""
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


class Rig(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="hwremap-")
        self.root = os.path.join(self.work, "root")
        self.shims = os.path.join(self.work, "shims")
        os.makedirs(self.shims)
        write(os.path.join(self.shims, "systemctl"), SHIM_SYSTEMCTL, 0o755)
        write(os.path.join(self.shims, "pidof"), SHIM_PIDOF, 0o755)
        self.log = os.path.join(self.work, "systemctl.log")
        self.env = dict(os.environ, HW_PREFIX=self.root, HW_SHIMLOG=self.log,
                        PATH=self.shims + os.pathsep + os.environ["PATH"])
        self.addCleanup(shutil.rmtree, self.work, True)

    def launcher(self, text=LAUNCHER):
        write(os.path.join(self.root, "usr", "bin", "az01-launch-MPC"), text, 0o755)

    def patch(self, *args, stdin="", **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run([SH, SCRIPT, *args], env=e, input=stdin, capture_output=True, text=True, timeout=60)

    def state(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = [l for l in proc.stdout.splitlines() if l.startswith("STATE ")]
        self.assertEqual(len(lines), 1, proc.stdout)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], lines[0])
        return dict(kv.split("=", 1) for kv in lines[0].split()[1:])

    def so_bytes(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return f.read()


class Contract(Rig):
    def test_status_without_a_device_tree_is_not_root(self):
        if os.geteuid() == 0:
            self.skipTest("this process is root, so the not-root refusal cannot be seen")
        env = dict(os.environ, PATH=self.env["PATH"])
        r = subprocess.run([SH, SCRIPT, "status"], env=env, capture_output=True, text=True, timeout=30)
        st = self.state(r)
        self.assertEqual((st["state"], st["reason"]), ("unsupported", "not-root"))

    def test_unknown_layout(self):
        st = self.state(self.patch("status", HW_NO_ACVS="1"))
        self.assertEqual((st["state"], st["supported"], st["reason"]), ("unsupported", "0", "unknown-layout"))

    def test_missing_tool(self):
        env = dict(self.env, PATH=self.shims)
        r = subprocess.run([SH, SCRIPT, "status"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(self.state(r)["reason"], "tools")

    def test_launcher_install_uninstall_round_trip(self):
        self.launcher()
        st = self.state(self.patch("status"))
        self.assertEqual((st["state"], st["supported"], st["backup"]), ("stock", "1", "0"))
        r = self.patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")), LAUNCHER_PATCHED)
        blob = self.so_bytes("usr/lib/hwremap.so")
        self.assertEqual(blob[:4], b"\x7fELF")
        self.assertEqual(blob[4], 1)
        self.assertEqual(blob[18], 40)  # EM_ARM
        if os.path.isfile(SO):
            with open(SO, "rb") as f:
                self.assertEqual(blob, f.read())
        self.assertTrue(os.stat(os.path.join(self.root, "usr/lib", "hwremap.so")).st_mode & stat.S_IXUSR)
        self.assertEqual(read(os.path.join(self.root, "sdcard", "hwremap.conf")), read(LIVE))
        self.assertEqual(read(os.path.join(self.root, "data", "hwremap", "VERSION")).strip(), "0.2.0")
        self.assertEqual(read(os.path.join(self.root, "data", "hwremap", "STYLE")).strip(), "launcher")
        log = read(self.log)
        self.assertEqual(log.count("stop acvs\n"), 1)
        self.assertEqual(log.count("start acvs\n"), 1)
        self.assertNotIn("daemon-reload", log)
        self.assertTrue(os.listdir(os.path.join(self.root, "data", "mpc-vst-plugins", "backups")))
        maps = os.path.join(self.work, "maps")
        write(maps, "7f000000-7f001000 r-xp /usr/lib/hwremap.so\n")
        st = self.state(self.patch("status", HW_MAPS=maps, HW_PID="42"))
        self.assertEqual((st["state"], st["supported"], st["backup"]), ("patched", "1", "1"))
        write(maps, "7f000000-7f001000 r-xp /usr/bin/MPC\n")
        st = self.state(self.patch("status", HW_MAPS=maps, HW_PID="42"))
        self.assertEqual((st["state"], st["reason"]), ("partial", "not-loaded"))
        st = self.state(self.patch("status"))
        self.assertEqual((st["state"], st["reason"]), ("partial", "not-running"))
        again = self.patch("install", "--confirmed")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already installed", again.stderr)
        open(self.log, "w").close()
        r = self.patch("uninstall", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")), LAUNCHER)
        self.assertFalse(os.path.exists(os.path.join(self.root, "usr", "lib", "hwremap.so")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "sdcard", "hwremap.conf")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap")))
        log = read(self.log)
        self.assertIn("stop acvs", log)
        self.assertIn("start acvs", log)
        st = self.state(self.patch("status"))
        self.assertEqual(st["state"], "stock")

    def test_layout_flag_and_an_edited_config_is_kept(self):
        self.launcher()
        r = self.patch("install", "--layout", "force", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conf = os.path.join(self.root, "sdcard", "hwremap.conf")
        default = read(conf)
        self.assertIn("combo 9 114 b2 t280,487", default)
        with open(conf, "a") as f:
            f.write("# mine\n")
        r = self.patch("uninstall", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(conf), default + "# mine\n")
        self.assertIn("Left", r.stdout)

    def test_existing_config_is_not_overwritten(self):
        self.launcher()
        conf = os.path.join(self.root, "sdcard", "hwremap.conf")
        write(conf, "log 1\n")
        r = self.patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(conf), "log 1\n")
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap", "config.default")))

    def test_typed_word_and_a_wrong_word(self):
        self.launcher()
        bad = self.patch("install", stdin="no\n")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("cancelled", bad.stderr)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")), LAUNCHER)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "mpc-vst-plugins", "backups")))
        ok = self.patch("install", stdin="PATCH\n")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("/usr/lib/hwremap.so", read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")))

    def test_failure_after_the_launcher_edit_rolls_back_and_starts_mpc(self):
        self.launcher()
        r = self.patch("install", "--confirmed", HW_FAIL="after-launcher")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("putting back", r.stdout)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")), LAUNCHER)
        self.assertFalse(os.path.exists(os.path.join(self.root, "usr", "lib", "hwremap.so")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap", "VERSION")))
        log = read(self.log)
        self.assertIn("stop acvs", log)
        self.assertIn("start acvs", log)

    def test_an_unquoted_preload_is_joined_with_a_colon(self):
        # `LD_PRELOAD=a.so cmd` must stay one assignment: a space would make hwremap.so the command
        self.launcher("#!/bin/sh\nLD_PRELOAD=/usr/lib/foo.so env\n")
        r = self.patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC"))
        self.assertEqual(text, "#!/bin/sh\nLD_PRELOAD=/usr/lib/foo.so:/usr/lib/hwremap.so env\n")
        seen = subprocess.run([SH, "-c", text], capture_output=True, text=True, timeout=30).stdout.splitlines()
        self.assertIn("LD_PRELOAD=/usr/lib/foo.so:/usr/lib/hwremap.so", seen)

    def test_the_library_unpacks_the_same_under_gawk_in_a_utf8_locale(self):
        # gawk writes printf "%c" values above 127 as multi-byte characters in a UTF-8 locale: the script forces LC_ALL=C
        gawk = shutil.which("gawk")
        if not gawk:
            self.skipTest("gawk is not installed")
        os.symlink(gawk, os.path.join(self.shims, "awk"))
        text = read(SCRIPT)
        a = text.index("\n", text.index("<<'HW_SO_HEX'")) + 1
        want = bytes.fromhex(text[a:text.index("\nHW_SO_HEX", a)].replace("\n", ""))
        self.launcher()
        r = self.patch("install", "--confirmed", LC_ALL="C.UTF-8", LANG="C.UTF-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.so_bytes("usr/lib/hwremap.so"), want)

    def test_a_library_that_unpacks_wrongly_is_never_installed(self):
        text = read(SCRIPT)
        a = text.index("\n", text.index("<<'HW_SO_HEX'")) + 1
        digit = "0" if text[a] != "0" else "1"
        bad = os.path.join(self.work, "bad.sh")
        write(bad, text[:a] + digit + text[a + 1:])   # one hex digit of the embedded library changed
        self.launcher()
        r = subprocess.run([SH, bad, "install", "--confirmed"], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("did not unpack correctly", r.stderr)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")), LAUNCHER)
        self.assertFalse(os.path.exists(os.path.join(self.root, "usr", "lib", "hwremap.so")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap", "VERSION")))
        log = read(self.log)
        self.assertEqual(log.count("stop acvs"), log.count("start acvs"), log)   # MPC is never left stopped

    def test_cancelled_before_any_write(self):
        self.launcher()
        r = self.patch("install", "--confirmed", HW_FAIL="before-write")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("putting back", r.stdout)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")), LAUNCHER)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap")))

    def test_hand_install_and_other_version_are_refused(self):
        self.launcher(LAUNCHER_PATCHED)
        st = self.state(self.patch("status"))
        self.assertEqual(st["reason"], "hand-install")
        r = self.patch("install", "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("without this patch's marker", r.stderr)
        self.launcher()
        mark = os.path.join(self.root, "data", "hwremap")
        write(os.path.join(mark, "VERSION"), "0.0.1\n")
        st = self.state(self.patch("status"))
        self.assertEqual(st["reason"], "other-version")
        r = self.patch("install", "--confirmed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already installed", r.stderr)

    def test_dropin_keeps_the_existing_preload(self):
        r = self.patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        drop = os.path.join(self.root, "etc", "systemd", "system", "acvs.service.d", "hwremap.conf")
        body = read(drop)
        self.assertEqual(body, '[Service]\nEnvironment="LD_PRELOAD=/usr/lib/libforce_cursor.so /data/hwremap/hwremap.so"\n')
        self.assertTrue(os.path.isfile(os.path.join(self.root, "data", "hwremap", "hwremap.so")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "usr", "lib", "hwremap.so")))
        self.assertIn("dbl 37 d49 b9 u49", read(os.path.join(self.root, "sdcard", "hwremap.conf")))
        self.assertIn("daemon-reload", read(self.log))
        maps = os.path.join(self.work, "maps")
        write(maps, "/data/hwremap/hwremap.so\n")
        self.assertEqual(self.state(self.patch("status", HW_MAPS=maps, HW_PID="7"))["state"], "patched")
        open(self.log, "w").close()
        r = self.patch("uninstall", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(drop))
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap")))
        self.assertIn("daemon-reload", read(self.log))

    def test_a_launcher_without_ld_preload_takes_the_dropin(self):
        # a Force: /usr/bin/az01-launch-MPC exists (the service runs it) but sets no LD_PRELOAD
        self.launcher("#!/bin/sh\nexec setarch -R -- /usr/bin/MPC \"$@\"\n")
        r = self.patch("install", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("style:   dropin", r.stdout)
        self.assertEqual(read(os.path.join(self.root, "usr", "bin", "az01-launch-MPC")),
                         "#!/bin/sh\nexec setarch -R -- /usr/bin/MPC \"$@\"\n")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "data", "hwremap", "hwremap.so")))

    def test_the_terminal_is_only_opened_after_a_subshell_check(self):
        # BusyBox ends the shell when "read < /dev/tty" cannot open it (no tty over ssh), even with 2>/dev/null
        # and || after it; dash does not, so run the check on the text
        for n, line in enumerate(read(SCRIPT).splitlines(), 1):
            if "/dev/tty" in line and not line.startswith("tty_ok()"):
                self.assertIn("tty_ok", line, "line %d opens /dev/tty without tty_ok: %s" % (n, line))

    def test_inmusic_service_and_a_hostile_preload(self):
        r = self.patch("install", "--confirmed", HW_NO_ACVS="1", HW_INMUSIC="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "etc", "systemd", "system", "inmusic-mpc.service.d", "hwremap.conf")))
        self.assertIn("stop inmusic-mpc", read(self.log))
        # a fresh tree: a preload we must not write back into a unit file
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        open(self.log, "w").close()
        r = self.patch("install", "--confirmed", HW_ENVIRONMENT='Environment=LD_PRELOAD=/usr/lib/a.so $EVIL')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("plain list", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap", "hwremap.so")))
        self.assertIn("start acvs", read(self.log))  # MPC was stopped, then the rollback started it

    def test_uninstall_when_absent_is_success(self):
        r = self.patch("uninstall", "--confirmed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Not installed", r.stdout)

    def test_help_and_a_bad_flag(self):
        self.assertEqual(self.patch("help").returncode, 0)
        self.assertNotEqual(self.patch("install", "--nope").returncode, 0)

    # --- options (the Force map is made of option blocks)
    def conf(self):
        return read(os.path.join(self.root, "sdcard", "hwremap.conf"))

    def fresh(self):
        """Uninstall and clear what a second install in the same second would trip over."""
        self.assertEqual(self.patch("uninstall", "--confirmed").returncode, 0)
        shutil.rmtree(os.path.join(self.root, "sdcard"), True)
        shutil.rmtree(os.path.join(self.root, "data", "mpc-vst-plugins"), True)

    def install(self, *args, **kw):
        r = self.patch("install", "--confirmed", *args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.conf()

    def test_options_lists_the_force_map_and_the_live_map_has_none(self):
        r = self.patch("options", "--layout", "force")
        self.assertEqual(r.returncode, 0, r.stderr)
        names = [l.split()[0] for l in r.stdout.splitlines()[1:]]
        self.assertEqual(names, ["mixer-master", "mixer-tabs", "edit-editor", "clip-arrange", "menu-main-mode",
                                 "skipback", "knobs-short", "knobs-long", "knobs-double"])
        self.assertRegex(r.stdout, r"knobs-short\s+off")
        self.assertRegex(r.stdout, r"mixer-tabs\s+on")
        self.assertIn("has no options", self.patch("options", "--layout", "mpc-live").stdout)

    def test_default_force_install_has_the_non_knobs_options_and_no_markers(self):
        text = self.install("--layout", "force")
        self.assertNotIn("#@", text)
        self.assertNotIn("this whole file is also a valid config", text)
        got = rules(text)
        for line in ("dbl 11 b5", "dbl 37 d49 b9 u49", "combo 9 114 b2 t280,487", "dbl 2 t331,655",
                     "combo 11 112 t1232,540", "combo 11 115 t1232,421", "hold 49"):
            self.assertIn(line, got)
        for line in got:
            self.assertTrue(RULE.match(line), line)
        self.assertFalse([l for l in got if l.startswith(("tap 1", "long 1", "held 1", "dbl 1 "))])
        self.assertEqual(read(os.path.join(self.root, "data", "hwremap", "OPTIONS")).split(),
                         ["mixer-master", "mixer-tabs", "edit-editor", "clip-arrange", "menu-main-mode"])

    def test_the_whole_force_file_is_valid_and_all_knobs_options_compose(self):
        for line in rules(read(FORCE)):
            self.assertTrue(RULE.match(line), line)
        got = rules(self.install("--layout", "force", "--options", "all"))
        for line in ("tap 1 d49 b1 u49", "held 1 u49 b1 d49", "long 1 b1", "dbl 1 h1"):
            self.assertIn(line, got)
        self.assertNotIn("tap 1 b1", got)

    def test_none_writes_only_the_always_block(self):
        got = rules(self.install("--layout", "force", "--options", "none"))
        self.assertEqual(got, ["log 0", "hold 49", "longms 400", "holdms 800", "dblms 350", "touchms 300"])

    def test_each_knobs_option_alone(self):
        for opt, want, absent in (
            ("knobs-short", ["tap 1 d49 b1 u49", "held 1 u49 b1 d49"], ["tap 1 b1", "long 1 b1", "dbl 1 h1"]),
            ("knobs-long", ["tap 1 b1", "long 1 b1"], ["held 1 u49 b1 d49", "dbl 1 h1", "tap 1 d49 b1 u49"]),
            ("knobs-double", ["tap 1 b1", "dbl 1 h1"], ["held 1 u49 b1 d49", "long 1 b1", "tap 1 d49 b1 u49"]),
        ):
            with self.subTest(opt):
                self.fresh()
                got = rules(self.install("--layout", "force", "--options", opt))
                for line in want:
                    self.assertIn(line, got)
                for line in absent:
                    self.assertNotIn(line, got)

    def test_with_and_without(self):
        got = rules(self.install("--layout", "force", "--with", "knobs-double", "--without", "mixer-tabs,clip-arrange"))
        self.assertIn("dbl 1 h1", got)
        self.assertIn("tap 1 b1", got)
        self.assertFalse([l for l in got if l.startswith("combo")])

    def test_skipback_is_off_unless_asked_for(self):
        self.assertNotIn("dbl 93 b127", rules(self.install("--layout", "force")))
        self.fresh()
        got = rules(self.install("--layout", "force", "--with", "skipback"))
        self.assertIn("dbl 93 b127", got)
        self.assertIn("dbl 11 b5", got)

    def test_an_unknown_option_changes_nothing(self):
        r = self.patch("install", "--confirmed", "--layout", "force", "--options", "mixer-master,nope")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown option 'nope'", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "sdcard", "hwremap.conf")))
        r = self.patch("install", "--confirmed", "--layout", "mpc-live", "--with", "mixer-master")
        self.assertIn("has no options", r.stderr)

    def test_option_flags_are_ignored_when_a_config_exists(self):
        write(os.path.join(self.root, "sdcard", "hwremap.conf"), "log 1\n")
        r = self.patch("install", "--confirmed", "--layout", "force", "--options", "all")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("option flags are ignored", r.stdout)
        self.assertEqual(self.conf(), "log 1\n")

    def test_the_checklist_on_a_terminal(self):
        # 1 switches mixer-master off, x is rejected, 99 does not exist, Enter continues, then the typed word
        r = self.patch("install", "--layout", "force", stdin="1\nx\n99\n\nPATCH\n", HW_ASK="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[x] Mixer twice", r.stdout)
        self.assertIn("[ ] Mixer twice", r.stdout)
        self.assertIn("Not a number", r.stdout)
        self.assertIn("No option 99", r.stdout)
        got = rules(self.conf())
        self.assertNotIn("dbl 11 b5", got)
        self.assertIn("dbl 37 d49 b9 u49", got)
        st = self.patch("status")
        self.assertIn("Options chosen at install: mixer-tabs edit-editor clip-arrange menu-main-mode.", st.stdout)
        self.fresh()
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "hwremap", "OPTIONS")))
        r = self.patch("install", "--layout", "force", stdin="a\n\nPATCH\n", HW_ASK="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dbl 1 h1", rules(self.conf()))
        self.fresh()
        r = self.patch("install", "--layout", "force", stdin="n\n\nPATCH\n", HW_ASK="1")
        self.assertEqual(rules(self.conf()), ["log 0", "hold 49", "longms 400", "holdms 800", "dblms 350", "touchms 300"])

    def test_without_a_terminal_the_defaults_are_used_and_confirmed_never_asks(self):
        r = self.patch("install", "--layout", "force", stdin="PATCH\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("No terminal to ask on", r.stdout)
        self.assertNotIn("Number to switch", r.stdout)
        self.fresh()
        r = self.patch("install", "--confirmed", "--layout", "force", HW_ASK="1")
        self.assertNotIn("Number to switch", r.stdout)

    def test_regenerating_the_script_matches(self):
        if not os.path.isfile(SO):
            self.skipTest("src/hwremap.so is not present (it is built, not committed)")
        out = os.path.join(self.work, "again.sh")
        r = subprocess.run(["python3", os.path.join(DIR, "build_script.py"), out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(SCRIPT, "rb") as a, open(out, "rb") as b:
            self.assertEqual(a.read(), b.read())


class Engine(unittest.TestCase):
    def test_host_suite(self):
        cc = shutil.which("gcc") or shutil.which("cc")
        if not cc:
            self.skipTest("no C compiler")
        src = os.path.join(DIR, "src")
        bin_ = os.path.join(tempfile.mkdtemp(prefix="hwremap-t-"), "t")
        self.addCleanup(shutil.rmtree, os.path.dirname(bin_), True)
        build = subprocess.run([cc, "-O1", "-g", "-Wall", "-Wextra", "test_hwremap.c", "-ldl", "-lpthread", "-o", bin_],
                               cwd=src, capture_output=True, text=True)
        if build.returncode != 0:
            self.skipTest("host test did not compile here:\n" + build.stderr)
        run = subprocess.run([bin_], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok poll wakes on long press", run.stdout)
        self.assertIn("ok double tap -> touch", run.stdout)


if __name__ == "__main__":
    unittest.main()

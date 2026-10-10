# Edit MPC.settings' plugin list (BusyBox awk). Shipped in every release zip (tools/release.py).
#   awk -v mode=add    -v file=/sdcard/vst/x.so -v entryfile=plugin.xml -f plugin_list.awk MPC.settings
#   awk -v mode=remove -v file=/sdcard/vst/x.so -f plugin_list.awk MPC.settings
#   optional: -v uid=7a6f7574   also drops entries with that uid (an old install at another path)
#             -v alt=/old/path.so  also drops entries with that file=
#             -v listkey=pluginList-arm-64bit  which <VALUE name="..."> to add into/create (default pluginList-arm)
# Drops every <PLUGIN .../> (single- or multi-line) whose file= matches, then in add mode inserts the entry
# into <VALUE name="$listkey"><KNOWNPLUGINS>, creating the value before </PROPERTIES> if it's missing.
# listkey: a real Gen2 (Live III) factory MPC.settings dump has only "pluginList-arm", holding the built-in AIR
# plugins (checked 2026-10-10, offline, debugfs); that device had never had a third-party aarch64 .so registered,
# so it doesn't settle whether MPC reads aarch64 VST2 .so entries from that same key or a separate one. Unverified
# third-party tester feedback (2026-10-10, Hakai VST Manager author, Crate Digger aarch64 beta) reports MPC's
# plugin browser on Gen2 only shows an entry under "pluginList-arm-64bit", not "pluginList-arm". Until confirmed
# on our own hardware, install.sh picks the key from the package's arch (see there) rather than hard-coding either.
function flush() {
    drop = index(buf, "file=\"" file "\"") != 0
    if (!drop && alt != "" && index(buf, "file=\"" alt "\"") != 0) drop = 1
    if (!drop && uid != "" && index(buf, " uid=\"" uid "\"") != 0) drop = 1
    if (!drop) print buf
    buf = ""
}
BEGIN {
    if (mode == "add") { while ((getline l < entryfile) > 0) entry = entry l; close(entryfile) }
    if (listkey == "") listkey = "pluginList-arm"
    done = 0; inlist = 0; buf = ""
}
buf != "" { buf = buf "\n" $0; if ($0 ~ /\/>/) flush(); next }
/<PLUGIN( |$)/ { buf = $0; if ($0 ~ /\/>/) flush(); next }
$0 ~ "<VALUE name=\"" listkey "\">" { inlist = 1; print; next }
inlist && /<KNOWNPLUGINS\/>/ {
    if (mode == "add") {
        ind = $0; sub(/<.*/, "", ind)
        print ind "<KNOWNPLUGINS>"; print ind "  " entry; print ind "</KNOWNPLUGINS>"; done = 1
    } else print
    inlist = 0; next
}
inlist && /<\/KNOWNPLUGINS>/ {
    if (mode == "add" && !done) { ind = $0; sub(/<.*/, "", ind); print ind "  " entry; done = 1 }
    inlist = 0; print; next
}
/<\/PROPERTIES>/ {
    if (mode == "add" && !done) {
        print "  <VALUE name=\"" listkey "\">"; print "    <KNOWNPLUGINS>"; print "      " entry
        print "    </KNOWNPLUGINS>"; print "  </VALUE>"; done = 1
    }
    print; next
}
{ print }

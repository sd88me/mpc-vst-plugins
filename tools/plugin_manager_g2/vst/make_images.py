#!/usr/bin/env python3
"""Draws the Plugin Manager skin's artwork into images/ (SVG). Run it after
changing the look; the layout (layout.conf) places these. Colours follow the mockup: near-black panels, grey type,
red for the main action, amber for updates and warnings, green for "tested"."""
import html
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
BG, PANEL, LINE, INK, DIM, MUTED = "#0c0c0d", "#151517", "#26272a", "#ececed", "#9da1a7", "#b4b7bc"
RED, AMBER, AMBER_TX, GREEN = "#e0342c", "#f0a830", "#f0b44a", "#7fd6a8"
FONT = "font-family=\"Titillium Web\""


def svg(name, w, h, body):
    open(os.path.join(OUT, name), "w").write(
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">%s</svg>\n' % (w, h, w, h, body))


def text(x, y, s, size, fill, weight=600, anchor="start", spacing=0):
    return '<text x="%g" y="%g" %s font-size="%d" font-weight="%d" fill="%s" text-anchor="%s" letter-spacing="%g">%s</text>' % (
        x, y, FONT, size, weight, fill, anchor, spacing, html.escape(s))


ICON = {   # 24x24 stroke icons, drawn at (x, y) scaled to s
    "down": '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M4 20h16"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    "check": '<path d="M4 12.5l5 5L20 6.5"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "warn": '<path d="M12 3L2 21h20L12 3z"/><path d="M12 10v5"/><path d="M12 18v.5"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3z"/>',
    "left": '<path d="M15 5l-7 7 7 7"/>',
    "right": '<path d="M9 5l7 7-7 7"/>',
    "nowifi": '<path d="M2 8.5a15 15 0 0 1 20 0"/><path d="M5.5 12a10 10 0 0 1 13 0"/><path d="M9 15.5a5 5 0 0 1 6 0"/><path d="M12 19h.01"/><path d="M3 3l18 18"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "filter": '<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chevdown": '<path d="M6 9l6 6 6-6"/>',
    "backspace": '<path d="M9 5h11v14H9l-6-7z"/><path d="M12.5 9.5l5 5M17.5 9.5l-5 5"/>',
    "updown": '<path d="M8 20V4M4 8l4-4 4 4"/><path d="M16 4v16M12 16l4 4 4-4"/>',
}


def icon(kind, x, y, s, colour, width=2.5):
    return '<g transform="translate(%g %g) scale(%g)" fill="none" stroke="%s" stroke-width="%g" stroke-linecap="round" stroke-linejoin="round">%s</g>' % (
        x, y, s / 24.0, colour, width, ICON[kind])


def button(name, w, h, label, fill, tx, ic=None, stroke=None, dash=False, size=19):
    edge = ""
    if stroke:
        edge = ' stroke="%s" stroke-width="2"%s' % (stroke, ' stroke-dasharray="7 5"' if dash else "")
    body = '<rect x="1" y="1" width="%d" height="%d" rx="8" fill="%s"%s/>' % (w - 2, h - 2, fill, edge)
    tw = len(label) * size * 0.62 + (30 if ic else 0)
    x0 = (w - tw) / 2
    if ic:
        body += icon(ic, x0, h / 2 - 11, 22, tx)
        x0 += 30
    body += text(x0, h / 2 + size * 0.36, label, size, tx, 700, spacing=1.2)
    svg(name, w, h, body)


def main():
    os.makedirs(OUT, exist_ok=True)
    # the page: header, tab well and footer; everything else is live or switched
    # the mark is the catalog site's: a red dot with a soft halo, then the letter-spaced wordmark (site.css .brand / .dot)
    grid = '<circle cx="35" cy="30" r="9" fill="%s" fill-opacity="0.22"/><circle cx="35" cy="30" r="6" fill="%s"/>' % (RED, RED)
    svg("bg.svg", 1280, 628,
        '<rect width="1280" height="628" fill="%s"/>' % BG
        + '<rect width="1280" height="60" fill="%s"/><rect y="60" width="1280" height="1" fill="%s"/>' % (PANEL, LINE)
        + grid + text(56, 39, "OPEN MPC - PLUGIN MANAGER G2", 24, INK, 700, spacing=3)
        + '<rect x="1036" y="15" width="1" height="30" fill="#2e3034"/>'
        + text(1056, 26, "INTERNAL", 14, MUTED, 600, spacing=1)
        + '<rect x="1056" y="37" width="200" height="5" rx="2.5" fill="#2a2b2f"/>'
        + '<rect x="24" y="64" width="580" height="56" rx="8" fill="%s" stroke="%s"/>' % (PANEL, LINE)
        + '<rect y="556" width="1280" height="72" fill="%s"/><rect y="556" width="1280" height="1" fill="%s"/>' % (PANEL, LINE)
        + '<rect x="206" y="576" width="1" height="32" fill="#2e3034"/>')
    svg("net_on.svg", 100, 24, '<circle cx="5" cy="12" r="4.5" fill="#3fbf7f"/>' + text(16, 17, "ONLINE", 15, MUTED, 600, spacing=1))
    svg("net_off.svg", 100, 24, '<circle cx="5" cy="12" r="4.5" fill="%s"/>' % RED + text(16, 17, "OFFLINE", 15, "#ff9a93", 600, spacing=1))
    # a plugin card (the list row's own picture): the thumbnail tile is part of it
    for name, fill, edge in (("card_off.svg", PANEL, "#222326"), ("card_on.svg", "#1d1e21", RED)):
        svg(name, 1232, 80, '<rect x="1" y="1" width="1230" height="78" rx="10" fill="%s" stroke="%s" stroke-width="2"/>' % (fill, edge)
            + '<rect x="10" y="6" width="136" height="68" rx="6" fill="#24262a" stroke="#34363b"/>')
    # the details (layout.conf "detail view"), over the card area and the space under it. What the details switch on
    # their own (picture, CPU and tested colours, What's new, tags) is baked over the page background, so the panel is
    # that colour too, outlined; the facts panel's labels; the picture's empty tile (d_shot "none")
    facts = "".join(text(30, 264 + 24 * k, lab, 14, DIM, 500) for k, lab in
                    enumerate(("Version", "Channel", "Size", "Released", "Downloads", "CPU", "Tested")))
    svg("detail.svg", 1232, 424, '<rect x="1" y="1" width="1230" height="422" rx="10" fill="%s" stroke="#26272a" stroke-width="2"/>' % BG
        + '<rect x="16.5" y="241.5" width="269" height="181" rx="6" fill="none" stroke="%s"/>' % LINE + facts)
    svg("tile_detail.svg", 270, 135, '<rect x="0.5" y="0.5" width="269" height="134" fill="#24262a" stroke="#34363b"/>')
    svg("tag_pill.svg", 212, 34, '<rect x="0.5" y="0.5" width="211" height="33" rx="17" fill="#1d1e21" stroke="#3a3c41"/>')
    svg("tag_hit.svg", 212, 34, '<rect width="212" height="34" fill="#000" fill-opacity="0"/>')
    # the header's tag-search chip (in place of the kind pills while a tag search is on); tapping it clears the search
    svg("chip.svg", 184, 44, '<rect x="0.5" y="0.5" width="183" height="43" rx="22" fill="#2a1514" stroke="#6b2a26"/>'
        + '<path d="M155 17l10 10M165 17l-10 10" stroke="#ff9a93" stroke-width="2.2" stroke-linecap="round"/>')
    svg("chip_hit.svg", 184, 44, '<rect width="184" height="44" fill="#000" fill-opacity="0"/>')
    button("btn_back.svg", 120, 48, "BACK", "none", INK, "left", stroke="#3a3c41", size=17)
    # card buttons
    button("btn_install.svg", 196, 56, "INSTALL", RED, "#ffffff", "down")
    button("btn_update.svg", 196, 56, "UPDATE", AMBER, "#1a1205", "refresh")
    button("btn_installed.svg", 196, 56, "INSTALLED", "none", "#c9ccd1", "check", stroke="#3a3c41")
    button("btn_q_install.svg", 196, 56, "INSTALL · QUEUED", "none", AMBER_TX, "clock", stroke="#b88426", dash=True, size=15)
    button("btn_q_update.svg", 196, 56, "UPDATE · QUEUED", "none", AMBER_TX, "clock", stroke="#b88426", dash=True, size=15)
    button("btn_q_remove.svg", 196, 56, "REMOVE · QUEUED", "none", AMBER_TX, "clock", stroke="#b88426", dash=True, size=15)
    button("btn_disabled.svg", 196, 56, "INSTALL", "#222326", "#5c5f65", "lock", stroke="#2e3034")
    button("btn_register.svg", 196, 56, "REGISTER", AMBER, "#1a1205", "shield")
    button("btn_q_register.svg", 196, 56, "REGISTER · QUEUED", "none", AMBER_TX, "clock", stroke="#b88426", dash=True, size=15)
    button("btn_reinstall.svg", 96, 56, "REINSTALL", "#26272b", INK, None, stroke="#3a3c41", size=14)
    button("btn_remove.svg", 96, 56, "REMOVE", "#2a1514", "#ff7a72", None, stroke="#6b2a26", size=14)
    svg("more.svg", 44, 56, "".join('<circle cx="22" cy="%d" r="2.6" fill="%s"/>' % (y, MUTED) for y in (21, 28, 35)))
    # badges (the "tested" one gets its device name as live text)
    def badge(name, w, label, colour, edge, ic=None):
        body = '<rect x="0.5" y="0.5" width="%d" height="25" rx="5" fill="none" stroke="%s"/>' % (w - 1, edge)
        x = 10
        if ic:
            body += icon(ic, 9, 6, 14, colour, 2.5)
            x = 28
        svg(name, w, 26, body + text(x, 18, label, 15, colour, 600))
    badge("badge_stable.svg", 72, "Stable", "#d6d8db", "#3a3c41")
    badge("badge_beta.svg", 64, "Beta", AMBER_TX, "#6b5220")
    badge("badge_cpu.svg", 112, "High CPU", AMBER_TX, "#6b5220", "warn")
    badge("badge_old.svg", 104, "Old install", "#c9ccd1", "#4a4c52")
    svg("badge_tested.svg", 200, 26, '<rect x="0.5" y="0.5" width="199" height="25" rx="5" fill="none" stroke="#2f5e46"/>'
        + icon("check", 9, 6, 14, GREEN, 3))
    svg("upd_badge.svg", 24, 24, '<circle cx="12" cy="12" r="12" fill="%s"/>' % AMBER)
    # tabs (the option names are drawn on top by the renderer)
    svg("tab_off.svg", 190, 46, '<rect width="190" height="46" rx="6" fill="none"/>')
    svg("tab_on.svg", 190, 46, '<rect x="0.5" y="0.5" width="189" height="45" rx="6" fill="#2a2b2f" stroke="#4a4c52"/>')
    # the header's filter and sort dropdowns (agreed mockups 1-3; the value is live text), the ring while one is open,
    # and their menus: option names drawn in, the current one's highlight and the taps are separate
    caret = lambda x: '<path d="M%g 18h12l-6 8z" fill="%s"/>' % (x, DIM)
    pill = lambda w: '<rect x="0.5" y="0.5" width="%d" height="43" rx="22" fill="none" stroke="#3a3c41"/>' % (w - 1)
    svg("dd_filter.svg", 200, 44, pill(200) + icon("filter", 18, 12, 20, DIM, 2) + caret(170))
    svg("dd_sort.svg", 236, 44, pill(236) + icon("updown", 16, 12, 20, DIM, 2) + text(44, 28, "Sort", 17, DIM, 400) + caret(206))
    svg("card_hit.svg", 530, 70, '<rect width="530" height="70" fill="#000" fill-opacity="0"/>')   # a card's title and description
    for w in (200, 236):
        svg("dd_hit_%d.svg" % w, w, 44, '<rect width="%d" height="44" fill="#000" fill-opacity="0"/>' % w)
        svg("dd_open_%d.svg" % w, w, 44, '<rect x="1" y="1" width="%d" height="42" rx="21" fill="#ffffff" fill-opacity="0.06" stroke="%s" stroke-width="2"/>' % (w - 2, INK))
    def menu(name, w, title, items):
        svg(name, w, 228, '<rect x="1" y="1" width="%d" height="226" rx="10" fill="#1d1e21" stroke="#3a3c41" stroke-width="2"/>' % (w - 2)
            + text(22, 28, title, 12, "#7c8086", 700, spacing=1.2) + "".join(text(22, 66 + 46 * k, t, 17, INK, 600) for k, t in enumerate(items)))
        svg("menu_row_%d.svg" % (w - 14), w - 14, 46, '<rect width="%d" height="46" rx="6" fill="#ffffff" fill-opacity="0.07"/>' % (w - 14)
            + '<circle cx="%d" cy="23" r="3.5" fill="%s"/>' % (w - 34, RED))
        svg("menu_hit_%d.svg" % (w - 14), w - 14, 46, '<rect width="%d" height="46" fill="#000" fill-opacity="0"/>' % (w - 14))
    menu("menu_kind.svg", 230, "SHOW", ("All", "Instruments", "Effects", "Addins"))
    menu("menu_sort.svg", 298, "SORT BY", ("Last updated", "Newest", "Most downloaded", "Name (A\u2013Z)"))
    svg("menu_bd.svg", 1280, 628, '<rect width="1280" height="628" fill="#000" fill-opacity="0"/>')
    # banners and empty states
    svg("banner.svg", 636, 36, '<rect x="0.5" y="0.5" width="635" height="35" rx="8" fill="#2a1514" stroke="#6b2a26"/>'
        + icon("warn", 12, 10, 16, "#ff7a72", 2.5))
    svg("offline.svg", 1232, 374, '<rect x="1" y="1" width="1230" height="372" rx="10" fill="none" stroke="#2e3034" stroke-dasharray="6 6"/>'
        + icon("nowifi", 596, 70, 40, DIM, 2) + text(616, 160, "Can’t reach the plugin catalog", 24, INK, 700, "middle")
        + text(616, 192, "Check the MPC’s network connection in Preferences, then refresh.", 17, DIM, 400, "middle"))
    svg("empty.svg", 1232, 374, '<rect x="1" y="1" width="1230" height="372" rx="10" fill="none" stroke="#2e3034" stroke-dasharray="6 6"/>')
    button("btn_refresh.svg", 170, 48, "REFRESH", "none", INK, "refresh", stroke=INK, size=18)
    # the restart confirmation (the second APPLY; agreed mockup 7_restart_confirm): a dim backdrop over the whole
    # plugin area, which also takes every tap meant for what is under it, and the dialog; the queued changes are live text
    svg("backdrop.svg", 1280, 628, '<rect width="1280" height="628" fill="#000" fill-opacity="0.62"/>')
    svg("confirm.svg", 640, 426, '<rect x="1" y="1" width="638" height="424" rx="12" fill="%s" stroke="#3a3c41" stroke-width="2"/>' % PANEL
        + icon("warn", 33, 40, 30, AMBER, 2.2) + text(75, 64, "Restart MPC?", 26, INK, 700)
        + text(33, 114, "MPC closes and opens again to apply:", 17, "#c9ccd1", 400)
        + '<rect x="33.5" y="192.5" width="573" height="55" rx="6" fill="#2a2210" stroke="#6b5220"/>'
        + text(50, 226, "Anything not saved in your project will be lost.", 17, AMBER_TX, 400))
    button("btn_cancel.svg", 280, 56, "CANCEL", "none", INK, None, stroke="#3a3c41", size=18)
    button("btn_restart.svg", 280, 56, "RESTART & APPLY", AMBER, "#1a1205", None, size=18)
    button("btn_change.svg", 130, 44, "CHANGE", "none", INK, None, stroke="#3a3c41", size=16)   # the restart prompt: next install location
    # the header's theme switch (dark / light, applied at the next restart): a pill with its label; the live text (DARK / LIGHT) goes over its right part
    svg("btn_theme.svg", 210, 30, '<rect x="0.5" y="0.5" width="209" height="29" rx="15" fill="none" stroke="#3a3c41"/>'
        + text(16, 20, "THEME", 13, DIM, 600))
    # search (agreed mockups 4, 5): the header's button and search chip, and the keyboard panel over the list and footer
    # with two compact match rows; every key is its own image with its letter drawn in
    svg("search_btn.svg", 56, 44, '<rect x="0.5" y="0.5" width="55" height="43" rx="22" fill="none" stroke="#3a3c41"/>' + icon("search", 17, 11, 22, INK, 2.2))
    svg("chip_q.svg", 184, 44, '<rect x="0.5" y="0.5" width="183" height="43" rx="22" fill="#2a1514" stroke="#6b2a26"/>'
        + icon("search", 12, 13, 18, "#ff9a93", 2.4) + '<path d="M155 17l10 10M165 17l-10 10" stroke="#ff9a93" stroke-width="2.2" stroke-linecap="round"/>')
    for name, w in (("chip_hit_l.svg", 140), ("chip_hit_r.svg", 44), ("srow_hit.svg", 1086)):
        svg(name, w, 56 if name == "srow_hit.svg" else 44, '<rect width="%d" height="56" fill="#000" fill-opacity="0"/>' % w)
    svg("kb_bg.svg", 1280, 504, '<rect width="1280" height="504" fill="%s"/>' % BG + '<rect y="163" width="1280" height="1" fill="#26272a"/>'
        + text(24, 474, "Results follow the current tab, filter and sort", 14, "#7c8086", 400))
    svg("srow.svg", 1232, 56, '<rect x="1" y="1" width="1230" height="54" rx="8" fill="%s" stroke="#222326" stroke-width="2"/>' % PANEL
        + '<rect x="17.5" y="8.5" width="39" height="39" rx="6" fill="#24262a" stroke="#34363b"/>')
    svg("kb_input.svg", 960, 46, '<rect x="0.5" y="0.5" width="959" height="45" rx="8" fill="#121214" stroke="#3a3c41"/>' + icon("search", 16, 12, 22, DIM, 2.2))
    def key(name, w, label, fill="#26272b", ink=INK, size=22, ic=None):
        body = '<rect x="0.5" y="0.5" width="%d" height="47" rx="7" fill="%s" stroke="#34363b"/>' % (w - 1, fill)
        body += icon(ic, w / 2 - 12, 12, 24, ink, 2.2) if ic else text(w / 2, 24 + size * 0.36, label, size, ink, 700, "middle", 1 if size < 20 else 0)
        svg(name, w, 48, body)
    for c in "QWERTYUIOPASDFGHJKLZXCVBNM1234567890":
        key("key_%s.svg" % c, 86, c)
    key("key_back.svg", 180, "", ic="backspace")
    key("key_space.svg", 266, "SPACE", size=15)
    key("key_done.svg", 180, "DONE", RED, "#ffffff", 18)
    button("btn_clear.svg", 256, 46, "CLEAR", "none", INK, "close", stroke="#3a3c41", size=17)
    svg("btn_hide.svg", 96, 28, '<rect x="0.5" y="0.5" width="95" height="27" rx="14" fill="none" stroke="#3a3c41"/>'
        + text(16, 19, "HIDE", 13, DIM, 700, spacing=1) + icon("chevdown", 60, 4, 20, DIM, 2.2))
    # the match rows' small action buttons
    for st, label, fill, ink, stroke, dash in (("install", "INSTALL", RED, "#ffffff", None, False), ("update", "UPDATE", AMBER, "#1a1205", None, False),
                                               ("installed", "INSTALLED", "none", "#c9ccd1", "#3a3c41", False),
                                               ("q_install", "QUEUED", "none", AMBER_TX, "#b88426", True), ("q_update", "QUEUED", "none", AMBER_TX, "#b88426", True),
                                               ("q_remove", "QUEUED", "none", AMBER_TX, "#b88426", True), ("disabled", "INSTALL", "#222326", "#5c5f65", "#2e3034", False)):
        button("bs_%s.svg" % st, 110, 40, label, fill, ink, None, stroke=stroke, dash=dash, size=13)
    # footer
    for side in ("left", "right"):
        for name, colour in (("arrow_%s.svg" % side, INK), ("arrow_%s_dim.svg" % side, "#4a4c52")):
            svg(name, 44, 44, '<rect x="0.5" y="0.5" width="43" height="43" rx="8" fill="none" stroke="#3a3c41"/>'
                + icon(side, 12, 12, 20, colour))
    button("updall_on.svg", 188, 52, "UPDATE ALL", "none", AMBER_TX, None, stroke=AMBER, size=18)
    button("updall_off.svg", 188, 52, "UPDATE ALL", "none", "#4a4c52", None, stroke="#3a3c41", size=18)
    button("apply_off.svg", 220, 52, "APPLY", "#2a2b2f", "#6b6e74")
    button("apply_apply.svg", 220, 52, "APPLY", RED, "#ffffff")
    button("apply_preparing.svg", 220, 52, "PREPARING…", "#2a2b2f", MUTED)
    button("apply_ready.svg", 220, 52, "RESTART & APPLY", AMBER, "#1a1205", size=17)
    button("apply_retry.svg", 220, 52, "RETRY", AMBER, "#1a1205", "refresh")
    # the bars: one picture per step (MPC switches them); step 0 of the progress bar is empty, it shows only while downloading
    for k in range(11):
        svg("disk_%02d.svg" % k, 200, 5, '<rect width="%d" height="5" rx="2.5" fill="%s"/>' % (20 * k, DIM) if k else "")
    for k in range(21):
        svg("progress_%02d.svg" % k, 360, 4, ('<rect width="360" height="4" rx="2" fill="#2a2b2f"/>'
                                              '<rect width="%d" height="4" rx="2" fill="%s"/>' % (18 * k, RED)) if k else "")


if __name__ == "__main__":
    main()

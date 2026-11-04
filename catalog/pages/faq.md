---
title: Questions and answers
nav: FAQ
order: 15
summary: MPC OS 3.10 (beta), Gen1 or Gen2, the Plugin Manager's web page and more.
---

Start with [Install the Plugin Manager](install.html). Still stuck? Ask in the community with your MPC model, MPC OS version and what you see.

::: details Does it work on MPC OS 3.10?
Yes, in beta. For now, the recommended way is to install the Plugin Manager on MPC OS 3.9.1 with the Plugin Manager stick, then update the MPC to 3.10: the Plugin Manager and your plugins stay installed. See [MPC OS 3.10 (beta)](install.html#mpc-os-3-10-beta).
:::

::: details Does it work on MPC OS 2.x?
The Plugin Manager and its stick don't: they need MPC OS 3.x. On 2.x, install plugins whose catalog card says "MPC OS: 2.x and 3.x" over SSH, with the desktop installer app or by hand: see [MPC OS 2.x](install.html#mpc-os-2-x) on the Install page.
:::

::: details Gen1 or Gen2 build?
Gen1 (32-bit): Live, Live II, One, X, Key 61/37 and the Force. Gen2 (64-bit): Live III, One G2, Key G2, XL. The Plugin Manager picks the right build of each plugin for your MPC.
:::

::: details Can I keep plugins on a USB stick or SD card?
Yes. The Plugin Manager's drive menu (tap the storage readout) chooses where new ones go: the internal drive, an SD card or a USB drive. The internal drive is the safest: a plugin on a stick or card is gone while it is unplugged.
:::

::: details What about the Force?
The Force runs MPC OS 3.9.1. Use the [3.9.1 steps](install.html#mpc-os-3-9-1-or-earlier): the Plugin Manager stick or the installer app.
:::

::: details Where is the Plugin Manager's web page?
Add Plugin Manager to a track: its status line at the bottom shows `On your phone or computer: http://…:8790`. Open that on any device on the same Wi-Fi. It works while the Plugin Manager is on a track; after APPLY restarts MPC it comes back when the project with the Plugin Manager reopens.
:::

::: details Is the web page safe?
It has no password: anyone on your network can use it while the Plugin Manager is open. Other web sites can't control it. On a network you don't trust, close the Plugin Manager when you're done.
:::

::: details Do sequencer plugins still drive other tracks?
Yes, through their own MIDI port: pick it as the other track's MIDI input (enable it in Preferences → MIDI first).
:::

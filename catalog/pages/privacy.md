---
title: Privacy
nav: Privacy
order: 90
summary: What the catalog stores if you sign in to report that a plugin works or to like it, and how to delete it.
---

The catalog is a static site: browsing it, searching and downloading need no account and store nothing about you on our side.
Signing in is optional. It is only used to count "works for me" reports, likes and the plugins you follow, one count per person.

::: details What is stored when you sign in
- Your sign-in provider (Discord, Google or GitHub), your account id at that provider, your email address and the display name the provider shares.
- What you do: the plugins you reported as working (with the plugin version, your device and MPC OS version), the plugins you liked, the plugins you follow.
- A secret address for your personal update feed, if you follow plugins. Anyone who has the address can read the feed, so keep it private. "Regenerate address" under Following and my feed cancels the old one.
- Your IP address and browser type, kept with your sign-in session and in short-lived counters that limit abuse. They are not shown to anyone.
:::

::: details What is public
Only totals, such as "12 people report this works" or "30 likes". Your name, email and individual reports are not shown. The catalog maintainers can see who made a report so that spam or abuse can be hidden.
:::

::: details Where it is kept
In a database on Cloudflare (the service that runs the catalog's small server). Sign-in goes through Discord, Google or GitHub, which tell us only the details listed above, never your password. We do not sell or share this data, we send no marketing and there are no advertising or tracking scripts. The site sets no cookies; your sign-in token lives in your browser's own storage and is removed when you sign out.
:::

::: details Delete your data
Open your name in the page header and choose "Delete my account". It removes your account, reports, likes, follows and feed address. Counts that included you go down by one. If you cannot sign in, open an issue at [github.com/open-mpc/mpc-vst-plugins/issues](https://github.com/open-mpc/mpc-vst-plugins/issues) and say which account to delete.
:::

::: details Questions
Open an issue on the [catalog's GitHub repository](https://github.com/open-mpc/mpc-vst-plugins/issues). This page can change; the date of the last change is in the repository's history.
:::

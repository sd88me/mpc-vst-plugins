/* Drives the engine like the screen would (tests/run.sh): waits for the catalog, prints each page of cards with
 * their fields and states, then queues an install and runs APPLY up to the (dry-run) restart. With "addins" it
 * runs the addin flow against the offline fixture instead: update, install and a refused removal. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
typedef struct { void *(*create)(const char *); void (*destroy)(void *); void (*midi)(void *, const uint8_t *, int);
  void (*set_param)(void *, const char *, const char *); int (*get_param)(void *, const char *, char *, int);
  void (*render)(void *, int16_t *, int); void *process; } E;
const E *mpc_engine(void);
static const E *e;
static void *m;

static const char *get(const char *k) { static char b[32][128]; static int i; i = (i + 1) % 32; b[i][0] = 0; e->get_param(m, k, b[i], 128); return b[i]; }
static void set(const char *k, const char *v) { e->set_param(m, k, v); }
/* the manager drops the same button twice within 250 ms (MPC delivers one tap twice): a test that really taps one twice waits */
static int tapms(void) { const char *e = getenv("PM_TAPMS"); return e ? atoi(e) : 250; }   /* the manager's double-tap window */
static void press(const char *k) {
  static char last[64];
  if (!strcmp(k, last)) usleep((tapms() + 20) * 1000);
  snprintf(last, sizeof last, "%s", k);
  set(k, "1"); set(k, "0");
}
/* a page tap after a pause (as a finger), once or delivered twice (as MPC did on a Live III: the second one must not step again) */
static void page(const char *k, int twice) { usleep((tapms() + 50) * 1000); if (twice) set(k, "1"); set(k, "1"); set(k, "0"); }

static void cards(void) {
  printf("  [%s] %s | status(%s): %s | apply_state %s\n", get("page_txt"), get("summary"), get("status_kind"), get("status"), get("apply_state"));
  if (get("problem")[0] == '1') printf("  banner: %s\n", get("problem_txt"));
  for (int r = 1; r <= 5; r++) {
    char k[32];
    #define F(f) (snprintf(k, sizeof k, "r%d_" f, r), get(k))
    snprintf(k, sizeof k, "card%d_1", r);
    if (!strcmp(F("vis"), "0")) { printf("  card %d: -\n", r); continue; }
    printf("  card %d: %-13s [%s|%s] state=%s inst=%s chan=%s cpu=%s old=%s tested=%s(%s) %s %s %s %s | %s\n", r, get(k), F("init"), F("kindtxt"),
           F("state"), F("inst"), F("chan"), F("cpu"), F("old"), F("tested"), F("tested_txt"), F("ver"), F("from"), F("size"), F("info"), F("meta"));
  }
}

static void details(void) {
  printf("  view=%s shot=%s [%s] %s | %s | state=%s inst=%s nav=%s%s card1 vis=%s\n", get("view"), get("d_shot"), get("d_init"),
         get("d_name"), get("d_by"), get("d_state"), get("d_inst"), get("nav_prev"), get("nav_next"), get("r1_vis"));
  printf("    v%s %s %s released %s, %s downloads, cpu %s (%s), tested %s (%s)\n", get("d_f_version"), get("d_f_channel"), get("d_f_size"),
         get("d_f_released"), get("d_f_downloads"), get("d_f_cpu"), get("d_cpuk"), get("d_f_tested"), get("d_testk"));
  for (int i = 1; i <= 4; i++) { char k[8]; snprintf(k, sizeof k, "d_sum%d", i); printf("    |%s|\n", get(k)); }
  printf("    %s (%s)\n", get("d_wn_head"), get("d_wnk"));
  for (int i = 1; i <= 3; i++) { char k[8]; snprintf(k, sizeof k, "d_wn%d", i); printf("    |%s|\n", get(k)); }
  printf("    tags:");
  for (int i = 1; i <= 8; i++) { char k[10], t[10]; snprintf(k, sizeof k, "d_tag%dv", i); snprintf(t, sizeof t, "d_tagt%d", i); if (!strcmp(get(k), "1")) printf(" %s", get(t)); }
  printf("\n");
}

static void prompt(void) {
  printf("  confirm=%s |%s|%s|\n", get("confirm"), get("confirm_txt1"), get("confirm_txt2"));
}

static void wait_for(const char *key, const char *val) {
  for (int i = 0; i < 120; i++) {
    if (!strcmp(get(key), val)) return;
    if (!strcmp(key, "apply_state") && !strcmp(get(key), "4")) { printf("  (apply_state=4 while waiting for %s: the prepare step failed)\n", val); return; }   /* failed: no point waiting out the timeout */
    sleep(1);
  }
  printf("  (timeout waiting for %s=%s)\n", key, val);
}

int main(int argc, char **argv) {
  e = mpc_engine(); m = e->create(NULL);
  for (int i = 0; i < 60 && !strstr(get("summary"), "available") ; i++) sleep(1);
  sleep(1);
  printf("net=%s problem=%s (%s) empty=%s disk=%s %s upd_badge=%s count=%s\n", get("net"), get("problem"), get("problem_txt"), get("empty"),
         get("disk"), get("disk_txt"), get("upd_badge"), get("upd_count"));
  if (argc > 1 && !strcmp(argv[1], "addins")) {   /* the offline fixture (tests/fixture.py, tests/addins.sh) */
    set("kind", "3"); printf("ADDINS (DISCOVER: only the one not installed)\n"); cards();
    printf("install beta (card 1)\n"); press("r1_act"); cards();
    set("tab", "1"); printf("INSTALLED: remove alpha (card 1), remove gamma (card 2: made by hand, refused)\n"); cards();
    press("r1_more"); press("r1_remove"); press("r2_more"); press("r2_remove"); cards();
    press("apply"); wait_for("apply_state", "3"); cards();
    press("apply"); prompt(); press("confirm_go"); sleep(1); cards();
    e->destroy(m); return 0;
  }
  if (argc > 1 && !strncmp(argv[1], "theme", 5)) {   /* both skins in the plugin folder (tests/run.sh sets PM_OWN): the switch, the prompt, then APPLY */
    printf("start: can=%s theme=%s |%s| apply_state=%s\n", get("theme_can"), get("theme"), get("theme_txt"), get("apply_state"));
    if (!strcmp(argv[1], "themeshow")) { e->destroy(m); return 0; }
    set("theme_btn", "1"); press("theme_btn");   /* one tap, delivered twice (a Live III does that) */
    printf("pressed: theme=%s |%s| apply_state=%s status: %s\n", get("theme"), get("theme_txt"), get("apply_state"), get("status"));
    press("apply");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3"); i++) sleep(1);
    press("apply"); printf("prompt: confirm=%s |%s|\n", get("confirm"), get("confirm_txt1"));
    e->destroy(m); return 0;
  }
  if (argc > 1 && !strcmp(argv[1], "pick")) {   /* two usable locations: the restart prompt names one, CHANGE picks the other */
    set("kind", "1"); press("r1_act"); press("apply");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3"); i++) sleep(1);
    press("apply"); printf("prompt: confirm=%s pick=%s |%s|\n", get("confirm"), get("confirm_pick"), get("confirm_dest"));
    press("target_next");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3"); i++) sleep(1);
    printf("after CHANGE: confirm=%s pick=%s |%s|\n", get("confirm"), get("confirm_pick"), get("confirm_dest"));
    press("confirm_go");   /* the confirmed place is remembered */
    e->destroy(m); return 0;
  }
  if (argc > 1 && !strcmp(argv[1], "pickshow")) {   /* a fresh start: which place does the restart prompt name first? */
    set("kind", "1"); press("r1_act"); press("apply");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3") && strcmp(get("apply_state"), "4"); i++) sleep(1);
    press("apply"); printf("first prompt: confirm=%s pick=%s |%s|\n", get("confirm"), get("confirm_pick"), get("confirm_dest"));
    e->destroy(m); return 0;
  }
  if (argc > 1 && !strcmp(argv[1], "status")) { cards(); e->destroy(m); return 0; }   /* what the manager says on its own (the last apply) */
  if (argc > 2 && !strcmp(argv[1], "one")) {   /* queue the effect called argv[2] and APPLY: the prepare step's verdict */
    if (argc > 4) set("tab", argv[4]);
    set("kind", argc > 3 ? argv[3] : "2");
    for (int p = 0, done = 0; p < 2 && !done; p++) {   /* the effects run to two pages now */
    for (int r = 1; r <= 5; r++) {
      char k[32];
      snprintf(k, sizeof k, "card%d_1", r);
      if (!strcmp(get(k), argv[2])) { snprintf(k, sizeof k, "r%d_act", r); press(k); done = 1; break; }
    }
    if (!done) page("page_next", 0);
    }
    press("apply");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3") && strcmp(get("apply_state"), "4"); i++) sleep(1);
    cards();
    e->destroy(m); return 0;
  }
  if (argc > 1 && !strcmp(argv[1], "arch")) {   /* the zip for the device (tests/fixture.py "Dual", "Armonly"): EFFECTS, install card 1 */
    set("kind", "2"); cards();
    press(argc > 2 ? "r2_act" : "r1_act"); press("apply");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3") && strcmp(get("apply_state"), "4"); i++) sleep(1);
    cards();
    e->destroy(m); return 0;
  }
  if (argc > 1 && !strcmp(argv[1], "links")) {   /* a package that needs a symbolic link (tests/fixture.py "Linky"): queue it and APPLY */
    set("kind", "1"); printf("INSTRUMENTS: install Linky (card 1)\n"); cards();
    press("r1_act"); press("apply");
    for (int i = 0; i < 60 && strcmp(get("apply_state"), "3") && strcmp(get("apply_state"), "4"); i++) sleep(1);
    cards();
    e->destroy(m); return 0;
  }
  printf("DISCOVER\n"); cards();
  printf("details: tap card 2, BACK, thumbnail of card 1, page arrows ignored, queue from the details, BACK\n");
  set("card2_1", "1"); details(); press("d_back"); printf("  view=%s\n", get("view"));
  press("r1_open"); page("page_next", 0); details(); press("d_act"); details(); press("d_act"); press("d_back"); cards();
  printf("tag search: details of card 1, its first tag, then clear\n");
  press("r1_open"); press("d_tag1"); printf("  view=%s hdr=%s chip=%s\n", get("view"), get("hdr"), get("tag_txt")); cards();
  press("tag_clear"); printf("  hdr=%s\n", get("hdr")); cards();
  printf("search: type C H O, match rows, DONE; the chip reopens it; back, clear; the chip's x clears it\n");
  press("search_btn"); printf("  kb=%s hdr=%s |%s| %s\n", get("kb"), get("hdr"), get("q_txt"), get("kb_count"));
  press("k_C"); press("k_H"); press("k_O");
  printf("  |%s| %s\n  row1 %s [%s] %s | %s | state=%s\n  row2 %s [%s] %s | state=%s\n", get("q_txt"), get("kb_count"), get("sr1_vis"), get("sr1_init"),
         get("sr1_name"), get("sr1_meta"), get("sr1_state"), get("sr2_vis"), get("sr2_init"), get("sr2_name"), get("sr2_state"));
  press("k_done"); printf("  kb=%s hdr=%s chip=%s\n", get("kb"), get("hdr"), get("q_chip")); cards();
  press("search_btn"); press("k_back"); printf("  kb=%s |%s|\n", get("kb"), get("q_txt")); press("k_clear"); printf("  |%s| %s\n", get("q_txt"), get("kb_count"));
  press("k_space"); press("k_D"); press("k_X"); press("k_7"); printf("  |%s| %s\n", get("q_txt"), get("kb_count"));
  press("sr1_open"); printf("  details of the match: view=%s kb=%s %s\n", get("view"), get("d_name"), get("kb")); press("d_back");
  press("q_clear"); printf("  hdr=%s chip=%s\n", get("hdr"), get("q_chip"));
  printf("sort menu: open, a tap outside closes it; open again, Most downloaded; then Name; filter menu: Effects, then All\n");
  press("sort_btn"); printf("  sort_open=%s hl=%s\n", get("sort_open"), get("sort_hl")); press("menu_close"); printf("  sort_open=%s\n", get("sort_open"));
  press("sort_btn"); press("sort_pick3"); printf("  sort=%s (%s) open=%s\n", get("sort"), get("sort_txt"), get("sort_open")); cards();
  press("sort_pick4"); printf("  sort_pick while closed: sort=%s\n", get("sort"));
  press("sort_btn"); press("sort_pick4"); printf("  sort=%s (%s)\n", get("sort"), get("sort_txt")); cards();
  press("kind_btn"); printf("  kind_open=%s hl=%s\n", get("kind_open"), get("kind_hl")); press("kind_pick3"); printf("  kind=%s (%s)\n", get("kind"), get("kind_txt")); cards();
  press("kind_btn"); press("kind_pick1"); press("sort_btn"); press("sort_pick1"); printf("  back to %s, %s\n", get("kind_txt"), get("sort_txt"));
  page("page_next", 0); cards(); page("page_next", 1); cards();
  set("tab", "2"); printf("UPDATES\n"); cards();
  set("tab", "1"); printf("INSTALLED\n"); cards();
  set("tab", "0"); set("kind", "2"); printf("EFFECTS\n"); cards(); set("kind", "0");
  printf("INSTALLED: menu on card 1 (if any), then DISCOVER: queue card 2 and UPDATE ALL\n");
  set("tab", "1"); press("r1_more"); cards(); set("tab", "0"); press("r1_remove"); press("r2_act"); press("update_all"); cards();
  press("apply"); wait_for("apply_state", "3"); cards();
  printf("APPLY again: the restart prompt; CANCEL keeps it ready, a tab tap is ignored while it shows\n");
  press("apply"); prompt(); set("tab", "1"); printf("  tab=%s\n", get("tab")); press("confirm_cancel"); prompt();
  printf("  apply_state=%s\n", get("apply_state"));
  press("apply"); prompt(); press("confirm_go"); sleep(1); cards();
  e->destroy(m); return 0;
}

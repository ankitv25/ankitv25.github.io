# ankitv25.github.io

Personal site — one page, `index.html`: the full section structure (funds, Convexity Lab, MRS, DAA,
foundation, experience) in the dark design language of `reference.html`. `Verma_Ankit_Resume.pdf` is
linked from the masthead, hero and contact card and is deployed with the page. `old-index.html` is the
previous light version, kept until the new one is signed off.

## Figures are generated, not typed

Every live number on the page — fund NAVs and returns, the NAV chart and its hover data, holdings,
the 1997–2026 backtest table and the SAA → DAA headline, the Macro Regime Score chart and statistics,
the convexity chart and the ten-year Monte Carlo fan — is written by `scripts/refresh_data.py` from the
public dashboards:

| Dashboard | Feed |
|---|---|
| Asset-Allocation | `https://ankitv25.github.io/Asset-Allocation/data/live_nav.js`, `portfolio_books.json` (Monte Carlo) |
| Macro-Regime-Score | `https://ankitv25.github.io/Macro-Regime-Score/data/composite_history.json`, `metadata.json` |
| Convexity-Lab-RM | `https://ankitv25.github.io/Convexity-Lab-RM/data/lab/rates.json` |

The script only replaces what sits between `<!--gen:NAME-->` and `<!--/gen:NAME-->` (blocks the page
does not carry are skipped), and the text of elements with `data-k="KEY"`. Edit everything else in `index.html` freely. `data/site-data.json`
records what was published and from where.

```
python3 scripts/refresh_data.py           # refresh and rewrite
python3 scripts/refresh_data.py --check   # validate the feeds, write nothing
```

It refuses to write (exit 1) — leaving the current page live — if a feed is malformed, is missing one of the
five funds, carries a non-numeric NAV or one that moved more than 5% in a day, or is older than what is
already published (NAV date or MRS month). Counts are derived, not copied: "N of 5 ahead" is the number of
funds with a positive active return ("All 5" / "None" at the ends), trading days is the number of NAV
observations, and months-in-regime and the regime frequencies come from the MRS series.

Not published by any dashboard, so hand-maintained: the "What each engine adds" leave-one-out table, the
lineage drawdown chart, the trend-sleeve sizes and the MRS research facts (9 months before NBER, 0.989).

## Schedule

- `.github/workflows/sync-stats.yml` (**Sync live figures**) runs on:
  - `repository_dispatch` `stats-updated`, sent when the Asset-Allocation refresh (private
    `Summer_Investment_Platform` → `scheduled-refresh.yml`, Mon/Wed/Fri) or the MRS refresh
    (`Macro-Regime-Score` → `mrs-full-refresh.yml`, daily) finishes. The payload carries the date just
    published; the script polls the live feed until GitHub Pages serves it (up to 15 minutes).
  - weekdays 22:30 UTC, after the US close, as a backup;
  - by hand (Actions → Sync live figures → Run workflow).

  It commits only when a figure changed, as "Sync live figures <date>".
- `.github/workflows/deploy-pages.yml` deploys on every push and after each sync, then checks that the live
  `data/site-data.json` matches `main`.

The dispatch needs a secret named `SITE_DISPATCH_TOKEN` in both sending repos: a fine-grained personal
access token whose only repository is `ankitv25.github.io`, with **Contents: Read and write**. Without
it the senders log a warning and the weekday schedule still keeps the page current.

## Visitor analytics

GoatCounter (no cookies, no visible counter). Outbound links carry `data-goatcounter-click` names
(`resume-pdf`, `linkedin`, `github`, `email`, `aa-dashboard`, `aa-live-nav`, `aa-code`, `daa-dashboard`,
`daa-montecarlo`, `mrs-dashboard`, `mrs-code`, `convexity-preview`, `convexity-rates`,
`equity-research-repo`). Open `https://ankitv25.github.io/#toggle-goatcounter` once in each of your own
browsers to stop counting your visits.

Tagged share links, so the referrer shows up in GoatCounter:

| Where it is shared | Link |
|---|---|
| LinkedIn | `https://ankitv25.github.io/?ref=linkedin` |
| Résumé | `https://ankitv25.github.io/?ref=resume` |
| Email | `https://ankitv25.github.io/?ref=email` |
| Applications | `https://ankitv25.github.io/?ref=apply` |

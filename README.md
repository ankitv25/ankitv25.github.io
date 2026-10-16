# ankitv25.github.io

Personal site — one page, `index.html`: the full section structure (funds, Convexity Lab, MRS, DAA,
foundation, experience) in the dark design language of `reference.html`. `Verma_Ankit_Resume.pdf` is
linked from the masthead, hero and contact card and is deployed with the page. `old-index.html` is the
previous light version, kept until the new one is signed off.

## Figures are generated, not typed

Every live number on the page — fund NAVs and returns, the NAV chart and its hover data, holdings,
the Macro Regime Score chart and statistics, the convexity chart and the ten-year Monte Carlo fan — is
written by `scripts/refresh_data.py` from the public dashboards:

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

It refuses to write (exit 1) if a feed is malformed or older than what is already published.

## Schedule

- `.github/workflows/refresh-data.yml` — Mondays 13:00 UTC, after the Asset-Allocation refresh has priced
  Friday's close; also runnable by hand (Actions → Weekly data refresh → Run workflow).
- `.github/workflows/deploy-pages.yml` — deploys on every push and after each refresh, then checks that the
  live `data/site-data.json` matches `main`.

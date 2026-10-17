#!/usr/bin/env python3
"""Refresh every data-driven part of index.html from the three public dashboards.

    python3 scripts/refresh_data.py                 # fetch live feeds, rewrite index.html + data/site-data.json
    python3 scripts/refresh_data.py --check         # fetch and validate only; write nothing
    python3 scripts/refresh_data.py --src DIR       # read the feeds from DIR (live_nav.js, composite_history.json,
                                                    #   metadata.json, rates.json) instead of the network

Sources (all public, nothing is typed by hand):
  Asset-Allocation   data/live_nav.js             five-fund NAV, references, policy books
  Macro-Regime-Score data/composite_history.json  monthly composite and confirmed regime
                     data/metadata.json
  Convexity-Lab-RM   data/lab/rates.json          dated Treasury par curve the Lab publishes

index.html stays the file you edit. The script only replaces what sits between
<!--gen:NAME--> and <!--/gen:NAME--> markers, and the text of elements carrying data-k="KEY".
Everything else is left byte-for-byte as it was. Stdlib only, so the workflow needs no installs.

It refuses to write (exit 1) if a feed is malformed or goes backwards in time, so a broken
upstream run can never blank the page.
"""
import argparse, json, math, os, re, sys, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, 'index.html')
SNAP = os.path.join(ROOT, 'data', 'site-data.json')
URLS = {
    'live_nav.js': 'https://ankitv25.github.io/Asset-Allocation/data/live_nav.js',
    'composite_history.json': 'https://ankitv25.github.io/Macro-Regime-Score/data/composite_history.json',
    'metadata.json': 'https://ankitv25.github.io/Macro-Regime-Score/data/metadata.json',
    'rates.json': 'https://ankitv25.github.io/Convexity-Lab-RM/data/lab/rates.json',
    'portfolio_books.json': 'https://ankitv25.github.io/Asset-Allocation/data/portfolio_books.json',
}
# The funds' identity hues, lifted for the dark page so every line clears the navy ground.
ON_DARK = {'#0891b2': '#3db5d1', '#92400e': '#b07d5b', '#8b5cf6': '#a58bf8', '#86198f': '#cf6bd6', '#d97706': '#e8a13a'}
FUNDS = ['Certain', 'Endowment', 'SAA', 'DAA', 'Alpha']
MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
         'October', 'November', 'December']
# MRS calibrated bands (composite z): the thresholds the dashboard classifies against.
BANDS = [('Expansion', 0.35, None), ('Neutral', -0.30, 0.35), ('Slowdown', -1.00, -0.30), ('Contraction', None, -1.00)]
REG_COL = {'Expansion': 'var(--c1)', 'Neutral': 'var(--cn)', 'Slowdown': 'var(--c2)', 'Contraction': 'var(--c3)'}
MINUS = '−'


class FeedError(Exception):
    pass


# ---------------------------------------------------------------- formatting
def sgn(x, d=2, unit=''):
    s = f'{abs(x):.{d}f}'
    if float(s) == 0:
        return f'{0:.{d}f}{unit}'
    return ('+' if x > 0 else MINUS) + s + unit


def neg(x, d=2, unit=''):
    """Plain number with a typographic minus."""
    return (MINUS if x < 0 else '') + f'{abs(x):.{d}f}{unit}'


def cls(x, eps=0.00005):
    return 'up' if x > eps else ('dn' if x < -eps else 'flat')


def d_long(iso):
    y, m, d = map(int, iso[:10].split('-'))
    return f'{d} {MO[m - 1]} {y}'


def d_short(iso):
    y, m, d = map(int, iso[:10].split('-'))
    return f'{d} {MO[m - 1]}'


def m_long(iso):
    y, m, _ = map(int, iso[:10].split('-'))
    return f'{MONTH[m - 1]} {y}'


def m_short(iso):
    y, m, _ = map(int, iso[:10].split('-'))
    return f'{MO[m - 1]} {y}'


def ordinal(n):
    suf = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suf}'


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def pts(xy):
    return ' '.join(f'{x:.1f},{y:.1f}' for x, y in xy)


# ---------------------------------------------------------------- feeds
def load(src):
    raw = {}
    for name, url in URLS.items():
        if src:
            with open(os.path.join(src, name), encoding='utf-8') as f:
                raw[name] = f.read()
        else:
            req = urllib.request.Request(url, headers={'User-Agent': 'ankitv25.github.io refresh'})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw[name] = r.read().decode('utf-8')
    js = raw['live_nav.js'].strip()
    m = re.match(r'^window\.LIVE_NAV\s*=\s*(\{.*\})\s*;?\s*$', js, re.S)
    if not m:
        raise FeedError('live_nav.js is not a window.LIVE_NAV assignment')
    nav = json.loads(m.group(1))
    for fx in nav.get('facts', {}).values():
        if isinstance(fx, dict) and 'color' in fx:
            fx['color'] = ON_DARK.get(fx['color'].lower(), fx['color'])
    return (nav, json.loads(raw['composite_history.json']),
            json.loads(raw['metadata.json']), json.loads(raw['rates.json']), json.loads(raw['portfolio_books.json']))


def validate(nav, mrs, meta, rates, books, prev):
    dates = nav.get('dates') or []
    if len(dates) < 2:
        raise FeedError('live NAV has fewer than two dates')
    for f in FUNDS:
        s = nav['series'].get(f)
        if not s or len(s) != len(dates):
            raise FeedError(f'live NAV series for {f} does not match its dates')
        if any(not (50 < v < 200) for v in s):
            raise FeedError(f'live NAV for {f} has an implausible value')
        if f not in nav['books'] or abs(sum(nav['books'][f].values()) - 1) > 0.005:
            raise FeedError(f'policy book for {f} does not sum to 100%')
    if len(mrs) < 100 or any('composite' not in r or 'date' not in r for r in mrs):
        raise FeedError('MRS composite history is malformed')
    if len(rates.get('curve', [])) < 8:
        raise FeedError('Convexity Lab rates curve is malformed')
    try:
        mc = books['books']['daa']['monte_carlo']
        fan = mc['fan']
        for k in ('DAA', 'SAA', '60/40'):
            q = [fan[k][p] for p in ('p5', 'p25', 'p50', 'p75', 'p95')]
            if len(fan[k]['years']) < 5 or any(len(x) != len(fan[k]['years']) for x in q):
                raise FeedError(f'Monte Carlo fan for {k} is malformed')
            if any(not (a <= b <= c <= d <= e) for a, b, c, d, e in zip(*q)):
                raise FeedError(f'Monte Carlo percentiles for {k} are not ordered')
        if mc['params']['n_paths'] < 1000:
            raise FeedError('Monte Carlo has too few paths')
    except (KeyError, TypeError) as e:
        raise FeedError(f'portfolio_books.json is missing Monte Carlo data: {e}')
    if prev:
        if dates[-1] < prev['nav']['asof']:
            raise FeedError(f"live NAV went backwards: {dates[-1]} < {prev['nav']['asof']}")
        if mrs[-1]['date'] < prev['mrs']['through']:
            raise FeedError(f"MRS went backwards: {mrs[-1]['date']} < {prev['mrs']['through']}")


# ---------------------------------------------------------------- funds
def nice_range(lo, hi, n=4):
    span = max(hi - lo, 0.5)
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    a = math.floor(lo / step) * step
    b = math.ceil(hi / step) * step
    return a, b, step


def fund_block(nav):
    dates, S, facts = nav['dates'], nav['series'], nav['facts']
    last = {f: S[f][-1] for f in FUNDS}
    order = sorted(FUNDS, key=lambda f: -last[f])
    n = len(dates)

    # --- main chart
    W, H, X0, X1, Y0, Y1 = 680, 280, 48, 660, 16, 238
    lo = min(min(S[f]) for f in FUNDS + []) ; hi = max(max(S[f]) for f in FUNDS)
    lo, hi = min(lo, 100), max(hi, 100)
    a, b, step = nice_range(lo - 0.15, hi + 0.15)
    sy = (Y1 - Y0) / (b - a)
    dx = (X1 - X0) / (n - 1)
    y = lambda v: Y1 - (v - a) * sy
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Daily NAV of the five funds from launch at 100 on '
           f'{d_long(dates[0])} to {d_long(dates[-1])}. '
           + ', '.join(f'{f} {sgn(last[f] - 100)} percent' for f in order) + ' since launch.">']
    t = a
    while t <= b + 1e-9:
        c = 'zl' if abs(t - 100) < 1e-9 else 'gl'
        lab = f'{t:g}'
        out.append(f'<line class="{c}" x1="{X0}" y1="{y(t):.1f}" x2="{X1}" y2="{y(t):.1f}"></line>'
                   f'<text class="ax" x="{X0 - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{lab}</text>')
        t += step
    ticks = [0] + [i for i in range(1, n) if dates[i][5:7] != dates[i - 1][5:7]]
    for i in ticks:
        if n - 1 - i < 6 and i != 0:
            continue
        out.append(f'<text class="ax" x="{X0 + i * dx:.1f}" y="{H - 14}" text-anchor="{"start" if i == 0 else "middle"}">{d_short(dates[i])}</text>')
    out.append(f'<text class="ax" x="{X1}" y="{H - 14}" text-anchor="end">{d_short(dates[-1])}</text>')
    for f in FUNDS:
        col = facts[f]['color']
        out.append(f'<polyline data-f="{f}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" '
                   f'points="{pts((X0 + i * dx, y(v)) for i, v in enumerate(S[f]))}"><title>{f} — NAV {last[f]:.2f} on '
                   f'{d_long(dates[-1])} ({sgn(last[f] - 100)}% since launch)</title></polyline>')
    for f in FUNDS:
        out.append(f'<circle data-f="{f}" cx="{X1}" cy="{y(last[f]):.1f}" r="3.6" fill="{facts[f]["color"]}"></circle>')
    out.append(f'<line class="xh" id="navXh" x1="0" y1="{Y0}" x2="0" y2="{Y1}"></line><g class="hd" id="navDots"></g></svg>')
    chart = '\n'.join(out)

    geo = {'x0': X0, 'dx': round(dx, 6), 'a': a, 'sy': round(sy, 6), 'y1': Y1}
    data = {'d': dates, 'g': geo, 's': {f: [round(v, 2) for v in S[f]] for f in FUNDS}}

    board = []
    for f in order:
        c = last[f] - 100
        board.append(f'<button class="brow" type="button" data-f="{f}" style="--c:{facts[f]["color"]}"><i></i>'
                     f'<span class="bn">{f}<small>vs {esc(facts[f]["reference"])}</small></span>'
                     f'<span class="brd">{last[f]:.2f}</span><span class="bch {cls(c)}">{sgn(c)}%</span></button>')

    tape = []
    for f in order:
        c = last[f] - 100
        tape.append(f'<a class="q" href="#funds" style="--c:{facts[f]["color"]}"><i></i><span class="qn">{f}</span>'
                    f'<span class="qp">{last[f]:.2f}</span><span class="qc {cls(c)}">{sgn(c)}%</span></a>')

    rows, ahead = [], 0
    for f in FUNDS:
        fx = facts[f]
        ref = fx['reference']
        r = nav['periods'][f]['SI'] * 100
        rr = nav['periods'][ref]['SI'] * 100
        act = r - rr
        ahead += act > 0.005
        rows.append(f'<tr><td><span class="chip" style="--c:{fx["color"]}"></span>{f}</td>'
                    f'<td class="tl">{esc(fx["horizon"]).replace(" years", " yrs")}</td><td class="tl">{esc(fx["role"])}</td>'
                    f'<td class="tl">{esc(ref)}</td><td class="num">{sgn(r)}%</td><td class="num">{sgn(rr)}%</td>'
                    f'<td class="num {cls(act, 0.005)}">{sgn(act)} pp</td></tr>')

    # --- policy books by sleeve, in the platform's sleeve order
    labels = nav['labels']
    sleeves = [k for k in labels if any(nav['books'][f].get(k, 0) > 0.0005 for f in FUNDS)]
    hold = []
    for k in sleeves:
        cells = ''.join(f'<td class="num">{nav["books"][f][k] * 100:.1f}%</td>' if nav['books'][f].get(k, 0) > 0.0005
                        else '<td class="num muted">—</td>' for f in FUNDS)
        hold.append(f'<tr><td>{esc(labels[k])}</td>{cells}</tr>')

    # --- flagship sparkline
    sp = ['<svg viewBox="0 0 320 96" role="img" aria-label="Daily NAV of the five funds since launch, base 100.">']
    sa, sb = min(min(S[f]) for f in FUNDS), max(max(S[f]) for f in FUNDS)
    syy = lambda v: 88 - (v - sa) / max(sb - sa, 1e-6) * 80
    sp.append(f'<line x1="4" y1="{syy(100):.1f}" x2="316" y2="{syy(100):.1f}" class="sp-base"></line>')
    for f in FUNDS:
        sp.append(f'<polyline fill="none" stroke="{facts[f]["color"]}" stroke-width="1.6" stroke-linejoin="round" '
                  f'points="{pts((4 + i * 312 / (n - 1), syy(v)) for i, v in enumerate(S[f]))}"></polyline>')
    sp.append('</svg>')

    best = order[0]
    keys = {
        'nav.asof': d_long(dates[-1]),
        'nav.asof_short': d_short(dates[-1]),
        'nav.from': d_short(dates[0]),
        'nav.days': str(n),
        'nav.best': f'{sgn(last[best] - 100)}%',
        'nav.best_name': best,
        'nav.ahead': f'{ahead} of {len(FUNDS)}',
    }
    snap = {'asof': dates[-1], 'days': n, 'nav': {f: round(last[f], 4) for f in FUNDS},
            'since_launch_pct': {f: round(last[f] - 100, 4) for f in FUNDS}}
    return {'navchart': chart, 'navboard': '\n'.join(board), 'tape-funds': '\n'.join(tape),
            'fundtable': '\n'.join(rows), 'holdings': '\n'.join(hold), 'spark-nav': ''.join(sp),
            'navdata': '<script type="application/json" id="navData">' + json.dumps(data, separators=(',', ':')) + '</script>'}, keys, snap


# ---------------------------------------------------------------- MRS
def regime_of(z):
    for name, lo, hi in BANDS:
        if (lo is None or z >= lo) and (hi is None or z < hi):
            return name
    return 'Neutral'


def mrs_block(rows, meta):
    n = len(rows)
    z = [r['composite'] for r in rows]
    last = rows[-1]
    reg = last.get('regime_confirmed') or last.get('regime_raw')
    conf = [r['regime_confirmed'] for r in rows if r.get('regime_confirmed')]
    counts = {b[0]: conf.count(b[0]) for b in BANDS}
    trans = sum(1 for a, b in zip(conf, conf[1:]) if a != b)
    years = int(rows[-1]['date'][:4]) - int(rows[0]['date'][:4])
    first_conf = next(r['date'] for r in rows if r.get('regime_confirmed'))

    # contraction episodes = dips of the composite below the Contraction threshold; dips less than
    # twelve months apart are one episode (the GFC crosses, recovers briefly, and crosses again)
    eps, last_i = [], -99
    for i, r in enumerate(rows):
        if r['composite'] < -1.00:
            if eps and i - last_i <= 12:
                if r['composite'] < eps[-1]['composite']:
                    eps[-1] = r
            else:
                eps.append(r)
            last_i = i
    named = []
    for e in eps:
        yv = int(e['date'][:4])
        nm = 'the GFC' if 2007 <= yv <= 2009 else ('COVID' if yv == 2020 else m_short(e['date']))
        named.append((nm, e))
    gfc = min((r for r in rows if '2007' <= r['date'][:4] <= '2009'), key=lambda r: r['composite'])

    # --- band chart, 1440 x 300: y = Y(z), regime bands shaded
    W, X1 = 1440, 1300
    zt, zb, yt, yb = 1.40, -2.40, 18.0, 282.0
    Y = lambda v: yt + (zt - max(min(v, zt), zb)) / (zt - zb) * (yb - yt)
    dx = X1 / (n - 1)
    line = [(i * dx, Y(v)) for i, v in enumerate(z)]
    o = [f'<svg viewBox="0 0 {W} 300" role="img" aria-label="The Macro Regime Score composite z-score from '
         f'{m_long(rows[0]["date"])} to {m_long(last["date"])} plotted against four regime bands. '
         + '; '.join(f'it falls to {neg(e["composite"])} in {m_long(e["date"])}' for _, e in named)
         + (' — the only excursions into the Contraction band.' if named else '.') + '">']
    edges = [zt, 0.35, -0.30, -1.00, zb]
    fills = ['rgba(79,179,165,.07)', 'rgba(124,135,155,.05)', 'rgba(201,164,92,.08)', 'rgba(217,112,107,.09)']
    for (t, b_), fc in zip(zip(edges, edges[1:]), fills):
        o.append(f'<rect x="0" y="{Y(t):.1f}" width="{W}" height="{Y(b_) - Y(t):.1f}" fill="{fc}"></rect>')
    for t in (0.35, -0.30):
        o.append(f'<line class="gl" x1="0" y1="{Y(t):.1f}" x2="{W}" y2="{Y(t):.1f}"></line>')
    o.append(f'<line class="zl" x1="0" y1="{Y(-1.0):.1f}" x2="{W}" y2="{Y(-1.0):.1f}"></line>')
    o.append(f'<polyline class="mrs-area" stroke="none" points="0.0,{yb:.1f} {pts(line)} {X1:.1f},{yb:.1f}"></polyline>')
    o.append(f'<polyline id="heroLine" class="mrs-line" fill="none" stroke-width="2.1" stroke-linejoin="round" '
             f'stroke-linecap="round" points="{pts(line)}"></polyline>')
    ly = Y(z[-1])
    o.append(f'<line x1="{X1}" y1="{ly:.1f}" x2="{X1 + 18}" y2="{ly:.1f}" class="mrs-lead"></line>')
    o.append(f'<circle cx="{X1}" cy="{ly:.1f}" r="4.5" class="mrs-dot"></circle>')
    o.append(f'<text class="endlbl" x="1428" y="{ly - 11:.1f}" text-anchor="end">{m_short(last["date"]).upper()} · {reg.upper()}</text>')
    o.append(f'<text class="endval" x="1428" y="{ly + 7:.1f}" text-anchor="end">{sgn(z[-1])} z</text>')
    for (name, t, b_) in zip(['EXPANSION', 'NEUTRAL', 'SLOWDOWN', 'CONTRACTION'], edges, edges[1:]):
        o.append(f'<text class="bandlbl" x="16" y="{Y(t) + 19:.1f}">{name}</text>')
    y0 = int(rows[0]['date'][:4])
    for yr in range(y0 + 1, int(last['date'][:4]) + 1):
        if (yr % 4 == 0 and yr - y0 >= 3 and int(last['date'][:4]) - yr >= 2) or yr == int(last['date'][:4]):
            i = next(k for k, r in enumerate(rows) if r['date'][:4] == str(yr))
            o.append(f'<text class="yr" x="{i * dx:.0f}" y="296" text-anchor="middle">{yr}</text>')
    o.append('</svg>')

    words = {1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five'}
    foot = (f'{words.get(len(named), str(len(named)))} contraction{"s" if len(named) != 1 else ""} in {years} years — '
            + ' and '.join(f'{nm} at <strong>{neg(e["composite"])}</strong>' for nm, e in named)
            + '. Nothing else crosses the line.')

    tot = len(conf)
    bars = []
    for name in sorted(counts, key=lambda k: -counts[k]):
        p = counts[name] / tot * 100
        lo_hi = next(b for b in BANDS if b[0] == name)
        rng = (f'composite at or above +{lo_hi[1]:.2f}' if lo_hi[2] is None else
               f'composite below {neg(lo_hi[2])}' if lo_hi[1] is None else
               f'composite between {neg(lo_hi[1])} and {sgn(lo_hi[2])}')
        inv = ' inv' if p >= 75 else ''
        bars.append(f'<li class="hb" title="{name} — {p:.1f}% of months, {rng}"><span class="hb-l"><b>{name}</b></span>'
                    f'<span class="hb-t{inv}" style="--w:{p:.1f}%;--c:{REG_COL[name]}"><span class="hb-b"></span>'
                    f'<span class="hb-v">{p:.1f}%</span></span></li>')

    # flagship sparkline
    sp = ['<svg viewBox="0 0 320 96" role="img" aria-label="Macro Regime Score composite since 2003; the Contraction band is shaded.">']
    sY = lambda v: 6 + (zt - max(min(v, zt), zb)) / (zt - zb) * 84
    sp.append(f'<rect x="4" y="{sY(-1):.1f}" width="312" height="{90 - sY(-1):.1f}" class="sp-band"></rect>')
    sp.append(f'<line x1="4" y1="{sY(-1):.1f}" x2="316" y2="{sY(-1):.1f}" class="sp-thr"></line>')
    sp.append(f'<polyline fill="none" class="sp-line" stroke-width="1.5" stroke-linejoin="round" '
              f'points="{pts((4 + i * 312 / (n - 1), sY(v)) for i, v in enumerate(z))}"></polyline>')
    sp.append(f'<circle cx="316" cy="{sY(z[-1]):.1f}" r="3" class="sp-dot"></circle></svg>')

    kpis = (f'<div class="kpi"><div class="v">{neg(gfc["composite"])}</div><div class="k">GFC trough, {m_short(gfc["date"])}</div></div>'
            '<div class="kpi"><div class="v">9 months</div><div class="k">Raw signal before NBER</div></div>'
            f'<div class="kpi"><div class="v">{trans}</div><div class="k">Transitions in {years} years</div></div>'
            '<div class="kpi"><div class="v">0.989</div><div class="k">Equal-weight robustness corr.</div></div>')

    keys = {
        'mrs.month': m_long(last['date']),
        'mrs.month_short': m_short(last['date']),
        'mrs.mon': MO[int(last['date'][5:7]) - 1],
        'mrs.z': f'{sgn(z[-1])}z',
        'mrs.regime': reg,
        'mrs.in_regime': ordinal(int(last.get('months_in_regime') or 1)),
        'mrs.months': str(n),
        'mrs.range': f'{m_short(rows[0]["date"])} — {m_short(last["date"])}',
        'mrs.conf_n': str(tot),
        'mrs.conf_range': f'{m_short(first_conf)} – {m_short(last["date"])}',
        'mrs.years': str(years),
    }
    snap = {'through': last['date'], 'months': n, 'composite': z[-1], 'regime': reg,
            'months_in_regime': last.get('months_in_regime'), 'transitions': trans,
            'freq_pct': {k: round(v / tot * 100, 1) for k, v in counts.items()},
            'generated_at': meta.get('generated_at')}
    return {'mrsband': '\n'.join(o), 'mrsfoot': foot, 'mrsfreq': '\n'.join(bars), 'spark-mrs': ''.join(sp),
            'mrskpis': kpis}, keys, snap


# ---------------------------------------------------------------- Convexity Lab rates
def bootstrap(curve, shift=0.0):
    """Semiannual par bootstrap with linear par interpolation — the Lab's own method (matches its zeroCurve)."""
    p = sorted((c['maturity'], c['yield'] + shift) for c in curve if c['maturity'] >= 0.5)

    def par(t):
        if t <= p[0][0]:
            return p[0][1]
        for (a, ya), (b, yb) in zip(p, p[1:]):
            if a <= t <= b:
                return ya + (yb - ya) * (t - a) / (b - a)
        return p[-1][1]
    D = []
    for k in range(1, 61):
        c = par(k / 2)
        D.append((1 - c / 2 * sum(D)) / (1 + c / 2))
    return D


def bond_price(D, cpn=0.04, yrs=10):
    n = yrs * 2
    return sum(cpn / 2 * 100 * D[k] for k in range(n)) + 100 * D[n - 1]


def convexity(curve):
    P0 = bond_price(bootstrap(curve))
    dv01 = bond_price(bootstrap(curve, -0.0001)) - P0          # one-sided 1bp bump, as the Lab measures DV01
    dur = dv01 / P0 / 0.0001
    shocks = [s / 10000 for s in range(-100, 101, 5)]
    g = []
    for s in shocks:
        ex = bond_price(bootstrap(curve, s))
        g.append((s, ex, P0 * (1 - dur * s), ex - P0 * (1 - dur * s)))
    return P0, dur, g


def cvx_block(rates):
    P0, dur, g = convexity(rates['curve'])
    ad = rates['asOf']                                   # MM/DD/YYYY
    mm, dd, yy = ad.split('/')
    iso = f'{yy}-{mm}-{dd}'
    W, H, X0, X1, Y0, Y1 = 480, 250, 44, 462, 22, 206
    top = max(0.4, math.ceil(max(x[3] for x in g) * 10) / 10)
    Y = lambda v: Y1 - v / top * (Y1 - Y0)
    X = lambda s: X0 + (s + 0.01) / 0.02 * (X1 - X0)
    pick = {round(x[0] * 1e4): x for x in g}
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Convexity gain of a synthetic 10-year 4 percent bond on the '
         f'{d_long(iso)} curve: exact repricing minus the duration-only estimate, per 100 face. '
         + ', '.join(f'{sgn(pick[b][3])} at {sgn(b, 0)} basis points' for b in (-100, -50, 50, 100))
         + ' — positive whichever way rates move.">']
    k = 0.0
    while k <= top + 1e-9:
        o.append(f'<line class="{"zl" if k == 0 else "gl"}" x1="{X0}" y1="{Y(k):.1f}" x2="{X1}" y2="{Y(k):.1f}"></line>'
                 f'<text class="ax" x="{X0 - 8}" y="{Y(k) + 4:.1f}" text-anchor="end">{k:.1f}</text>')
        k = round(k + 0.1, 10)
    for b, anc in ((-100, 'start'), (-50, 'middle'), (0, 'middle'), (50, 'middle'), (100, 'end')):
        o.append(f'<text class="ax" x="{X(b / 1e4):.1f}" y="{H - 24}" text-anchor="{anc}">{sgn(b, 0) if b else "0"} bp</text>')
    curve = [(X(x[0]), Y(x[3])) for x in g]
    o.append(f'<polygon class="cvx-area" points="{X0:.1f},{Y1:.1f} {pts(curve)} {X1:.1f},{Y1:.1f}"></polygon>')
    o.append(f'<polyline class="cvx-line" fill="none" stroke-width="2.2" points="{pts(curve)}"></polyline>')
    for b in (-100, -50, 0, 50, 100):
        s, ex, du, gn = pick[b]
        o.append(f'<circle class="cvx-dot" cx="{X(s):.1f}" cy="{Y(gn):.1f}" r="4"><title>{sgn(b, 0)} bp: exact price {ex:.2f}, '
                 f'duration-only {du:.2f}, convexity gain {sgn(gn, 3)}</title></circle>')
        if b:
            anc = 'start' if b < 0 else 'end'
            o.append(f'<text class="val" x="{X(s) + (10 if b < 0 else -10):.1f}" y="{Y(gn) - 10:.1f}" text-anchor="{anc}">{sgn(gn)}</text>')
    o.append('</svg>')

    sp = ['<svg viewBox="0 0 320 96" role="img" aria-label="Convexity gain of a 10-year bond under rate shocks: positive whichever way rates move.">']
    sx = lambda s: 4 + (s + 0.01) / 0.02 * 312
    syv = lambda v: 88 - v / top * 76
    cv = [(sx(x[0]), syv(x[3])) for x in g]
    sp.append(f'<line x1="4" y1="88" x2="316" y2="88" class="sp-base"></line>')
    sp.append(f'<polygon class="sp-fill" points="4,88 {pts(cv)} 316,88"></polygon>')
    sp.append(f'<polyline fill="none" class="sp-line" stroke-width="1.8" points="{pts(cv)}"></polyline>')
    for b in (-100, -50, 0, 50, 100):
        sp.append(f'<circle cx="{sx(b / 1e4):.1f}" cy="{syv(pick[b][3]):.1f}" r="2.6" class="sp-dot2"></circle>')
    sp.append('</svg>')
    keys = {'cvx.asof': d_long(iso)}
    snap = {'curve_asof': iso, 'price': round(P0, 4), 'duration': round(dur, 4),
            'gain': {str(b): round(pick[b][3], 4) for b in (-100, -50, 50, 100)}}
    return {'cvxchart': '\n'.join(o), 'spark-cvx': ''.join(sp)}, keys, snap


# ---------------------------------------------------------------- page rewrite
def mc_block(books):
    """Ten-year Monte Carlo fan for DAA from the dashboard's block bootstrap, against SAA and 60/40 medians."""
    mc = books['books']['daa']['monte_carlo']
    fan, prm = mc['fan'], mc['params']
    summ = {r['strategy']: r for r in mc['summary']}
    W, H, X0, X1, Y0, Y1 = 600, 260, 44, 548, 14, 226
    yrs = [0] + list(fan['DAA']['years'])
    def ser(k, p): return [1.0] + list(fan[k][p])
    hi = max(ser('DAA', 'p95') + ser('SAA', 'p95')); lo = min(ser('DAA', 'p5') + [1.0])
    lo, hi = math.floor(lo * 4) / 4, math.ceil(hi * 4) / 4
    X = lambda t: X0 + (X1 - X0) * t / yrs[-1]
    Y = lambda v: Y1 - (Y1 - Y0) * (v - lo) / (hi - lo)
    P = lambda arr: ' '.join(f'{X(t):.1f},{Y(v):.1f}' for t, v in zip(yrs, arr))
    band = lambda a, b: P(ser('DAA', a)) + ' ' + ' '.join(f'{X(t):.1f},{Y(v):.1f}' for t, v in reversed(list(zip(yrs, ser('DAA', b)))))
    d, sa, b6 = summ['DAA'], summ['SAA'], summ['60/40']
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Ten-year Monte Carlo for DAA, {prm["n_paths"]:,} block-bootstrap paths: '
         f'median growth of one dollar {d["terminal_median"]:.2f}, fifth percentile {d["terminal_p5"]:.2f}, ninety-fifth {d["terminal_p95"]:.2f}; '
         f'60/40 median {b6["terminal_median"]:.2f}.">']
    t = lo
    while t <= hi + 1e-9:
        o.append(f'<line class="gl" x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}"></line>'
                 f'<text class="ax" x="{X0 - 8}" y="{Y(t) + 4:.1f}" text-anchor="end">{t:.1f}×</text>')
        t += 0.5
    for yv in range(0, int(yrs[-1]) + 1, 2):
        o.append(f'<text class="ax" x="{X(yv):.1f}" y="{H - 10}" text-anchor="middle">{"Today" if yv == 0 else f"Yr {yv}"}</text>')
    o.append(f'<polygon class="fan-90" points="{band("p95", "p5")}"></polygon>')
    o.append(f'<polygon class="fan-50" points="{band("p75", "p25")}"></polygon>')
    o.append(f'<polyline class="fan-6040" fill="none" points="{P(ser("60/40", "p50"))}"></polyline>')
    o.append(f'<polyline class="fan-saa" fill="none" points="{P(ser("SAA", "p50"))}"></polyline>')
    o.append(f'<polyline class="fan-p50" fill="none" points="{P(ser("DAA", "p50"))}"></polyline>')
    for k, cls_, dy in (('p95', 'fan-lbl', -6), ('p50', 'fan-lbl on', 4), ('p5', 'fan-lbl', 12)):
        v = ser('DAA', k)[-1]
        o.append(f'<text class="{cls_}" x="{X1 + 6}" y="{Y(v) + dy:.1f}">{v:.2f}×</text>')
    o.append('</svg>')
    kp = (f'<div class="kpi"><div class="v">{d["cagr_median"]:.1f}%<span class="ar">vs</span>{b6["cagr_median"]:.1f}%</div><div class="k">Median CAGR · DAA vs 60/40</div></div>'
          f'<div class="kpi"><div class="v">{d["terminal_p5"]:.2f}×<span class="ar">vs</span>{b6["terminal_p5"]:.2f}×</div><div class="k">Bad-case (p5) growth of $1</div></div>'
          f'<div class="kpi"><div class="v">{neg(d["maxdd_median"], 1, "%")}<span class="ar">vs</span>{neg(b6["maxdd_median"], 1, "%")}</div><div class="k">Median worst drawdown</div></div>'
          f'<div class="kpi"><div class="v">{d["prob_loss"]:.1f}%<span class="ar">vs</span>{b6["prob_loss"]:.1f}%</div><div class="k">Paths that lose money</div></div>')
    snap = {'n_paths': prm['n_paths'], 'horizon_years': prm['horizon_years'], 'block_months': prm['block_months'],
            'history_window': prm['history_window'], 'daa': {k: d[k] for k in ('cagr_median', 'terminal_p5', 'maxdd_median', 'prob_loss')},
            '6040': {k: b6[k] for k in ('cagr_median', 'terminal_p5', 'maxdd_median', 'prob_loss')}}
    keys = {'mc.paths': f'{prm["n_paths"]:,}', 'mc.years': str(prm['horizon_years']), 'mc.block': str(prm['block_months']),
            'mc.window': prm['history_window'].replace(' — ', '–')}
    return {'mcfan': ''.join(o), 'mckpis': kp}, keys, snap


def apply(html, blocks, keys):
    """Rewrite every generated block the page carries; blocks the page does not use are skipped."""
    used = 0
    for name, content in blocks.items():
        pat = re.compile(r'(<!--gen:' + re.escape(name) + r'-->)(.*?)(<!--/gen:' + re.escape(name) + r'-->)', re.S)
        if not pat.search(html):
            continue
        used += 1
        html = pat.sub(lambda m: m.group(1) + content + m.group(3), html)
    if not used:
        raise FeedError('index.html carries no <!--gen:...--> block to refresh')
    unknown = set(re.findall(r'<!--gen:([\w-]+)-->', html)) - set(blocks)
    if unknown:
        raise FeedError('index.html has gen blocks the script does not produce: ' + ', '.join(sorted(unknown)))
    for k, v in keys.items():
        pat = re.compile(r'(<(\w+)\b[^>]*\bdata-k="' + re.escape(k) + r'"[^>]*>)(.*?)(</\2>)', re.S)
        html, n = pat.subn(lambda m: m.group(1) + v + m.group(4), html)
    missing = set(re.findall(r'data-k="([^"]+)"', html)) - set(keys)
    if missing:
        raise FeedError('index.html uses data-k keys the script does not produce: ' + ', '.join(sorted(missing)))
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    prev = None
    if os.path.exists(SNAP):
        with open(SNAP, encoding='utf-8') as f:
            prev = json.load(f)
    try:
        nav, mrs, meta, rates, books = load(a.src)
        validate(nav, mrs, meta, rates, books, prev)
        b1, k1, s1 = fund_block(nav)
        b2, k2, s2 = mrs_block(mrs, meta)
        b3, k3, s3 = cvx_block(rates)
        b4, k4, s4 = mc_block(books)
        blocks = {**b1, **b2, **b3, **b4}
        keys = {**k1, **k2, **k3, **k4}
        latest = max(s1['asof'], s2['through'], s3['curve_asof'])
        keys['site.asof'] = d_long(latest)
        with open(PAGE, encoding='utf-8') as f:
            html = f.read()
        new = apply(html, blocks, keys)
    except (FeedError, KeyError, ValueError, OSError) as e:
        print(f'refresh refused: {e}', file=sys.stderr)
        sys.exit(1)
    snap = {'built': date.today().isoformat(), 'sources': URLS, 'nav': s1, 'mrs': s2, 'convexity': s3, 'monte_carlo': s4}
    print(f"funds  through {s1['asof']}  ({s1['days']} trading days)  " +
          '  '.join(f"{f} {v:.2f}" for f, v in s1['nav'].items()))
    print(f"MRS    through {s2['through']}  {s2['regime']} {s2['composite']:+.4f}z  "
          f"{s2['months']} months  {s2['transitions']} transitions")
    print(f"rates  curve {s3['curve_asof']}  10Y 4% price {s3['price']:.2f}  gains {s3['gain']}")
    if a.check:
        print('check only — nothing written')
        return
    changed = new != html
    with open(PAGE, 'w', encoding='utf-8') as f:
        f.write(new)
    os.makedirs(os.path.dirname(SNAP), exist_ok=True)
    with open(SNAP, 'w', encoding='utf-8') as f:
        json.dump(snap, f, indent=1)
        f.write('\n')
    print('index.html updated' if changed else 'index.html already current')


if __name__ == '__main__':
    main()

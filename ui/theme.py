"""
Visual theme for the app: a clean, minimal, production-grade look.

Everything here is presentation only. It injects a global CSS layer over
Streamlit's defaults, defines a matching Plotly template, and provides small
HTML render helpers (hero, section headers, badges, insight cards).

Palette (Tailwind slate + indigo — restrained, modern):
  ink     #0F172A   text
  muted   #64748B   secondary text
  line    #E2E8F0   borders
  surface #FFFFFF   cards
  canvas  #F6F7FB   page background
  accent  #4F46E5   indigo primary
"""

from __future__ import annotations

import html

PALETTE = {
    "ink": "#0F172A",
    "muted": "#64748B",
    "line": "#E2E8F0",
    "surface": "#FFFFFF",
    "canvas": "#F6F7FB",
    "accent": "#4F46E5",
    "accent_soft": "#EEF0FF",
    "good": "#059669",
    "good_soft": "#ECFDF5",
    "warn": "#D97706",
    "warn_soft": "#FFF7ED",
    "bad": "#DC2626",
    "bad_soft": "#FEF2F2",
}

# Categorical colorway for charts — muted, elegant, colour-blind friendly-ish.
CHART_COLORWAY = [
    "#4F46E5", "#0EA5E9", "#10B981", "#F59E0B",
    "#EC4899", "#8B5CF6", "#14B8A6", "#EF4444",
]

FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)


def inject_global_css() -> str:
    """Return a <style> block styling the whole app. Use with st.markdown(...)."""
    p = PALETTE
    return f"""
<style>
:root {{
  --ink:{p['ink']}; --muted:{p['muted']}; --line:{p['line']};
  --surface:{p['surface']}; --canvas:{p['canvas']}; --accent:{p['accent']};
  --accent-soft:{p['accent_soft']};
}}

/* ---- App shell -------------------------------------------------------- */
.stApp {{ background: var(--canvas); }}
.block-container {{
  max-width: 1080px;
  padding-top: 2.2rem; padding-bottom: 4rem;
}}
html, body, [class*="css"] {{ font-family: {FONT_STACK}; color: var(--ink); }}

/* Hide Streamlit chrome for a cleaner, product-like surface */
#MainMenu, footer, header [data-testid="stToolbar"] {{ visibility: hidden; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* ---- Typography ------------------------------------------------------- */
h1, h2, h3 {{ letter-spacing: -0.02em; font-weight: 700; color: var(--ink); }}
h2 {{ font-size: 1.28rem; margin-top: 0.4rem; }}
h3 {{ font-size: 1.05rem; }}
a {{ color: var(--accent); }}

/* ---- Hero ------------------------------------------------------------- */
.hero {{
  background: linear-gradient(135deg, #ffffff 0%, #f3f4ff 100%);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 1.9rem 2rem;
  box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(79,70,229,.06);
  margin-bottom: 1.4rem;
}}
.hero h1 {{ font-size: 1.9rem; margin: 0 0 .4rem 0; }}
.hero .sub {{ color: var(--muted); font-size: .98rem; max-width: 62ch; line-height:1.55; }}
.pillrow {{ display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1.1rem; }}
.pill {{
  display:inline-flex; align-items:center; gap:.4rem;
  background: var(--surface); border:1px solid var(--line);
  border-radius: 999px; padding:.32rem .7rem; font-size:.8rem; color:var(--muted);
}}
.pill b {{ color: var(--ink); font-weight:600; }}
.pill .dot {{ width:.5rem; height:.5rem; border-radius:50%; background:var(--accent); }}
.pill.ok .dot {{ background:{p['good']}; }}

/* ---- Section label ---------------------------------------------------- */
.sec {{
  display:flex; align-items:center; gap:.6rem; margin:1.6rem 0 .7rem 0;
}}
.sec .bar {{ width:.28rem; height:1.15rem; border-radius:3px; background:var(--accent); }}
.sec h2 {{ margin:0; }}
.sec .hint {{ color:var(--muted); font-size:.85rem; margin-left:.2rem; }}

/* ---- Cards ------------------------------------------------------------ */
.card {{
  background: var(--surface); border:1px solid var(--line);
  border-radius:14px; padding:1.1rem 1.2rem;
  box-shadow: 0 1px 2px rgba(16,24,40,.04);
}}

/* ---- Metric tiles (restyle st.metric) --------------------------------- */
[data-testid="stMetric"] {{
  background: var(--surface); border:1px solid var(--line);
  border-radius:14px; padding:1rem 1.1rem;
  box-shadow:0 1px 2px rgba(16,24,40,.04);
}}
[data-testid="stMetricLabel"] {{ color:var(--muted); font-weight:500; }}
[data-testid="stMetricValue"] {{ font-weight:700; letter-spacing:-.02em; }}

/* ---- Tabs ------------------------------------------------------------- */
[data-testid="stTabs"] [role="tablist"] {{ gap:.3rem; border-bottom:1px solid var(--line); }}
[data-testid="stTabs"] [role="tab"] {{
  padding:.55rem .9rem; border-radius:9px 9px 0 0; color:var(--muted);
  font-weight:600; font-size:.92rem;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
  color:var(--accent); background:var(--accent-soft);
}}

/* ---- Buttons ---------------------------------------------------------- */
.stButton > button, .stDownloadButton > button {{
  border-radius:11px; font-weight:600; border:1px solid var(--line);
  padding:.55rem 1.1rem; transition:all .15s ease;
}}
.stButton > button[kind="primary"] {{
  background:var(--accent); border-color:var(--accent);
  box-shadow:0 6px 16px rgba(79,70,229,.22);
}}
.stButton > button[kind="primary"]:hover {{ filter:brightness(1.05); transform:translateY(-1px); }}
.stDownloadButton > button:hover {{ border-color:var(--accent); color:var(--accent); }}

/* ---- Uploader --------------------------------------------------------- */
[data-testid="stFileUploaderDropzone"] {{
  background:var(--surface); border:1.5px dashed #C7CBD8; border-radius:14px;
}}

/* ---- Dataframes / expanders ------------------------------------------- */
[data-testid="stDataFrame"] {{ border:1px solid var(--line); border-radius:12px; }}
[data-testid="stExpander"] {{ border:1px solid var(--line); border-radius:12px; background:var(--surface); }}

/* ---- Insight cards ---------------------------------------------------- */
.insights {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:.8rem; }}
.icard {{
  background:var(--surface); border:1px solid var(--line); border-left-width:4px;
  border-radius:12px; padding:.85rem 1rem; box-shadow:0 1px 2px rgba(16,24,40,.03);
}}
.icard .k {{ display:flex; align-items:center; gap:.5rem; font-weight:700; font-size:.92rem; }}
.icard .d {{ color:var(--muted); font-size:.86rem; margin-top:.3rem; line-height:1.5; }}
.icard .tag {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); font-weight:600; }}
.icard.info {{ border-left-color:var(--accent); }}
.icard.good {{ border-left-color:{p['good']}; }}
.icard.warn {{ border-left-color:{p['warn']}; }}
.icard.bad  {{ border-left-color:{p['bad']}; }}

/* ---- Badges ----------------------------------------------------------- */
.badge {{ display:inline-flex; align-items:center; gap:.4rem; border-radius:999px;
  padding:.3rem .75rem; font-size:.82rem; font-weight:600; }}
.badge.good {{ background:{p['good_soft']}; color:{p['good']}; }}
.badge.warn {{ background:{p['warn_soft']}; color:{p['warn']}; }}

/* ---- Takeaways list --------------------------------------------------- */
.takeaways {{ background:var(--accent-soft); border:1px solid #DDE0FF; border-radius:14px;
  padding:1rem 1.2rem 1rem 1.2rem; }}
.takeaways ul {{ margin:.2rem 0 0 0; padding-left:1.1rem; }}
.takeaways li {{ margin:.35rem 0; line-height:1.55; }}
</style>
"""


# --- HTML fragment helpers (rendered via st.markdown(..., unsafe_allow_html)) --
def hero(title: str, subtitle: str, pills: list[tuple[str, str, bool]]) -> str:
    """pills: list of (label, value, is_ok)."""
    pill_html = "".join(
        f'<span class="pill {"ok" if ok else ""}"><span class="dot"></span>'
        f'{html.escape(label)}&nbsp;<b>{html.escape(value)}</b></span>'
        for label, value, ok in pills
    )
    return (
        f'<div class="hero"><h1>{html.escape(title)}</h1>'
        f'<div class="sub">{html.escape(subtitle)}</div>'
        f'<div class="pillrow">{pill_html}</div></div>'
    )


def section(title: str, hint: str = "") -> str:
    hint_html = f'<span class="hint">{html.escape(hint)}</span>' if hint else ""
    return f'<div class="sec"><span class="bar"></span><h2>{html.escape(title)}</h2>{hint_html}</div>'


def badge(text: str, kind: str = "good") -> str:
    return f'<span class="badge {kind}">{html.escape(text)}</span>'


def insight_cards(findings: list[dict]) -> str:
    """findings: list of {category,title,detail,severity,icon}."""
    cards = []
    for f in findings:
        sev = f.get("severity", "info")
        icon = f.get("icon", "•")
        cards.append(
            f'<div class="icard {sev}">'
            f'<div class="tag">{html.escape(f.get("category",""))}</div>'
            f'<div class="k">{icon}&nbsp;{html.escape(f.get("title",""))}</div>'
            f'<div class="d">{html.escape(f.get("detail",""))}</div>'
            f"</div>"
        )
    return f'<div class="insights">{"".join(cards)}</div>'


def takeaways_block(items: list[str]) -> str:
    lis = "".join(f"<li>{html.escape(i)}</li>" for i in items)
    return f'<div class="takeaways"><ul>{lis}</ul></div>'


def apply_plotly_template():
    """Register and set a clean default Plotly template for all charts."""
    import plotly.graph_objects as go
    import plotly.io as pio

    p = PALETTE
    tmpl = go.layout.Template()
    tmpl.layout = go.Layout(
        colorway=CHART_COLORWAY,
        font=dict(family=FONT_STACK, size=13, color=p["ink"]),
        paper_bgcolor="white",
        plot_bgcolor="white",
        title=dict(font=dict(size=15, color=p["ink"]), x=0.01, xanchor="left"),
        margin=dict(l=56, r=24, t=52, b=48),
        xaxis=dict(gridcolor="#EEF1F6", zerolinecolor="#E2E8F0",
                   linecolor="#E2E8F0", ticks="outside", tickcolor="#E2E8F0"),
        yaxis=dict(gridcolor="#EEF1F6", zerolinecolor="#E2E8F0",
                   linecolor="#E2E8F0", ticks="outside", tickcolor="#E2E8F0"),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
        colorscale=dict(sequential=[[0, "#EEF0FF"], [1, p["accent"]]]),
        hoverlabel=dict(font=dict(family=FONT_STACK)),
    )
    pio.templates["insight_clean"] = tmpl
    pio.templates.default = "insight_clean"

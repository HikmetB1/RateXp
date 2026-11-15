# TechNorth AI visual identity

The look of technorth.ai, written down so other products (the RateXp app, the
RateXp guide, decks, landing pages) can use it as well. Two themes share one system:

- **Sunburst**: the light theme
- **Midnight**: the dark theme

The reference implementation is `site/index.html` (all CSS is inline at the top of the
file). If that file and this one disagree, the site is right; update this file to match.

---

## 1. The idea in five rules

1. **Pixel cabinet.** Square corners, thick ink outlines and hard offset shadows with no
   blur. Elements look like chunky arcade parts that press in when clicked.
2. **One red, one yellow.** Red `#e23a2e` marks titles and actions. Yellow `#ffce33`
   frames things. Each is the same value in both themes.
3. **Navy is home.** Every page sits on the brand navy `#001a4d` in both themes. Content
   never touches it directly; it sits in cards inside yellow frames.
4. **Flip the surfaces, keep the meaning.** Going from light to dark changes only the
   surfaces (card colour, text, outlines). Red, yellow, green and every hover stay the same.
5. **No orange, no gradients, no rounded corners, no soft shadows.**

---

## 2. Colour

### 2.1 Fixed brand colours (identical in both themes)

| Name | Hex | Used for |
|---|---|---|
| Navy | `#001a4d` | page background, browser `theme-color` |
| Red | `#e23a2e` | section titles, primary buttons, current menu entry, wordmark, focus ring |
| Yellow | `#ffce33` | big section frames, the menu panel's frame, offset shadow behind titles, card/row hover |
| Green | `#0f9b67` | hover on every button and on chip links |
| Cream | `#fff5d4` | hover on menu entries |
| Ink | `#14233a` | text on yellow, cream and white |

### 2.2 Theme tokens (these change between themes)

| Token | Sunburst (light) | Midnight (dark) | Role |
|---|---|---|---|
| `--bg` | `#001a4d` | `#001a4d` | page |
| `--panel` | `#ffffff` | `#131f36` | card surface |
| `--panel2` | `#fff5d4` | `#1b2942` | inner surface: nested cards, inputs, zebra rows |
| `--text` | `#14233a` | `#e7eef7` | body text |
| `--muted` | `#5a6678` | `#a6b3c7` | secondary text |
| `--faint` | `#94a1b4` | `#6f7d93` | placeholders, small rules |
| `--line` | `#14233a` | `#2a3a5e` | every outline and hard shadow |
| `--accent` | `#0ea88c` | `#4fe3c1` | eyebrows, role lines, small labels, icons |
| `--good` | `#0f9b67` | `#46e0a8` | "live" dot and other success states |
| `--link` | `#2452c9` | `#4fe3c1` | inline links |
| `--box` | `#ffce33` | `#ffce33` | big frames (yellow in both) |
| `--btn` / `--btnfg` | `#e23a2e` / `#ffffff` | `#e23a2e` / `#ffffff` | titles and primary buttons |
| `--ink` | `#14233a` | `#02060e` | table header fill, wordmark text-shadow |
| `--row-border` | `rgba(20,40,70,.16)` | `rgba(255,255,255,.12)` | soft dividers |

The palettes come from RateXp's own `index.css` ("Sunburst" / "Midnight"). Midnight is
painted the way the RateXp guide paints it.

### 2.3 What each colour means

- **Red** means "this is a heading or an action". Red always has white text.
- **Yellow** means "this is a frame or a highlight". Yellow always has ink text.
- **Green** means "you are pointing at something clickable". Green always has white text.
- **Teal** (`--accent`) labels things: eyebrows, roles, small uppercase captions, icons.

---

## 3. Typography

All three fonts are on Google Fonts:

```html
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Nunito:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

| Font | Role | Sizes used |
|---|---|---|
| **Press Start 2P** | display: wordmark, titles, card headings, buttons, menu, form labels, chips, table headers | wordmark 13px · titles 13px · card headings 10-11px · buttons 10px · menu 8px · labels 8px · chips 7px |
| **Nunito 700** | body text (bold everywhere) | lede 15px/1.6 · body 13.5-14px/1.5 |
| **JetBrains Mono 500** | technical voice: eyebrows, roles, captions, code, contact details | eyebrow 11px · role 12px · caption 10px · contact 13px |

Text styles:

- **Eyebrow:** above every title. JetBrains Mono 500, 11px, `letter-spacing:.18em`,
  uppercase, `--accent`. The pattern is a number, an arrow and a phrase:
  `01 → our main solution`.
- **Caption label**, e.g. "BRINGING EXPERTISE FROM" or "CONTACT ME ON": JetBrains Mono 500,
  10px, `letter-spacing:.08em`, uppercase, `--good`.
- **Role line**, e.g. "Engineering & Sales Manager": JetBrains Mono 500, 12px, `--accent`.
- **Copy:** plain sentences. Use a spaced hyphen ` - ` as the dash, not an em dash.

---

## 4. Shape and motion

| Property | Value |
|---|---|
| Corner radius | `0` everywhere |
| Outline widths | 4px for frames, cards, buttons and inputs · 3px for titles, small cards, chips and menu entries · 2px for table cells |
| Hard shadows | `Xpx Xpx 0 var(--line)`, never blurred: 5px for frames, cards and buttons · 3px for titles and small cards · 2px for chips |
| Title shadow | `3px 3px 0 #ffce33` (yellow, both themes) |
| Press motion | hover `translate(-2px,-2px)` with the shadow growing to 7px · active `translate(5px,5px)` with the shadow at 0 · `.08s ease` |
| Chip motion | hover `translate(-1px,-1px)` with a 3px shadow · active `translate(2px,2px)` with no shadow |
| Theme change | `background-color .35s ease, color .35s ease` on `body` |

---

## 5. Layout: the nesting

Every section is built the same way, from the outside in:

```
navy page (#001a4d)
└─ yellow frame   .group  4px --line outline · 14px yellow (#ffce33) padding · 5px --line shadow
   └─ card        .card   4px --line outline · --panel fill · 5px --line shadow · padding 18px 20px
      ├─ eyebrow          "01 → our main solution"
      ├─ title (h2)       red block, white text, 3px --line outline, yellow 3px shadow
      └─ content          small cards (.item / .member) on --panel2, 3px outline, 3px shadow
```

The **side menu** uses the same build on a single element: a 4px outline, a 14px yellow
band and a 4px inner outline (drawn with inset shadows), then `--panel`, plus the 5px hard
shadow outside. On tablets and phones it becomes a bar docked to the bottom of the screen.

Spacing: 24px gap between sections, 14px gap inside a frame, 16px gap between the menu
and the page. Maximum content width is 1360px.

---

## 6. Components

| Component | At rest | Hover |
|---|---|---|
| **Section title** (`h2`) | `--btn` fill, white text, Press Start 13px, padding 7px 11px, 3px outline, yellow shadow | none |
| **Primary button** | red fill, white text, 4px outline, 5px shadow | **green** fill, white text, press motion |
| **Quiet button** (`.btn-quiet`) | `--panel` fill, `--text` | **green** fill, white text, press motion |
| **Chip link** (e.g. company names) | `--panel` fill, 3px outline, 2px shadow, Press Start 7px plus `↗` | **green** fill, white text |
| **Small card** (`.item`) | `--panel2` fill, 3px outline, 3px shadow, photo on top | **yellow** fill, all text **ink** |
| **Table row** | zebra: even rows `--panel2` | **yellow** fill, ink text |
| **Table header** | `--ink` fill, white Press Start 9px | none |
| **Menu entry** | transparent, `--text`, teal icon | **cream** fill, ink text, teal icon |
| **Current menu entry** | **red** fill, white text and icon, 3px shadow | stays red |
| **Contact menu entry** | red 3px outline | cream, like other menu entries |
| **Input** | `--panel2` fill, 4px outline, Nunito 14px | focus: `inset 3px 3px 0 rgba(0,0,0,.12)` |
| **Inline code / number chip** | JetBrains Mono, `--accent` text on `--panel2`, 1px outline | none |
| **Status pill** ("LIVE") | `--panel2`, 3px outline, blinking `--good` square | none |
| **Focus ring** | `outline:3px solid #e23a2e; outline-offset:2px` | none |

Hover colours never depend on the theme. A hovered element looks the same in Sunburst
and Midnight.

### Imagery

- Section and product photos are **black-and-white**, with `filter:contrast(1.08-1.15)`.
  They sit in a 3px ink frame with a hard shadow.
- People's portraits may be in colour and use the same frame.
- The hero (the "cabinet screen") stays dark in both themes.

---

## 7. Drop-in CSS

Paste this into any web product and switch themes with `<html data-theme="light|dark">`:

```css
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Nunito:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* Fixed brand colours - the same in both themes */
:root{
  --red:#e23a2e; --yellow:#ffce33; --green:#0f9b67; --cream:#fff5d4; --navy:#001a4d; --ink-text:#14233a;
  --hover-bg:#ffce33; --hover-fg:#14233a; --hover-soft:#fff5d4; --hover-good:#0f9b67; --hover-accent:#0ea88c;
}
/* Sunburst (light) */
:root, :root[data-theme='light']{
  --bg:#001a4d; --text:#14233a; --muted:#5a6678; --faint:#94a1b4;
  --accent:#0ea88c; --good:#0f9b67; --link:#2452c9;
  --ink:#14233a; --box:#ffce33; --panel:#ffffff; --panel2:#fff5d4;
  --btn:#e23a2e; --btnfg:#ffffff; --line:#14233a;
  --row-border:rgba(20,40,70,.16);
}
/* Midnight (dark) */
:root[data-theme='dark']{
  --bg:#001a4d; --text:#e7eef7; --muted:#a6b3c7; --faint:#6f7d93;
  --accent:#4fe3c1; --good:#46e0a8; --link:#4fe3c1;
  --ink:#02060e; --box:#ffce33; --panel:#131f36; --panel2:#1b2942;
  --btn:#e23a2e; --btnfg:#ffffff; --line:#2a3a5e;
  --row-border:rgba(255,255,255,.12);
}

body{background:var(--bg);color:var(--text);font-family:'Nunito',system-ui,sans-serif;font-weight:700}
h1,h2,h3{font-family:'Press Start 2P',monospace}
a{color:var(--link)}

.group{border:4px solid var(--line);padding:14px;background:var(--box);box-shadow:5px 5px 0 var(--line)}
.card{border:4px solid var(--line);padding:18px 20px;background:var(--panel);box-shadow:5px 5px 0 var(--line)}
h2{display:inline-block;font-size:13px;line-height:1.5;padding:7px 11px;
   color:var(--btnfg);background:var(--btn);border:3px solid var(--line);box-shadow:3px 3px 0 var(--yellow)}
.eyebrow{font-family:'JetBrains Mono',monospace;font-weight:500;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent)}

.btn{display:inline-flex;align-items:center;gap:8px;padding:11px 14px;
     font-family:'Press Start 2P',monospace;font-size:10px;line-height:1.4;text-decoration:none;
     color:var(--btnfg);background:var(--btn);border:4px solid var(--line);border-radius:0;
     box-shadow:5px 5px 0 var(--line);transition:transform .08s ease,box-shadow .08s ease}
.btn-quiet{background:var(--panel);color:var(--text)}
.btn:hover{transform:translate(-2px,-2px);box-shadow:7px 7px 0 var(--line);background:var(--hover-good);color:#fff}
.btn:active{transform:translate(5px,5px);box-shadow:0 0 0 var(--line)}

.item{border:3px solid var(--line);background:var(--panel2);box-shadow:3px 3px 0 var(--line)}
.item:hover,tbody tr:hover{background:var(--hover-bg);color:var(--hover-fg)}
:focus-visible{outline:3px solid var(--btn);outline-offset:2px}
```

---

## 8. Applying it to MkDocs Material (the RateXp guide)

The guide (ratexp-core.azurewebsites.net/guide/) already draws everything from variables
in its `ratexp.css`, one block per scheme. To bring it onto this identity, set those
variables as below. Its layout rules (cards on the navy page, header bars, code boxes)
can stay as they are.

```css
/* Sunburst */
[data-md-color-scheme="default"]{
  --md-primary-fg-color:#001a4d; --md-footer-bg-color:#001a4d;
  --md-accent-fg-color:#0f9b67;            /* hover: green */
  --md-typeset-a-color:#2452c9;            /* links */
  --md-default-fg-color:#14233a; --md-default-fg-color--light:#5a6678;
  --md-default-bg-color:#ffffff; --md-code-bg-color:#fff5d4;
  --page-bg:#001a4d; --page-text:#ffffff; --page-text-muted:#c3cde0;
  --box-bg:#ffffff; --box-line:#14233a; --box-bar:#ffce33;
  --group-bar:#e23a2e; --group-bar-text:#ffffff;    /* header bars = red titles */
  --tip-colour:#0f9b67; --note-colour:#2452c9;
  --header-bg:#ffce33; --header-text:#14233a;       /* top bar = yellow frame */
  --header-text-light:rgba(20,35,58,.7); --header-logo-filter:brightness(0) opacity(.85);
}
/* Midnight */
[data-md-color-scheme="slate"]{
  --md-primary-fg-color:#001a4d; --md-footer-bg-color:#001a4d;
  --md-accent-fg-color:#0f9b67;
  --md-typeset-a-color:#4fe3c1;
  --md-default-fg-color:#e7eef7; --md-default-fg-color--light:#a6b3c7;
  --md-default-bg-color:#131f36; --md-code-bg-color:#1b2942;
  --page-bg:#001a4d; --page-text:#e7eef7; --page-text-muted:#a6b3c7;
  --box-bg:#131f36; --box-line:#2a3a5e; --box-bar:#2a3a5e;
  --group-bar:#e23a2e; --group-bar-text:#ffffff;
  --tip-colour:#46e0a8; --note-colour:#58a6ff;
  --header-bg:#ffce33; --header-text:#14233a;
  --header-text-light:rgba(20,35,58,.7); --header-logo-filter:brightness(0) opacity(.85);
}
```

How the guide's current choices map to this identity:

| Guide today | Identity |
|---|---|
| Header bars yellow in dark, red in light | **red in both** (titles are red) |
| Top bar red in dark, yellow in light | **yellow in both** (frames and chrome are yellow) |
| Accent orange `#ff8a1e` in dark | **green `#0f9b67`** for hover; no orange |
| 1px outlines, 8px corners, no shadows | colours alone already match. For a full match use 0 corners, 3-4px outlines and hard offset shadows (sections 4-6) |
| Nunito and JetBrains Mono | same, plus **Press Start 2P** for headings, e.g. `.md-typeset h1, .md-typeset h2 { font-family:'Press Start 2P', monospace }` at a small size (13-18px) |

---

## 9. Contrast (WCAG 2.x ratios)

| Pair | Ratio | Note |
|---|---|---|
| ink on yellow | 10.6:1 | ✓ |
| ink on cream | 14.5:1 | ✓ |
| body text on dark panel | 14.1:1 | ✓ |
| muted text on dark panel | 7.7:1 | ✓ |
| ink text on white | 15.8:1 | ✓ |
| muted text on white | 5.8:1 | ✓ |
| teal link on dark panel | 10.3:1 | ✓ |
| blue link on white | 6.7:1 | ✓ |
| yellow on navy | 11.3:1 | ✓ |
| white on red | 4.3:1 | fine for the large pixel headings; just under 4.5 for small text |
| red on dark panel (wordmark) | 3.8:1 | fine for large text only |
| white on green (hover) | 3.6:1 | brief hover state on short labels; just under 4.5 |
| teal accent on white | 3.0:1 | only for large or uppercase captions |

If a product needs strict AA everywhere, keep the same hues but darken the fills under
small white text.

---

## 10. Open decisions

- **Links** are blue in Sunburst and teal in Midnight. One colour for both, teal to match
  the guide, would be more consistent.
- **Menu hover in Midnight** uses the light cream, which is very bright on the dark panel.
  A softer option is `--panel2` (`#1b2942`) with light text.

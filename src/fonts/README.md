# Fonts

The page's typeface, Atkinson Hyperlegible Next, self-hosted so that the page contacts no outside server.
Overpass is kept for `tools/make_icons.py`, which draws the icon's "TN" with it; the page does not use it.
`build.py` copies this folder, except this README, to `dist/fonts/`.

| File | Family | Weights |
|---|---|---|
| `atkinson-hyperlegible-next/atkinson-hyperlegible-next-variable.woff2` | Atkinson Hyperlegible Next, variable | 200 to 800 |
| `overpass/overpass-variable.woff2` | Overpass, variable | 600 to 800 (the file's axis runs 100 to 900) |

Each is the Latin subset only. It covers every character the page and the questions use;
the only non-ASCII ones are ® – — ’ “ ” •.

All of them are under the SIL Open Font License 1.1. Each folder holds its family's `OFL.txt`.
`tools/make_icons.py` draws the icon's "TN" with the Overpass file, so no TTF is needed.

## Where they came from

Atkinson Hyperlegible Next was downloaded on 2026-10-20 from the Google Fonts CSS API, asking with a current
Chrome user agent so the API answers with WOFF2 files, and keeping the `/* latin */` block:

- CSS: `https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@200..800&display=swap`
  - variable: `https://fonts.gstatic.com/s/atkinsonhyperlegiblenext/v7/NaPNcYPdHfdVxJw0IfIP0lvYFqijb-UxCtm5_wdGseiJn3o.woff2`
- License: `https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegiblenext/OFL.txt`

Overpass was downloaded on 2026-10-16 the same way:

- CSS: `https://fonts.googleapis.com/css2?family=Overpass:wght@600..800&display=swap`
  - variable: `https://fonts.gstatic.com/s/overpass/v19/qFdH35WCmI96Ajtm81GlU9s.woff2`
- Licenses:
  - `https://raw.githubusercontent.com/google/fonts/main/ofl/overpass/OFL.txt`

The Latin block's `unicode-range` is
`U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD`.
The `@font-face` rules in `src/app.html` leave it out, since these files hold nothing else.

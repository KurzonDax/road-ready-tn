# Fonts

The page's two typefaces, self-hosted so that the page contacts no outside server.
`build.py` copies this folder, except this README, to `dist/fonts/`.

| File | Family | Weights |
|---|---|---|
| `atkinson-hyperlegible/atkinson-hyperlegible-400.woff2` | Atkinson Hyperlegible | 400 |
| `atkinson-hyperlegible/atkinson-hyperlegible-700.woff2` | Atkinson Hyperlegible | 700 |
| `overpass/overpass-variable.woff2` | Overpass, variable | 600 to 800 (the file's axis runs 100 to 900) |

Each is the Latin subset only. It covers every character the page and the questions use;
the only non-ASCII ones are ® – — ’ “ ” •.

Both families are under the SIL Open Font License 1.1. Each folder holds its family's `OFL.txt`.
`tools/make_icons.py` draws the icon's "TN" with the Overpass file, so no TTF is needed.

## Where they came from

Downloaded on 2026-10-16 from the Google Fonts CSS API, asking with a current Chrome
user agent so the API answers with WOFF2 files, and keeping the `/* latin */` block of each:

- CSS: `https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap`
  - 400: `https://fonts.gstatic.com/s/atkinsonhyperlegible/v12/9Bt23C1KxNDXMspQ1lPyU89-1h6ONRlW45G04pIo.woff2`
  - 700: `https://fonts.gstatic.com/s/atkinsonhyperlegible/v12/9Bt73C1KxNDXMspQ1lPyU89-1h6ONRlW45G8Wbc9dCWP.woff2`
- CSS: `https://fonts.googleapis.com/css2?family=Overpass:wght@600..800&display=swap`
  - variable: `https://fonts.gstatic.com/s/overpass/v19/qFdH35WCmI96Ajtm81GlU9s.woff2`
- Licenses:
  - `https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegible/OFL.txt`
  - `https://raw.githubusercontent.com/google/fonts/main/ofl/overpass/OFL.txt`

The Latin block's `unicode-range` is
`U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD`.
The `@font-face` rules in `src/app.html` leave it out, since these files hold nothing else.

Self-hosted fonts, loaded by `next/font/local` in `../layout.tsx`. Nothing is
fetched from Google Fonts at build or run time; Google Fonts fetches had
failed Vercel builds. CSS variables, weights, styles and `display: "swap"` are
unchanged from the previous `next/font/google` setup.

All three families are licensed under the SIL Open Font License 1.1, which
permits bundling and redistribution with software. Each family's licence text
sits next to its fonts. Git blob ids are given so copies can be checked with
`git hash-object`.

## Manrope (UI/body, `--font-manrope`)

Weights 400-700. Unmodified upstream variable font, added earlier because the
Next 16.2.10 Google-font loader failed on font URLs without a recognised
filename extension.
- Manrope-Variable.ttf: google/fonts b31870aff700ab7a1d74fa0c6887d95beb9e0037
  ofl/manrope, blob 75274da58537d6123b14f2cd0c355ad4681fc2b3, 164,700 bytes.
- Manrope-OFL.txt: blob e271172a9ed0cddc895aabb6509f1c7d880b492d.

## Fraunces (`--font-fraunces`) and IBM Plex Mono (`--font-ibm-plex-mono`)

These are the latin-subset woff2 files that Google Fonts serves, committed
unmodified, byte for byte as `next/font/google` downloaded them for the
previous build. There was no renaming, re-hinting, subsetting or conversion by
us. The site already served these exact bytes from its own domain, so output
is pixel-identical.

Source: `fonts.googleapis.com/css2` requested with next/font's user agent
(Chrome 104 on macOS), `family=Fraunces:wght@500;600;700` and
`family=IBM+Plex+Mono:wght@400;500;600`, `/* latin */` blocks, 2026-10-13.
Each SHA-256 equals the matching preloaded file in a `next build` of staging
b3862e6 (`.next/static/media/*-s.p.*.woff2`).

| File | Served from | SHA-256 |
|---|---|---|
| Fraunces-latin.woff2 (wght 100-900 variable; one file for 500/600/700) | fonts.gstatic.com/s/fraunces/v38/6NUu8FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0K7iN7hzFUPJH58nib14c7qv8oRcTn.woff2 | 88e17be075f1be50ab67b057b99e3701b828f44ed28f9452df6c02645bb0cba9 |
| IBMPlexMono-Regular-latin.woff2 (400) | fonts.gstatic.com/s/ibmplexmono/v20/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2 | c36f509c0a8f9f85f29cb44bc8701d8a9e0b14c499e77a884f789ead7093a7ac |
| IBMPlexMono-Medium-latin.woff2 (500) | fonts.gstatic.com/s/ibmplexmono/v20/-F6qfjptAgt5VM-kVkqdyU8n3twJwlBFgsAXHNk.woff2 | a76f53ca6612e7b3828eec2311098675b7f9849ae4169a8bcef6302aec02a6c0 |
| IBMPlexMono-SemiBold-latin.woff2 (600) | fonts.gstatic.com/s/ibmplexmono/v20/-F6qfjptAgt5VM-kVkqdyU8n3vAOwlBFgsAXHNk.woff2 | ad4580d8cb4b5f627c2d18457656732f7f7b070f7837fbc380e08054157e6f6c |

Licences, unmodified from google/fonts 66928797f271fed5ee428544e7229685e2d90127:
- Fraunces-OFL.txt: ofl/fraunces/OFL.txt, blob 22fa7ce5733434d0c634f6e55116f410858e938c.
  No Reserved Font Name.
- IBMPlexMono-OFL.txt: ofl/ibmplexmono/OFL.txt, blob c35c4c618fab33da8695177b3a6cefe0810b7b28.
  Reserved Font Name "Plex".

Coverage: previously `next/font/google` also self-hosted latin-ext, vietnamese
and (Plex) cyrillic files behind `unicode-range`. `next/font/local` cannot set
a per-file `unicode-range`, so only latin is committed. Characters outside it
fall back to the next font in `--font-display`/`--font-mono`. No mono or
display text uses them; `name_jp` already relied on system CJK fallbacks.

### Alternative if these files ever need replacing

Google's files are subset and have the TrueType hinting stripped (Google's
Mac-targeted variant). Because of the Plex Reserved Font Name we must not
make such a modified Plex ourselves. The clean fallback is the unmodified
upstream fonts:
- IBM Plex Mono: google/fonts 66928797f271fed5ee428544e7229685e2d90127
  ofl/ibmplexmono IBMPlexMono-Regular.ttf (blob 0c9770d5183ba60dc4350d3e011b782a320761ae),
  -Medium.ttf (33c546f68b6007a45a3f10e845523abb2db25399), -SemiBold.ttf
  (8f8998a139d8f61d3b96bdd3b512fca501a1f6b9). The outlines are identical,
  but they are hinted: Linux/Windows Chrome rasterise slightly differently,
  and SemiBold's VDMX table makes `line-height: normal` boxes taller
  (13 to 18 px at 10px). On the home page this added 5px on desktop and
  10px on mobile. macOS/iOS render identically.
- Fraunces: ofl/fraunces/Fraunces[SOFT,WONK,opsz,wght].ttf (blob
  8210f9488d3c732359a9292dd09aca3f2bae830e) has four axes. Used as-is,
  optical size would follow font size and headings would change shape. Google
  pins opsz=14, SOFT=0, WONK=1 and drops `prep`. With fontTools `instancer`
  doing the same (allowed: no Reserved Font Name), this test matched Google's
  rendering to within 0.5 units per 2000-unit em.

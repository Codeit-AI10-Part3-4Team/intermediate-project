#!/usr/bin/env python3
"""Build the Claude Design upload bundle from frontend/design/ assets.

Off-script layout (no JS component bundle — this DS is tokens + fonts + brand
+ hand-authored preview cards). Usage:

    python .design-sync/build_bundle.py <output_dir>

Fails loudly on any validation error; a clean exit means the bundle is
structurally sound (static checks — visual review happens upstream on the
source previews).
"""

import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "frontend" / "design"
CONVENTIONS = REPO / ".design-sync" / "conventions.md"

# previews/<file> -> (group_dir, slug); @dsCard marker stays authoritative for display
CARD_MAP = {
    "logo.html": ("brand", "logo"),
    "colors.html": ("colors", "palette"),
    "typography.html": ("type", "typography"),
    "buttons.html": ("components", "buttons"),
    "chat.html": ("components", "chat"),
    "sources.html": ("components", "sources"),
    "upload.html": ("components", "upload"),
    "screen-home.html": ("screens", "screen-home"),
    "screen-chat.html": ("screens", "screen-chat"),
}

DSCARD_RE = re.compile(r'^<!-- @dsCard group="[^"]+" name="[^"]+" -->')
URL_RE = re.compile(r"url\(['\"]?([^'\")]+)['\"]?\)")
VAR_RE = re.compile(r"var\((--oop-[\w-]+)")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: build_bundle.py <output_dir>")
    out = Path(sys.argv[1]).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    tokens_src = (SRC / "tokens.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--oop-[\w-]+)\s*:", tokens_src))
    if not defined:
        fail("no tokens found in tokens.css")

    # tokens/ + fonts/ (verbatim)
    (out / "tokens").mkdir()
    (out / "tokens" / "tokens.css").write_text(tokens_src, encoding="utf-8")
    shutil.copytree(SRC / "fonts", out / "fonts")
    for woff in (out / "fonts").glob("*.woff2"):
        if woff.read_bytes()[:4] != b"wOF2":
            fail(f"{woff.name}: not a valid woff2 file")

    # cards: previews/<f>.html -> components/<group>/<slug>/<slug>.html
    # font refs go one level deeper twice: ../fonts/ -> ../../../fonts/
    card_paths = []
    for fname, (group, slug) in CARD_MAP.items():
        src_file = SRC / "previews" / fname
        if not src_file.exists():
            fail(f"missing preview: {fname}")
        html = src_file.read_text(encoding="utf-8")
        if not DSCARD_RE.match(html.splitlines()[0]):
            fail(f"{fname}: first line is not a @dsCard marker")
        html = html.replace("url('../fonts/", "url('../../../fonts/")
        dest = out / "components" / group / slug / f"{slug}.html"
        dest.parent.mkdir(parents=True)
        dest.write_text(html, encoding="utf-8")
        card_paths.append(dest)

    unmapped = {p.name for p in (SRC / "previews").glob("*.html")} - set(CARD_MAP)
    if unmapped:
        fail(f"previews without a CARD_MAP entry: {sorted(unmapped)}")

    # validate every url() in cards resolves inside the bundle,
    # and every var(--oop-*) is defined in tokens.css
    for card in card_paths:
        text = card.read_text(encoding="utf-8")
        for ref in URL_RE.findall(text):
            if ref.startswith(("data:", "http")):
                continue
            if not (card.parent / ref).resolve().is_file():
                fail(f"{card.relative_to(out)}: unresolved url({ref})")
        undefined = set(VAR_RE.findall(text)) - defined
        if undefined:
            fail(f"{card.relative_to(out)}: undefined tokens {sorted(undefined)}")

    # brand guidelines: logo SVG (validated XML) inline + as asset
    logo_svg = (SRC / "logo" / "oop-logo.svg").read_text(encoding="utf-8")
    ET.fromstring(logo_svg)
    (out / "guidelines" / "assets").mkdir(parents=True)
    (out / "guidelines" / "assets" / "oop-logo.svg").write_text(logo_svg, encoding="utf-8")
    (out / "guidelines" / "brand.md").write_text(
        "# 브랜드 — 로고\n\n"
        "ㅇㅇㅍ 워드마크(순수 벡터, 폰트 비의존). ㅇ 2개는 `#2C3323`(ink), "
        "ㅍ는 `#8C9963`(primary). 라이트 배경 전용.\n"
        "파일: `guidelines/assets/oop-logo.svg` — 디자인에는 아래 SVG를 인라인으로 사용.\n\n"
        f"```svg\n{logo_svg.strip()}\n```\n",
        encoding="utf-8",
    )

    # styles.css — the @import closure every rendered design receives
    faces = "\n".join(
        "@font-face {\n"
        "  font-family: 'Nanum Gothic';\n"
        f"  font-weight: {w};\n"
        "  font-display: swap;\n"
        f"  src: url('fonts/nanum-gothic-{w}.woff2') format('woff2');\n"
        "}"
        for w in (400, 700, 800)
    )
    (out / "styles.css").write_text(
        '@import "tokens/tokens.css";\n\n'
        f"{faces}\n\n"
        "html { color-scheme: light; }\n"
        "body {\n"
        "  background: var(--oop-bg); color: var(--oop-ink);\n"
        "  font-family: var(--oop-font); font-size: var(--oop-fs-body); line-height: 1.7;\n"
        "  -webkit-font-smoothing: antialiased;\n"
        "}\n",
        encoding="utf-8",
    )
    styles = (out / "styles.css").read_text(encoding="utf-8")
    for ref in URL_RE.findall(styles):
        if not (out / ref).is_file():
            fail(f"styles.css: unresolved url({ref})")
    for imp in re.findall(r'@import\s+"([^"]+)"', styles):
        if not (out / imp).is_file():
            fail(f"styles.css: unresolved @import {imp}")

    # README = conventions header + generated file map
    conventions = CONVENTIONS.read_text(encoding="utf-8")
    undefined = set(VAR_RE.findall(conventions)) - defined
    if undefined:
        fail(f"conventions.md names undefined tokens: {sorted(undefined)}")
    file_map = "\n".join(
        f"- `{p.relative_to(out)}`"
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.suffix != ".woff2"
    )
    (out / "README.md").write_text(
        f"{conventions}\n---\n\n## 파일 구성\n\n{file_map}\n"
        "- `fonts/nanum-gothic-{400,700,800}.woff2` (OFL 1.1, `fonts/LICENSE-OFL.txt`)\n",
        encoding="utf-8",
    )

    n_files = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"OK: bundle built at {out} ({n_files} files, {len(card_paths)} cards)")


if __name__ == "__main__":
    main()

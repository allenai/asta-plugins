"""The Asta theme serves its own fonts, so a site contacts no font host."""

import re
from pathlib import Path

THEME = (
    Path(__file__).resolve().parents[1]
    / "plugins/asta-tools/skills/workspace/assets/_extensions/asta-theme"
)


def test_theme_references_no_remote_host():
    for path in THEME.rglob("*"):
        if path.suffix in {".css", ".scss", ".html"}:
            text = path.read_text(encoding="utf-8")
            assert "@import" not in text, path
            assert not re.search(r"url\(\s*[\"']?(https?:)?//", text), path


def test_every_font_face_source_ships_with_the_theme():
    css = (THEME / "asta.css").read_text(encoding="utf-8")
    faces = re.findall(r"@font-face\s*{([^}]*)}", css)
    assert {re.search(r"font-family:\s*([^;]+);", f)[1] for f in faces} == {
        "Manrope",
        '"Roboto Mono"',
    }
    for face in faces:
        for source in re.findall(r"url\(\"([^\"]+)\"\)", face):
            assert (THEME / source).read_bytes()[:4] == b"wOF2", source


def test_each_font_ships_with_its_open_font_license():
    for font in ("Manrope", "RobotoMono"):
        license_text = (THEME / f"fonts/{font}-OFL.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in license_text
        assert "with Reserved Font Name" not in license_text.split("\n\n", 1)[0]

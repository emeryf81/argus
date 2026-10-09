"""Every translatable string must exist in all seven translation files with the same placeholders."""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "custom_components" / "argus" / "panel" / "i18n"
LANGS = ["nl", "fr", "de", "es", "zh", "ko", "id"]


def strings():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "i18n_extract.py"), "/dev/stdout"], capture_output=True, text=True,
                         cwd=ROOT, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"}, timeout=120)
    assert out.returncode == 0, out.stderr[-1500:]
    text = out.stdout
    return json.loads(text[: text.rindex("]") + 1])


def test_all_languages_complete():
    src = strings()
    assert len(src) > 1000
    ph = lambda s: sorted(re.findall(r"\{\w+\}", s))  # noqa: E731
    for lang in LANGS:
        d = json.loads((I18N / f"{lang}.json").read_text("utf-8"))
        missing = [s for s in src if s not in d]
        assert not missing, f"{lang}: {len(missing)} missing, e.g. {missing[:3]}"
        wrong = [s for s in src if ph(s) != ph(d[s])]
        assert not wrong, f"{lang}: placeholder mismatch, e.g. {wrong[:3]}"
        assert not [s for s in d.values() if re.search(r"LEGO|B\.R\.I\.C\.K|Brick", s)], lang

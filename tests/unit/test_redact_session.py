"""The session-export redactor removes credentials/email and leaves everything else unchanged."""

import importlib.util

from weather_risk.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location(
    "redact", PROJECT_ROOT / "scripts" / "redact_session.py"
)
redact_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redact_mod)


def test_redacts_keys_and_email_only():
    fake_aq = "AQ." + "x1Y2z3" * 8  # synthetic, not a real credential
    fake_aiza = "AIza" + "Q" * 35
    text = (f"key {fake_aq} and {fake_aiza}\nGEMINI_API_KEY=your-key-here\n"
            "mail someone@example.org; regex GEMINI_API_KEY=[^\\s]+ stays")  # fmt: skip
    out, counts = redact_mod.redact(text, ["someone@example.org"])
    assert fake_aq not in out and fake_aiza not in out and "someone@example.org" not in out
    assert counts == {"Google API key": 2, "email": 1}
    assert "GEMINI_API_KEY=your-key-here" in out and "GEMINI_API_KEY=[^\\s]+ stays" in out

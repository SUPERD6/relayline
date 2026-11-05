"""Colon-containing legacy model names remain unqualified."""
import pytest

from ccx.review_contract import reviewer


@pytest.mark.parametrize("pin", ["llama3:8b", "org/model:tag", "llama3:8b:custom"])
def test_colon_model_without_known_vendor_is_legacy(pin):
    assert reviewer([("claude", "old", "low")], {"tests_model": pin}) == ("claude", pin, "low")


@pytest.mark.parametrize("pin", ["codex:", "claude:sonnet:low:extra"])
def test_known_vendor_still_validates_pin(pin):
    with pytest.raises(ValueError):
        reviewer([("claude", "old", "low")], {"tests_model": pin})

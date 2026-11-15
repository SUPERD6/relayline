"""Default-off sensitivity is discoverable and strictly validated by ccx config."""
import pytest

from ccx.config import Paths, SETTINGS, load_config, set_setting
from test_adapters import AdapterEnv


def test_sensitivity_default_off(tmp_path):
    assert load_config(Paths(tmp_path))["check"]["sensitivity"] == "off"
    assert "experimental" in SETTINGS["check.sensitivity"][1]


@pytest.mark.parametrize("value", ["off", "warn", "escalate"])
def test_sensitivity_config_roundtrip(tmp_path, value):
    paths = Paths(tmp_path)
    set_setting(paths, "check.sensitivity", value)
    assert load_config(paths)["check"]["sensitivity"] == value


@pytest.mark.parametrize("value", ["on", "true", "WARN", "", "on_fail"])
def test_sensitivity_config_rejects_other_values(tmp_path, value):
    with pytest.raises(ValueError, match="must be off, warn or escalate"):
        set_setting(Paths(tmp_path), "check.sensitivity", value)


class TestSensitivityConfigCLI(AdapterEnv):
    def test_cli_help_set_get_and_invalid_value(self):
        assert "check.sensitivity" in self.ccx("config", "set", "--help").stdout
        assert self.j("config", "get", "check.sensitivity")["check.sensitivity"] == "off"
        self.j("config", "set", "check.sensitivity", "warn")
        assert self.j("config", "get", "check.sensitivity")["check.sensitivity"] == "warn"
        invalid = self.ccx("config", "set", "check.sensitivity", "yes")
        assert invalid.returncode != 0
        assert "must be off, warn or escalate" in invalid.stdout + invalid.stderr

from pathlib import Path

import pytest
import yaml

from monitoreo.engine.rules import RuleSet, RuleSetError
from monitoreo.lists import ListManager
from monitoreo.models import Channel
from monitoreo.service import DEFAULT_CONFIG_DIR

REFS_DOC = (Path(__file__).resolve().parents[1] / "docs" / "marco_normativo.md").read_text(encoding="utf-8")


def test_catalog_loads_and_covers_all_channels(service):
    rs = service.ruleset
    assert len(rs.rules) >= 60
    for channel in Channel:
        assert len(rs.for_channel(channel)) >= 15


def test_every_rule_is_traceable_to_regulation(service):
    for rule in service.ruleset.rules:
        assert rule.regulatory_refs, f"{rule.id} sin referencia normativa"
        for ref in rule.regulatory_refs:
            assert f"`{ref}`" in REFS_DOC, f"{rule.id}: referencia {ref} no documentada en marco_normativo.md"


def test_all_parameters_referenced_by_rules_exist(service):
    import re
    for rule in service.ruleset.rules:
        for name in re.findall(r"\bp\.(\w+)", rule.condition.source):
            assert name in service.params, f"{rule.id} usa parámetro inexistente p.{name}"


def test_invalid_rule_is_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump({"rules": [{
        "id": "X-1", "name": "mala", "channels": ["CASH_IN"], "condition": "__import__('os')"}]}))
    with pytest.raises(RuleSetError):
        RuleSet.load(tmp_path, ListManager())


def test_duplicate_ids_rejected(tmp_path):
    rule = {"id": "X-1", "name": "a", "channels": ["CASH_IN"], "condition": "txn.amount > 1"}
    (tmp_path / "a.yaml").write_text(yaml.safe_dump({"rules": [rule, rule]}))
    with pytest.raises(RuleSetError):
        RuleSet.load(tmp_path, ListManager())


def test_list_normalization():
    lm = ListManager.from_directory(DEFAULT_CONFIG_DIR / "lists")
    assert lm.contains("sanctions", "20999999991")
    assert lm.contains("sanctions", "20-99999999-1")
    assert lm.prefix_match("blocked_bins", "99999912")

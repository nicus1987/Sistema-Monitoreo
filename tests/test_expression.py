import pytest

from monitoreo.engine.expression import CompiledExpression, ExpressionError

FUNCS = {"max": max}
ROOTS = {"txn", "feat", "p"}


def ev(src, ctx):
    return CompiledExpression(src, FUNCS, ROOTS).evaluate(ctx)


def test_basic_logic_and_attributes():
    ctx = {"txn": {"amount": 100, "card": {"bin": "450799"}}, "p": {"lim": 50}}
    assert ev("txn.amount > p.lim and txn.card.bin == '450799'", ctx) is True
    assert ev("txn.amount * 2 >= 200", ctx) is True
    assert ev("max(txn.amount, 500) == 500", ctx) is True
    assert ev("txn.card.bin in ['1', '450799']", ctx) is True


def test_missing_values_are_null_safe():
    ctx = {"txn": {"amount": 100}, "feat": {}}
    assert ev("feat.speed > 900", ctx) is False
    assert ev("txn.device.ip == '1.1.1.1'", ctx) is False
    assert ev("feat.x / 0 > 1", {"feat": {"x": 1}}) is False
    assert ev("not feat.flag", ctx) is True


@pytest.mark.parametrize("src", [
    "__import__('os').system('ls')",
    "txn.__class__",
    "open('/etc/passwd')",
    "(lambda: 1)()",
    "[x for x in txn]",
    "os.path",
    "txn.amount if True else txn['a']",
])
def test_unsafe_expressions_rejected(src):
    with pytest.raises(ExpressionError):
        CompiledExpression(src, FUNCS, ROOTS)

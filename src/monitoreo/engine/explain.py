"""Traduce condiciones de reglas a lenguaje de negocio.

Ejemplo:
    feat.card_count_1h >= p.card_velocity_1h
    -> "Operaciones de la tarjeta (1 h) ≥ card_velocity_1h (10)"
"""

from __future__ import annotations

import ast
import re
from typing import Any

from ..features.catalog import FEATURES, TXN_FIELDS

_OPS = {ast.Gt: ">", ast.GtE: "≥", ast.Lt: "<", ast.LtE: "≤", ast.Eq: "=", ast.NotEq: "≠",
        ast.In: "está en", ast.NotIn: "no está en", ast.Is: "es", ast.IsNot: "no es"}
_BIN = {ast.Add: "+", ast.Sub: "−", ast.Mult: "×", ast.Div: "÷", ast.Mod: "mód", ast.FloorDiv: "÷"}


def fmt_value(v: Any) -> str:
    if v is True:
        return "sí"
    if v is False:
        return "no"
    if v is None:
        return "vacío"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, list):
        return "[" + ", ".join(fmt_value(x) for x in v) + "]"
    if isinstance(v, str):
        return f"'{v}'"
    return str(v)


def _path(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class Explainer:
    def __init__(self, params: dict[str, Any]):
        self.params = params

    def _num(self, node: ast.AST) -> Any:
        """Valor numérico si la expresión sólo depende de constantes y parámetros."""
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        path = _path(node)
        if path and path.startswith("p."):
            v = self.params.get(path[2:])
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            a, b = self._num(node.left), self._num(node.right)
            if a is None or b is None:
                return None
            try:
                return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}.get(type(node.op)) if not isinstance(
                    node.op, (ast.Div, ast.FloorDiv, ast.Mod)) else (a / b if isinstance(node.op, ast.Div) else
                                                                     a // b if isinstance(node.op, ast.FloorDiv) else a % b)
            except ZeroDivisionError:
                return None
        return None

    def term(self, node: ast.AST) -> str:
        path = _path(node)
        if path:
            if path.startswith("feat."):
                name = path[5:]
                return FEATURES[name][0] if name in FEATURES else name
            if path.startswith("p."):
                name = path[2:]
                return f"{name} ({fmt_value(self.params.get(name))})"
            if path.startswith("txn."):
                return TXN_FIELDS.get(path, (path[4:],))[0]
            return {"True": "sí", "False": "no", "None": "vacío"}.get(path, path)
        if isinstance(node, ast.Constant):
            return fmt_value(node.value)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return "[" + ", ".join(self.term(e) for e in node.elts) + "]"
        if isinstance(node, ast.BinOp):
            text = f"{self.term(node.left)} {_BIN.get(type(node.op), '?')} {self.term(node.right)}"
            value = self._num(node)
            return f"{text} (= {fmt_value(value)})" if value is not None else text
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = node.args
            if node.func.id in ("in_list", "prefix_in_list") and len(args) == 2 and isinstance(args[0], ast.Constant):
                how = "está en" if node.func.id == "in_list" else "empieza con un valor de"
                return f"{self.term(args[1])} {how} la lista «{args[0].value}»"
            if node.func.id == "between" and len(args) == 3:
                return f"{self.term(args[0])} entre {self.term(args[1])} y {self.term(args[2])}"
            return f"{node.func.id}(" + ", ".join(self.term(a) for a in args) + ")"
        if isinstance(node, (ast.BoolOp, ast.UnaryOp, ast.Compare)):
            return "(" + self.clause(node) + ")"
        return ast.unparse(node)

    def clause(self, node: ast.AST) -> str:
        if isinstance(node, ast.BoolOp):
            joiner = " y " if isinstance(node.op, ast.And) else " o "
            return joiner.join(self.term(v) if isinstance(v, ast.BoolOp) else self.clause(v) for v in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            inner = node.operand
            if _path(inner):
                return f"{self.term(inner)}: no"
            if isinstance(inner, ast.Call):
                return f"NO se cumple que {self.clause(inner)}"
            return f"NO ({self.clause(inner)})"
        if isinstance(node, ast.Compare):
            parts = [self.term(node.left)]
            for op, comp in zip(node.ops, node.comparators):
                parts += [_OPS.get(type(op), "?"), self.term(comp)]
            return " ".join(parts)
        path = _path(node)
        if path and (path.startswith("feat.") or path.startswith("txn.")):
            return f"{self.term(node)}: sí"
        return self.term(node)

    def explain(self, source: str) -> dict[str, Any]:
        tree = ast.parse(source.strip(), mode="eval").body
        if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And):
            clauses = [f"({self.clause(v)})" if isinstance(v, ast.BoolOp) else self.clause(v) for v in tree.values]
        else:
            clauses = [self.clause(tree)]
        refs = references(source)
        return {
            "clauses": clauses,
            "text": "Se dispara cuando " + (" Y ".join(clauses) if len(clauses) > 1 else clauses[0]) + ".",
            "features": [{"name": f, "label": FEATURES.get(f, (f,))[0],
                          "description": FEATURES.get(f, ("", "Variable no documentada"))[1]} for f in refs["features"]],
            "params": [{"name": n, "value": self.params.get(n)} for n in refs["params"]],
            "lists": refs["lists"],
        }


def references(source: str) -> dict[str, list[str]]:
    def uniq(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))
    return {
        "features": uniq(re.findall(r"\bfeat\.(\w+)", source)),
        "params": uniq(re.findall(r"\bp\.(\w+)", source)),
        "lists": uniq(re.findall(r"in_list\(\s*'(\w+)'", source)),
        "txn": uniq(re.findall(r"\b(txn(?:\.\w+)+)", source)),
    }

"""Evaluador seguro de expresiones para condiciones de reglas.

Las reglas se escriben en YAML con una sintaxis tipo Python, por ejemplo:

    txn.amount_ars > p.high_amount_ars and feat.card_count_1h >= 3

Por seguridad NO se usa `eval`: la expresión se parsea con `ast`, se valida
contra una lista blanca de nodos/funciones al cargar la regla y se evalúa
recorriendo el árbol. Los accesos a atributos inexistentes devuelven `None`
y las comparaciones de orden contra `None` devuelven `False` (null-safe), de
modo que un dato faltante nunca lanza una excepción en el camino crítico.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Callable, Mapping


class ExpressionError(ValueError):
    pass


class Namespace:
    """Envoltorio de dict con acceso por atributo y valor por defecto None."""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any] | None):
        self._data = data or {}

    def get(self, key: str) -> Any:
        value = self._data.get(key) if isinstance(self._data, Mapping) else getattr(self._data, key, None)
        if isinstance(value, Mapping):
            return Namespace(value)
        return value

    def __repr__(self) -> str:  # pragma: no cover
        return f"Namespace({self._data!r})"


_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_ORDER_OPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.BinOp, ast.Compare, ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Name, ast.Attribute, ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Call,
    ast.Load, ast.IfExp, *(_BIN_OPS.keys()), *(_ORDER_OPS.keys()),
)


class CompiledExpression:
    def __init__(self, source: str, functions: Mapping[str, Callable[..., Any]], roots: set[str]):
        self.source = source
        self._functions = functions
        try:
            self._tree = ast.parse(source.strip(), mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"Sintaxis inválida en '{source}': {exc.msg}") from exc
        self._validate(self._tree, roots)

    def _validate(self, tree: ast.AST, roots: set[str]) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                raise ExpressionError(f"Construcción no permitida: {type(node).__name__} en '{self.source}'")
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise ExpressionError(f"Atributo privado no permitido: {node.attr}")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in self._functions:
                    raise ExpressionError(f"Función no permitida en '{self.source}'")
                if node.keywords:
                    raise ExpressionError("No se permiten argumentos por nombre")
            if isinstance(node, ast.Name) and node.id not in roots and node.id not in self._functions \
                    and node.id not in ("True", "False", "None"):
                raise ExpressionError(f"Identificador desconocido '{node.id}' en '{self.source}'")

    def evaluate(self, context: Mapping[str, Any]) -> Any:
        return self._eval(self._tree.body, context)

    def _eval(self, node: ast.AST, ctx: Mapping[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            value = ctx.get(node.id)
            return Namespace(value) if isinstance(value, Mapping) else value
        if isinstance(node, ast.Attribute):
            base = self._eval(node.value, ctx)
            if base is None:
                return None
            if isinstance(base, Namespace):
                return base.get(node.attr)
            return None
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result: Any = True
                for value in node.values:
                    result = self._eval(value, ctx)
                    if not result:
                        return False
                return bool(result)
            for value in node.values:
                if self._eval(value, ctx):
                    return True
            return False
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, ctx)
            if isinstance(node.op, ast.Not):
                return not operand
            return None if operand is None else -operand
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left, ctx), self._eval(node.right, ctx)
            if left is None or right is None:
                return None
            try:
                return _BIN_OPS[type(node.op)](left, right)
            except ZeroDivisionError:
                return None
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, ctx)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, ctx)
                if not self._compare(op, left, right):
                    return False
                left = right
            return True
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [self._eval(e, ctx) for e in node.elts]
        if isinstance(node, ast.IfExp):
            return self._eval(node.body, ctx) if self._eval(node.test, ctx) else self._eval(node.orelse, ctx)
        if isinstance(node, ast.Call):
            fn = self._functions[node.func.id]  # type: ignore[attr-defined]
            return fn(*[self._eval(a, ctx) for a in node.args])
        raise ExpressionError(f"Nodo no soportado: {type(node).__name__}")  # pragma: no cover

    @staticmethod
    def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Is):
            return left is right
        if isinstance(op, ast.IsNot):
            return left is not right
        if isinstance(op, (ast.In, ast.NotIn)):
            if right is None:
                return isinstance(op, ast.NotIn)
            contained = left in right
            return contained if isinstance(op, ast.In) else not contained
        if left is None or right is None:
            return False
        try:
            return _ORDER_OPS[type(op)](left, right)
        except TypeError:
            return False

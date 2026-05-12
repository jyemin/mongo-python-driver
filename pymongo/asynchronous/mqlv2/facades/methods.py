"""Methods facade for MQLv2.

All operations are named methods on a single flat Expr type. No type-level
constraints — mistakes reach the server rather than being caught locally.

Usage::

    from pymongo.asynchronous.mqlv2.facades.methods import (
        from_, lit, doc, field, current, var, let_in, assign,
        sum_, count_, avg_, min_, max_, any_, JoinType,
        asc, desc, bag, arr, doc_kv,
    )

    from_(var("orders")).match(field("status").eq(lit("shipped")))
"""
from __future__ import annotations

from typing import Union

from pymongo.asynchronous.mqlv2 import _ast
from pymongo.asynchronous.mqlv2._serializer import Serializer

# Re-export enums for convenience
JoinType      = _ast.JoinType
SortDirection = _ast.SortDirection
DatePart      = _ast.DatePart


# ---------------------------------------------------------------------------
# Expr: flat facade, all ops as named methods
# ---------------------------------------------------------------------------

class Expr:
    """Single facade expression type. Wraps an AST Expr node."""

    __slots__ = ("_ast",)

    def __init__(self, node: _ast.Expr) -> None:
        self._ast = node

    # --- comparisons ---

    def eq(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.EQ, self._ast, other._ast))

    def ne(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.NE, self._ast, other._ast))

    def is_(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.IS, self._ast, other._ast))

    def lt(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.LT, self._ast, other._ast))

    def le(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.LE, self._ast, other._ast))

    def gt(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.GT, self._ast, other._ast))

    def ge(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.GE, self._ast, other._ast))

    # --- logical ---

    def and_(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.AND, self._ast, other._ast))

    def or_(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.OR, self._ast, other._ast))

    def not_(self) -> "Expr":
        return Expr(_ast.UnaryOp(_ast.UnaryOpType.NOT, self._ast))

    # --- arithmetic ---

    def add(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.ADD, self._ast, other._ast))

    def sub(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.SUB, self._ast, other._ast))

    def mul(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.MUL, self._ast, other._ast))

    def div(self, other: "Expr") -> "Expr":
        return Expr(_ast.BinaryOp(_ast.BinaryOpType.DIV, self._ast, other._ast))

    # --- field access and traversal ---

    def field(self, name: str) -> "Expr":
        return Expr(_ast.FieldAccess(self._ast, name))

    def arrow(self, name: str) -> "Expr":
        return Expr(_ast.ArrowOp(self._ast, name))

    def index(self, idx: "Expr") -> "Expr":
        return Expr(_ast.ArrayIndex(self._ast, idx._ast))

    # --- bag / any ---

    def unwind(self) -> "Expr":
        return Expr(_ast.UnwindExpr(self._ast))


# ---------------------------------------------------------------------------
# PipelineBuilder: stage-chaining over an AST Stage
# ---------------------------------------------------------------------------

class PipelineBuilder:
    """Chainable stage builder. Implements Mqlv2Source for db.mqlv2()."""

    __slots__ = ("_stage",)

    def __init__(self, stage: _ast.Stage) -> None:
        self._stage = stage

    def to_mqlv2(self) -> str:
        return Serializer().serialize(self._stage)

    def match(self, predicate: Expr) -> "PipelineBuilder":
        return PipelineBuilder(_ast.MatchStage(self._stage, predicate._ast))

    def format_(self, expr: Expr) -> "PipelineBuilder":
        return PipelineBuilder(_ast.FormatStage(self._stage, expr._ast))

    def agg(self, expr: Expr) -> "PipelineBuilder":
        return PipelineBuilder(_ast.AggStage(self._stage, expr._ast))

    def project(self, tree: _ast.FieldPathTree) -> "PipelineBuilder":
        return PipelineBuilder(_ast.ProjectStage(self._stage, tree))

    def limit(self, n: int) -> "PipelineBuilder":
        return PipelineBuilder(_ast.LimitStage(self._stage, n))

    def sort(self, *specs: _ast.SortSpec) -> "PipelineBuilder":
        return PipelineBuilder(_ast.SortStage(self._stage, specs))

    def group(
        self,
        group_keys: list[_ast.Assignment],
        agg_keys: list[_ast.Assignment],
    ) -> "PipelineBuilder":
        return PipelineBuilder(_ast.GroupStage(
            self._stage,
            tuple(group_keys),
            tuple(agg_keys),
        ))

    def set_(self, *assignments: _ast.Assignment) -> "PipelineBuilder":
        return PipelineBuilder(_ast.SetStage(self._stage, assignments))

    def unset(self, tree: _ast.FieldPathTree) -> "PipelineBuilder":
        return PipelineBuilder(_ast.UnsetStage(self._stage, tree))

    def distinct(self) -> "PipelineBuilder":
        return PipelineBuilder(_ast.DistinctStage(self._stage))

    def count(self) -> "PipelineBuilder":
        return PipelineBuilder(_ast.CountStage(self._stage))

    def unwind(self, expr: Expr) -> "PipelineBuilder":
        return PipelineBuilder(_ast.UnwindSimpleStage(self._stage, expr._ast))

    def unwind_complex(
        self, var_name: str, source_expr: Expr, body_expr: Expr
    ) -> "PipelineBuilder":
        return PipelineBuilder(_ast.UnwindComplexStage(
            self._stage, var_name, source_expr._ast, body_expr._ast
        ))

    def join(
        self,
        join_type: Union[_ast.JoinType, None],
        var_name: str,
        source: Expr,
        condition: Expr,
    ) -> "PipelineBuilder":
        return PipelineBuilder(_ast.JoinStage(
            self._stage, join_type, var_name, source._ast, condition._ast
        ))


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def from_(*args: Expr, **kwargs: Expr) -> PipelineBuilder:
    """Start a pipeline. Positional: from_(var("c")) → FromStageSimple.
    Keyword: from_(c=var("customers"), o=var("orders")) → FromStageNested."""
    if args and not kwargs:
        if len(args) != 1:
            raise TypeError("from_() accepts exactly one positional argument")
        return PipelineBuilder(_ast.FromStageSimple(args[0]._ast))
    if kwargs and not args:
        return PipelineBuilder(_ast.FromStageNested(
            tuple((k, v._ast) for k, v in kwargs.items())
        ))
    raise TypeError("from_() accepts either one positional argument or keyword arguments, not both")


def lit(v: Union[None, bool, int, float, str]) -> Expr:
    """Scalar literal. bool checked before int (bool subclasses int in Python)."""
    if v is None:
        return Expr(_ast.ValueLit(_ast.VNull()))
    if isinstance(v, bool):
        return Expr(_ast.ValueLit(_ast.VBool(v)))
    if isinstance(v, int):
        return Expr(_ast.ValueLit(_ast.VInt(v)))
    if isinstance(v, float):
        return Expr(_ast.ValueLit(_ast.VDouble(v)))
    if isinstance(v, str):
        return Expr(_ast.ValueLit(_ast.VString(v)))
    raise TypeError(f"Cannot lift {type(v).__name__!r} to MQLv2 literal")


def doc(**kwargs: Expr) -> Expr:
    """Document constructor from keyword args. Keys become VString literals."""
    fields: tuple[tuple[_ast.Expr, _ast.Expr], ...] = tuple(
        (_ast.ValueLit(_ast.VString(k)), v._ast) for k, v in kwargs.items()
    )
    return Expr(_ast.DocumentConstructor(fields))


def doc_kv(mapping: dict[str, Expr]) -> Expr:
    """Document constructor from a dict. Use for keys that aren't valid Python identifiers."""
    fields: tuple[tuple[_ast.Expr, _ast.Expr], ...] = tuple(
        (_ast.ValueLit(_ast.VString(k)), v._ast) for k, v in mapping.items()
    )
    return Expr(_ast.DocumentConstructor(fields))


def field(name: str) -> Expr:
    """Field access from current value: FieldAccess(CurrentValue(), name)."""
    return Expr(_ast.FieldAccess(_ast.CurrentValue(), name))


def current() -> Expr:
    """The current value ($)."""
    return Expr(_ast.CurrentValue())


def var(name: str) -> Expr:
    """Variable reference ($name)."""
    return Expr(_ast.VarRef(name))


def bag(*elements: Expr) -> Expr:
    """Bag constructor: <<e1, e2, ...>>."""
    return Expr(_ast.BagConstructor(tuple(e._ast for e in elements)))


def arr(*elements: Expr) -> Expr:
    """Array constructor: [e1, e2, ...]."""
    return Expr(_ast.ArrayConstructor(tuple(e._ast for e in elements)))


def assign(
    path: Union[str, list[str], tuple[str, ...]],
    value: Expr,
) -> _ast.Assignment:
    """Create an Assignment for group/set. Dot-separated string or list of parts."""
    if isinstance(path, str):
        parts: tuple[str, ...] = tuple(path.split("."))
    else:
        parts = tuple(path)
    return _ast.Assignment(parts, value._ast)


def let_in(bindings: list[tuple[str, Expr]], body: Expr) -> Expr:
    """Let expression: let $k1 = v1, $k2 = v2, ... in body."""
    return Expr(_ast.LetExpr(
        tuple((k, v._ast) for k, v in bindings),
        body._ast,
    ))


def asc(expr: Expr) -> _ast.SortSpec:
    """Ascending sort spec (direction omitted in serialized form)."""
    return _ast.SortSpec(expr._ast, _ast.SortDirection.ASC)


def desc(expr: Expr) -> _ast.SortSpec:
    """Descending sort spec."""
    return _ast.SortSpec(expr._ast, _ast.SortDirection.DESC)


# --- aggregation helpers ---

def count_() -> Expr:
    """count($*) — count elements in the current bag."""
    return Expr(_ast.FunctionCall("count", (_ast.UnwindExpr(_ast.CurrentValue()),)))


def sum_(expr: Expr) -> Expr:
    """sum(expr) — sum a bag of values."""
    return Expr(_ast.FunctionCall("sum", (expr._ast,)))


def avg_(expr: Expr) -> Expr:
    """avg(expr) — average a bag of values."""
    return Expr(_ast.FunctionCall("avg", (expr._ast,)))


def min_(expr: Expr) -> Expr:
    """min(expr) — minimum of a bag of values."""
    return Expr(_ast.FunctionCall("min", (expr._ast,)))


def max_(expr: Expr) -> Expr:
    """max(expr) — maximum of a bag of values."""
    return Expr(_ast.FunctionCall("max", (expr._ast,)))


def any_(sequence: Expr, predicate: Expr) -> Expr:
    """seq any (pred) — true if any element of seq satisfies pred."""
    return Expr(_ast.Any(sequence._ast, predicate._ast))

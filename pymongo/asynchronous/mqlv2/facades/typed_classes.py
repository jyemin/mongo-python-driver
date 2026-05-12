"""Typed-classes facade for MQLv2.

A class hierarchy where operations are gated by subtype: only NumExpr/IntExpr
have add/mul etc.; StrExpr and DateExpr do not. Type errors are caught by
mypy/pyright statically; at runtime AttributeError is the backstop.

Usage::

    from pymongo.asynchronous.mqlv2.facades.typed_classes import (
        from_, int_lit, str_lit, bool_lit, date_lit, num_lit, lit, doc,
        field, int_field, str_field, bool_field, num_field, date_field, doc_field,
        current, int_current, str_current, num_current,
        var, int_var, str_var,
        let_in, assign, sum_, count_, avg_, min_, max_, any_, JoinType,
        asc, desc, bag, arr, doc_kv,
    )

    from_(var("orders")).match(str_field("status").eq(str_lit("shipped")))
"""
from __future__ import annotations

from typing import Generic, TypeVar, Union, overload

from pymongo.asynchronous.mqlv2 import _ast
from pymongo.asynchronous.mqlv2._serializer import Serializer

# Re-export enums for convenience
JoinType      = _ast.JoinType
SortDirection = _ast.SortDirection
DatePart      = _ast.DatePart

E = TypeVar("E", bound="Expr")


# ---------------------------------------------------------------------------
# Expr hierarchy
# ---------------------------------------------------------------------------

class Expr:
    """Facade base. Wraps an AST Expr node."""

    __slots__ = ("_ast",)

    def __init__(self, node: _ast.Expr) -> None:
        self._ast = node

    # --- comparisons (valid on any pair of expressions) ---

    def eq(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.EQ, self._ast, other._ast))

    def ne(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.NE, self._ast, other._ast))

    def is_(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.IS, self._ast, other._ast))

    def lt(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.LT, self._ast, other._ast))

    def le(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.LE, self._ast, other._ast))

    def gt(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.GT, self._ast, other._ast))

    def ge(self, other: "Expr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.GE, self._ast, other._ast))

    # --- pure-cast refiners (no AST change) ---

    def as_num(self) -> "NumExpr":
        return NumExpr(self._ast)

    def as_int(self) -> "IntExpr":
        return IntExpr(self._ast)

    def as_str(self) -> "StrExpr":
        return StrExpr(self._ast)

    def as_bool(self) -> "BoolExpr":
        return BoolExpr(self._ast)

    def as_date(self) -> "DateExpr":
        return DateExpr(self._ast)

    def as_doc(self) -> "DocExpr":
        return DocExpr(self._ast)

    def as_arr(self) -> "ArrExpr[Expr]":
        return ArrExpr(self._ast)

    # --- field access (untyped) ---

    def field(self, name: str) -> "Expr":
        return Expr(_ast.FieldAccess(self._ast, name))

    # --- arrow traversal (permissive — legal on any expression in MQLv2) ---

    def arrow(self, name: str) -> "Expr":
        return Expr(_ast.ArrowOp(self._ast, name))

    def int_arrow(self, name: str) -> "IntExpr":
        return IntExpr(_ast.ArrowOp(self._ast, name))

    def num_arrow(self, name: str) -> "NumExpr":
        return NumExpr(_ast.ArrowOp(self._ast, name))

    def str_arrow(self, name: str) -> "StrExpr":
        return StrExpr(_ast.ArrowOp(self._ast, name))

    def bool_arrow(self, name: str) -> "BoolExpr":
        return BoolExpr(_ast.ArrowOp(self._ast, name))

    def date_arrow(self, name: str) -> "DateExpr":
        return DateExpr(_ast.ArrowOp(self._ast, name))

    def doc_arrow(self, name: str) -> "DocExpr":
        return DocExpr(_ast.ArrowOp(self._ast, name))

    def arr_arrow(self, name: str) -> "ArrExpr[Expr]":
        return ArrExpr(_ast.ArrowOp(self._ast, name))

    # --- array indexing ---

    def index(self, idx: "IntExpr") -> "Expr":
        return Expr(_ast.ArrayIndex(self._ast, idx._ast))


class NumExpr(Expr):
    """Numeric expression. Arithmetic ops return NumExpr."""

    def add(self, other: "NumExpr") -> "NumExpr":
        return NumExpr(_ast.BinaryOp(_ast.BinaryOpType.ADD, self._ast, other._ast))

    def sub(self, other: "NumExpr") -> "NumExpr":
        return NumExpr(_ast.BinaryOp(_ast.BinaryOpType.SUB, self._ast, other._ast))

    def mul(self, other: "NumExpr") -> "NumExpr":
        return NumExpr(_ast.BinaryOp(_ast.BinaryOpType.MUL, self._ast, other._ast))

    def div(self, other: "NumExpr") -> "NumExpr":
        return NumExpr(_ast.BinaryOp(_ast.BinaryOpType.DIV, self._ast, other._ast))


class IntExpr(NumExpr):
    """Integer expression. Int × Int → Int; Int × Num → Num (via @overload)."""

    @overload
    def add(self, other: "IntExpr") -> "IntExpr": ...
    @overload
    def add(self, other: "NumExpr") -> "NumExpr": ...
    def add(self, other: "NumExpr") -> "NumExpr":  # type: ignore[override]
        node = _ast.BinaryOp(_ast.BinaryOpType.ADD, self._ast, other._ast)
        return IntExpr(node) if isinstance(other, IntExpr) else NumExpr(node)

    @overload
    def sub(self, other: "IntExpr") -> "IntExpr": ...
    @overload
    def sub(self, other: "NumExpr") -> "NumExpr": ...
    def sub(self, other: "NumExpr") -> "NumExpr":  # type: ignore[override]
        node = _ast.BinaryOp(_ast.BinaryOpType.SUB, self._ast, other._ast)
        return IntExpr(node) if isinstance(other, IntExpr) else NumExpr(node)

    @overload
    def mul(self, other: "IntExpr") -> "IntExpr": ...
    @overload
    def mul(self, other: "NumExpr") -> "NumExpr": ...
    def mul(self, other: "NumExpr") -> "NumExpr":  # type: ignore[override]
        node = _ast.BinaryOp(_ast.BinaryOpType.MUL, self._ast, other._ast)
        return IntExpr(node) if isinstance(other, IntExpr) else NumExpr(node)

    @overload
    def div(self, other: "IntExpr") -> "IntExpr": ...
    @overload
    def div(self, other: "NumExpr") -> "NumExpr": ...
    def div(self, other: "NumExpr") -> "NumExpr":  # type: ignore[override]
        node = _ast.BinaryOp(_ast.BinaryOpType.DIV, self._ast, other._ast)
        return IntExpr(node) if isinstance(other, IntExpr) else NumExpr(node)


class BoolExpr(Expr):
    """Boolean expression."""

    def and_(self, other: "BoolExpr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.AND, self._ast, other._ast))

    def or_(self, other: "BoolExpr") -> "BoolExpr":
        return BoolExpr(_ast.BinaryOp(_ast.BinaryOpType.OR, self._ast, other._ast))

    def not_(self) -> "BoolExpr":
        return BoolExpr(_ast.UnaryOp(_ast.UnaryOpType.NOT, self._ast))


class StrExpr(Expr):
    """String expression. Numeric operations intentionally absent."""
    pass


class DateExpr(Expr):
    """Date expression. Date-part extraction returns IntExpr."""

    def year(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("year", (self._ast,)))

    def month(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("month", (self._ast,)))

    def day_of_year(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("dayOfYear", (self._ast,)))

    def day_of_month(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("dayOfMonth", (self._ast,)))

    def day_of_week(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("dayOfWeek", (self._ast,)))

    def hour(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("hour", (self._ast,)))

    def minute(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("minute", (self._ast,)))

    def second(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("second", (self._ast,)))

    def millisecond(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("millisecond", (self._ast,)))


class DocExpr(Expr):
    """Document expression. Typed field-access methods recover the leaf type."""

    def int_field(self, name: str) -> IntExpr:
        return IntExpr(_ast.FieldAccess(self._ast, name))

    def num_field(self, name: str) -> NumExpr:
        return NumExpr(_ast.FieldAccess(self._ast, name))

    def str_field(self, name: str) -> StrExpr:
        return StrExpr(_ast.FieldAccess(self._ast, name))

    def bool_field(self, name: str) -> BoolExpr:
        return BoolExpr(_ast.FieldAccess(self._ast, name))

    def date_field(self, name: str) -> DateExpr:
        return DateExpr(_ast.FieldAccess(self._ast, name))

    def doc_field(self, name: str) -> "DocExpr":
        return DocExpr(_ast.FieldAccess(self._ast, name))

    def arr_field(self, name: str) -> "ArrExpr[Expr]":
        return ArrExpr(_ast.FieldAccess(self._ast, name))


class ArrExpr(Expr, Generic[E]):
    """Array/bag expression."""

    def element_at(self, idx: IntExpr) -> Expr:
        return Expr(_ast.ArrayIndex(self._ast, idx._ast))

    def unwind(self) -> Expr:
        return Expr(_ast.UnwindExpr(self._ast))

    def any_(self, predicate: BoolExpr) -> BoolExpr:
        return BoolExpr(_ast.Any(self._ast, predicate._ast))

    def size(self) -> IntExpr:
        return IntExpr(_ast.FunctionCall("size", (self._ast,)))


# ---------------------------------------------------------------------------
# PipelineBuilder
# ---------------------------------------------------------------------------

class PipelineBuilder:
    """Chainable stage builder. Implements Mqlv2Source for db.mqlv2()."""

    __slots__ = ("_stage",)

    def __init__(self, stage: _ast.Stage) -> None:
        self._stage = stage

    def to_mqlv2(self) -> str:
        return Serializer().serialize(self._stage)

    def match(self, predicate: BoolExpr) -> "PipelineBuilder":
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
        condition: BoolExpr,
    ) -> "PipelineBuilder":
        return PipelineBuilder(_ast.JoinStage(
            self._stage, join_type, var_name, source._ast, condition._ast
        ))


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def from_(*args: Expr, **kwargs: Expr) -> PipelineBuilder:
    if args and not kwargs:
        if len(args) != 1:
            raise TypeError("from_() accepts exactly one positional argument")
        return PipelineBuilder(_ast.FromStageSimple(args[0]._ast))
    if kwargs and not args:
        return PipelineBuilder(_ast.FromStageNested(
            tuple((k, v._ast) for k, v in kwargs.items())
        ))
    raise TypeError("from_() accepts either one positional argument or keyword arguments, not both")


def int_lit(n: int) -> IntExpr:
    return IntExpr(_ast.ValueLit(_ast.VInt(n)))


def num_lit(f: float) -> NumExpr:
    return NumExpr(_ast.ValueLit(_ast.VDouble(f)))


def str_lit(s: str) -> StrExpr:
    return StrExpr(_ast.ValueLit(_ast.VString(s)))


def bool_lit(b: bool) -> BoolExpr:
    return BoolExpr(_ast.ValueLit(_ast.VBool(b)))


def date_lit(millis: int) -> DateExpr:
    return DateExpr(_ast.ValueLit(_ast.VDate(millis)))


def lit(v: Union[None, bool, int, float, str]) -> Expr:
    """Untyped literal — use the typed variants for static type checking."""
    if v is None:
        return Expr(_ast.ValueLit(_ast.VNull()))
    if isinstance(v, bool):
        return BoolExpr(_ast.ValueLit(_ast.VBool(v)))
    if isinstance(v, int):
        return IntExpr(_ast.ValueLit(_ast.VInt(v)))
    if isinstance(v, float):
        return NumExpr(_ast.ValueLit(_ast.VDouble(v)))
    if isinstance(v, str):
        return StrExpr(_ast.ValueLit(_ast.VString(v)))
    raise TypeError(f"Cannot lift {type(v).__name__!r} to MQLv2 literal")


def doc(**kwargs: Expr) -> Expr:
    fields: tuple[tuple[_ast.Expr, _ast.Expr], ...] = tuple(
        (_ast.ValueLit(_ast.VString(k)), v._ast) for k, v in kwargs.items()
    )
    return Expr(_ast.DocumentConstructor(fields))


def doc_kv(mapping: dict[str, Expr]) -> Expr:
    fields: tuple[tuple[_ast.Expr, _ast.Expr], ...] = tuple(
        (_ast.ValueLit(_ast.VString(k)), v._ast) for k, v in mapping.items()
    )
    return Expr(_ast.DocumentConstructor(fields))


# --- module-level field access factories ---

def field(name: str) -> Expr:
    return Expr(_ast.FieldAccess(_ast.CurrentValue(), name))

def int_field(name: str) -> IntExpr:
    return IntExpr(_ast.FieldAccess(_ast.CurrentValue(), name))

def num_field(name: str) -> NumExpr:
    return NumExpr(_ast.FieldAccess(_ast.CurrentValue(), name))

def str_field(name: str) -> StrExpr:
    return StrExpr(_ast.FieldAccess(_ast.CurrentValue(), name))

def bool_field(name: str) -> BoolExpr:
    return BoolExpr(_ast.FieldAccess(_ast.CurrentValue(), name))

def date_field(name: str) -> DateExpr:
    return DateExpr(_ast.FieldAccess(_ast.CurrentValue(), name))

def doc_field(name: str) -> DocExpr:
    return DocExpr(_ast.FieldAccess(_ast.CurrentValue(), name))

def arr_field(name: str) -> "ArrExpr[Expr]":
    return ArrExpr(_ast.FieldAccess(_ast.CurrentValue(), name))


# --- current value factories ---

def current() -> Expr:
    return Expr(_ast.CurrentValue())

def int_current() -> IntExpr:
    return IntExpr(_ast.CurrentValue())

def num_current() -> NumExpr:
    return NumExpr(_ast.CurrentValue())

def str_current() -> StrExpr:
    return StrExpr(_ast.CurrentValue())


# --- var factories ---

def var(name: str) -> Expr:
    return Expr(_ast.VarRef(name))

def int_var(name: str) -> IntExpr:
    return IntExpr(_ast.VarRef(name))

def str_var(name: str) -> StrExpr:
    return StrExpr(_ast.VarRef(name))


# --- constructors ---

def bag(*elements: Expr) -> Expr:
    return Expr(_ast.BagConstructor(tuple(e._ast for e in elements)))

def arr(*elements: Expr) -> Expr:
    return Expr(_ast.ArrayConstructor(tuple(e._ast for e in elements)))


# --- helpers ---

def assign(
    path: Union[str, list[str], tuple[str, ...]],
    value: Expr,
) -> _ast.Assignment:
    if isinstance(path, str):
        parts: tuple[str, ...] = tuple(path.split("."))
    else:
        parts = tuple(path)
    return _ast.Assignment(parts, value._ast)


def let_in(bindings: list[tuple[str, Expr]], body: Expr) -> Expr:
    return Expr(_ast.LetExpr(
        tuple((k, v._ast) for k, v in bindings),
        body._ast,
    ))


def asc(expr: Expr) -> _ast.SortSpec:
    return _ast.SortSpec(expr._ast, _ast.SortDirection.ASC)

def desc(expr: Expr) -> _ast.SortSpec:
    return _ast.SortSpec(expr._ast, _ast.SortDirection.DESC)


# --- aggregation ---

def count_() -> IntExpr:
    """count($*) — count elements in the current bag."""
    return IntExpr(_ast.FunctionCall("count", (_ast.UnwindExpr(_ast.CurrentValue()),)))

def sum_(expr: NumExpr) -> NumExpr:
    return NumExpr(_ast.FunctionCall("sum", (expr._ast,)))

def avg_(expr: NumExpr) -> NumExpr:
    return NumExpr(_ast.FunctionCall("avg", (expr._ast,)))

def min_(expr: NumExpr) -> NumExpr:
    return NumExpr(_ast.FunctionCall("min", (expr._ast,)))

def max_(expr: NumExpr) -> NumExpr:
    return NumExpr(_ast.FunctionCall("max", (expr._ast,)))

def any_(sequence: "ArrExpr[Expr]", predicate: BoolExpr) -> BoolExpr:
    return BoolExpr(_ast.Any(sequence._ast, predicate._ast))

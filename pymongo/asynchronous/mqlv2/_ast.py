"""MQLv2 AST — frozen dataclasses (Python 3.10+).

All base classes seal themselves against external subclassing via __init_subclass__.
Use tuple, not list, for sequence fields so frozen dataclasses remain hashable.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BinaryOpType(enum.Enum):
    EQ  = "=="
    NE  = "!="
    IS  = "is"
    LT  = "<"
    LE  = "<="
    GT  = ">"
    GE  = ">="
    AND = "and"
    OR  = "or"
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"


class UnaryOpType(enum.Enum):
    NOT = "not"


class SortDirection(enum.Enum):
    ASC  = "asc"
    DESC = "desc"


class JoinType(enum.Enum):
    INNER       = "inner"
    LEFT_OUTER  = "leftOuter"
    RIGHT_OUTER = "rightOuter"
    FULL_OUTER  = "fullOuter"


class DatePart(enum.Enum):
    YEAR         = "year"
    MONTH        = "month"
    DAY_OF_YEAR  = "dayOfYear"
    DAY_OF_MONTH = "dayOfMonth"
    DAY_OF_WEEK  = "dayOfWeek"
    HOUR         = "hour"
    MINUTE       = "minute"
    SECOND       = "second"
    MILLISECOND  = "millisecond"


# ---------------------------------------------------------------------------
# Value hierarchy (sealed)
# ---------------------------------------------------------------------------

class Value:
    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(f"Cannot subclass Value outside of {__name__!r}")


@dataclass(frozen=True)
class VNull(Value):
    pass


@dataclass(frozen=True)
class VMissing(Value):
    pass


@dataclass(frozen=True)
class VUndefined(Value):
    pass


@dataclass(frozen=True)
class VBool(Value):
    value: bool


@dataclass(frozen=True)
class VInt(Value):
    value: int


@dataclass(frozen=True)
class VDouble(Value):
    value: float


@dataclass(frozen=True)
class VString(Value):
    value: str


@dataclass(frozen=True)
class VDate(Value):
    millis_since_epoch: int


@dataclass(frozen=True)
class VDocument(Value):
    fields: tuple[tuple[str, Value], ...]


@dataclass(frozen=True)
class VSequence(Value):
    elements: tuple[Value, ...]
    ordered: bool  # True = array []; False = bag <<>>


# ---------------------------------------------------------------------------
# FieldPathTree hierarchy (sealed) — used by project / unset
# ---------------------------------------------------------------------------

class FieldPathTree:
    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(f"Cannot subclass FieldPathTree outside of {__name__!r}")


@dataclass(frozen=True)
class Interior(FieldPathTree):
    children: tuple[tuple[str, FieldPathTree], ...]


@dataclass(frozen=True)
class Leaf(FieldPathTree):
    pass


# ---------------------------------------------------------------------------
# Expr hierarchy (sealed)
# ---------------------------------------------------------------------------

class Expr:
    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(f"Cannot subclass Expr outside of {__name__!r}")


@dataclass(frozen=True)
class ValueLit(Expr):
    value: Value


@dataclass(frozen=True)
class CurrentValue(Expr):
    pass


@dataclass(frozen=True)
class VarRef(Expr):
    name: str


@dataclass(frozen=True)
class BinaryOp(Expr):
    op: BinaryOpType
    left: Expr
    right: Expr


@dataclass(frozen=True)
class UnaryOp(Expr):
    op: UnaryOpType
    arg: Expr


@dataclass(frozen=True)
class FieldAccess(Expr):
    target: Expr
    field: str


@dataclass(frozen=True)
class ArrowOp(Expr):
    target: Expr
    field: str


@dataclass(frozen=True)
class ArrayIndex(Expr):
    array: Expr
    index: Expr


@dataclass(frozen=True)
class UnwindExpr(Expr):
    arg: Expr


@dataclass(frozen=True)
class BagConstructor(Expr):
    elements: tuple[Expr, ...]


@dataclass(frozen=True)
class ArrayConstructor(Expr):
    elements: tuple[Expr, ...]


@dataclass(frozen=True)
class DocumentConstructor(Expr):
    fields: tuple[tuple[Expr, Expr], ...]


@dataclass(frozen=True)
class Any(Expr):
    sequence: Expr
    predicate: Expr


@dataclass(frozen=True)
class FunctionCall(Expr):
    name: str
    args: tuple[Expr, ...]


@dataclass(frozen=True)
class SubPipelineExpr(Expr):
    pipeline: Stage  # forward ref, fine with from __future__ import annotations


@dataclass(frozen=True)
class LetExpr(Expr):
    bindings: tuple[tuple[str, Expr], ...]
    body: Expr


# ---------------------------------------------------------------------------
# Stage hierarchy (sealed)
# ---------------------------------------------------------------------------

class Stage:
    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(f"Cannot subclass Stage outside of {__name__!r}")


@dataclass(frozen=True)
class FromStageSimple(Stage):
    source: Expr


@dataclass(frozen=True)
class FromStageNested(Stage):
    sources: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class MatchStage(Stage):
    source: Stage
    predicate: Expr


@dataclass(frozen=True)
class FormatStage(Stage):
    source: Stage
    expr: Expr


@dataclass(frozen=True)
class AggStage(Stage):
    source: Stage
    expr: Expr


@dataclass(frozen=True)
class ProjectStage(Stage):
    source: Stage
    tree: FieldPathTree


@dataclass(frozen=True)
class LimitStage(Stage):
    source: Stage
    count: int


@dataclass(frozen=True)
class SortStage(Stage):
    source: Stage
    specs: tuple[SortSpec, ...]


@dataclass(frozen=True)
class GroupStage(Stage):
    source: Stage
    group_keys: tuple[Assignment, ...]
    agg_keys: tuple[Assignment, ...]


@dataclass(frozen=True)
class SetStage(Stage):
    source: Stage
    assignments: tuple[Assignment, ...]


@dataclass(frozen=True)
class UnsetStage(Stage):
    source: Stage
    tree: FieldPathTree


@dataclass(frozen=True)
class DistinctStage(Stage):
    source: Stage


@dataclass(frozen=True)
class CountStage(Stage):
    source: Stage


@dataclass(frozen=True)
class UnwindSimpleStage(Stage):
    source: Stage
    expr: Expr


@dataclass(frozen=True)
class UnwindComplexStage(Stage):
    source: Stage
    var_name: str
    source_expr: Expr
    body_expr: Expr


@dataclass(frozen=True)
class JoinStage(Stage):
    source: Stage
    join_type: JoinType | None
    var_name: str
    right: Expr
    condition: Expr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SortSpec:
    expr: Expr
    direction: SortDirection


@dataclass(frozen=True)
class Assignment:
    path: tuple[str, ...]
    value: Expr

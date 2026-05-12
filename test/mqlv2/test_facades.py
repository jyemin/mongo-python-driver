"""Facade tests — mirrors UntypedFacadeTest.java + SubtypedFacadeTest.java.

Each test:
  1. Builds a pipeline via the facade.
  2. Asserts the underlying AST matches the bare-AST form (structural equality).
  3. Executes against a live server and asserts result equality.

Requires a mongod with the experimental mqlv2 command on mongodb://localhost:27017.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pymongo.asynchronous.mqlv2 import _ast
import pymongo.asynchronous.mqlv2.facades.methods as M
import pymongo.asynchronous.mqlv2.facades.typed_classes as TC

pytestmark = [pytest.mark.default_async, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers shared by both facade tests
# ---------------------------------------------------------------------------

async def _run(db, pipeline) -> list[dict]:
    cursor = await db.mqlv2(pipeline)
    docs: list[dict] = []
    async for doc in cursor:
        docs.append(doc)
    return docs


def _as_set(docs: list[dict]) -> frozenset:
    return frozenset(json.dumps(d, sort_keys=True) for d in docs)


def _bset(*dicts: dict) -> frozenset:
    return frozenset(json.dumps(d, sort_keys=True) for d in dicts)


def _assert_same_ast(facade_stage: _ast.Stage, bare_stage: _ast.Stage) -> None:
    assert bare_stage == facade_stage, "facade AST diverges from bare AST"


# --- bare AST helpers (b-prefix) ---

def _b_lit_i(n: int) -> _ast.Expr:
    return _ast.ValueLit(_ast.VInt(n))


def _b_lit_s(s: str) -> _ast.Expr:
    return _ast.ValueLit(_ast.VString(s))


def _b_field(name: str) -> _ast.Expr:
    return _ast.FieldAccess(_ast.CurrentValue(), name)


def _b_eq(l: _ast.Expr, r: _ast.Expr) -> _ast.Expr:
    return _ast.BinaryOp(_ast.BinaryOpType.EQ, l, r)


def _b_add(l: _ast.Expr, r: _ast.Expr) -> _ast.Expr:
    return _ast.BinaryOp(_ast.BinaryOpType.ADD, l, r)


def _b_mul(l: _ast.Expr, r: _ast.Expr) -> _ast.Expr:
    return _ast.BinaryOp(_ast.BinaryOpType.MUL, l, r)


def _b_fn(name: str, *args: _ast.Expr) -> _ast.Expr:
    return _ast.FunctionCall(name, args)


def _b_bag(*es: _ast.Expr) -> _ast.Expr:
    return _ast.BagConstructor(es)


def _b_doc(**kv: _ast.Expr) -> _ast.Expr:
    return _ast.DocumentConstructor(tuple(
        (_ast.ValueLit(_ast.VString(k)), v) for k, v in kv.items()
    ))


# ===========================================================================
# Methods (untyped) facade — mirrors UntypedFacadeTest.java
# ===========================================================================

class TestMethodsFacade:

    async def test_match_simple(self, db):
        facade = M.from_(M.bag(M.lit(1), M.lit(2), M.lit(3))).match(
            M.current().eq(M.lit(2))
        )
        bare = _ast.MatchStage(
            _ast.FromStageSimple(_b_bag(_b_lit_i(1), _b_lit_i(2), _b_lit_i(3))),
            _b_eq(_ast.CurrentValue(), _b_lit_i(2)),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 2}]

    async def test_format_with_doc_and_mul(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.lit(1)), M.doc(a=M.lit(2))
        )).format_(M.doc(doubled=M.field("a").mul(M.lit(2))))
        bare = _ast.FormatStage(
            _ast.FromStageSimple(_b_bag(_b_doc(a=_b_lit_i(1)), _b_doc(a=_b_lit_i(2)))),
            _b_doc(doubled=_b_mul(_b_field("a"), _b_lit_i(2))),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset({"doubled": 2}, {"doubled": 4})

    async def test_sort_desc_then_asc(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.lit(3), b=M.lit(2)),
            M.doc(a=M.lit(1), b=M.lit(7)),
            M.doc(a=M.lit(5), b=M.lit(2)),
            M.doc(a=M.lit(5), b=M.lit(1)),
        )).sort(M.desc(M.field("a")), M.asc(M.field("b")))
        bare = _ast.SortStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_b_lit_i(3), b=_b_lit_i(2)),
                _b_doc(a=_b_lit_i(1), b=_b_lit_i(7)),
                _b_doc(a=_b_lit_i(5), b=_b_lit_i(2)),
                _b_doc(a=_b_lit_i(5), b=_b_lit_i(1)),
            )),
            (
                _ast.SortSpec(_b_field("a"), _ast.SortDirection.DESC),
                _ast.SortSpec(_b_field("b"), _ast.SortDirection.ASC),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [
            {"a": 5, "b": 1},
            {"a": 5, "b": 2},
            {"a": 3, "b": 2},
            {"a": 1, "b": 7},
        ]

    async def test_limit(self, db):
        facade = M.from_(M.bag(
            M.lit(3), M.lit(1), M.lit(4), M.lit(1),
            M.lit(5), M.lit(9), M.lit(2), M.lit(6),
        )).sort(M.asc(M.current())).limit(3)
        bare = _ast.LimitStage(
            _ast.SortStage(
                _ast.FromStageSimple(_b_bag(
                    _b_lit_i(3), _b_lit_i(1), _b_lit_i(4), _b_lit_i(1),
                    _b_lit_i(5), _b_lit_i(9), _b_lit_i(2), _b_lit_i(6),
                )),
                (_ast.SortSpec(_ast.CurrentValue(), _ast.SortDirection.ASC),),
            ),
            3,
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 1}, {"value": 1}, {"value": 2}]

    async def test_project_branching(self, db):
        facade = M.from_(M.bag(M.doc(
            a=M.doc(x=M.lit(1), y=M.lit(2), z=M.lit(3)),
            b=M.lit(9),
        ))).project("a.x", "a.z", "b")
        bare = _ast.ProjectStage(
            _ast.FromStageSimple(_b_bag(_b_doc(
                a=_b_doc(x=_b_lit_i(1), y=_b_lit_i(2), z=_b_lit_i(3)),
                b=_b_lit_i(9),
            ))),
            _ast.Interior((
                ("a", _ast.Interior((
                    ("x", _ast.Leaf()),
                    ("z", _ast.Leaf()),
                ))),
                ("b", _ast.Leaf()),
            )),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": {"x": 1, "z": 3}, "b": 9}]

    async def test_set_with_arithmetic(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.lit(1)), M.doc(a=M.lit(2))
        )).set_(M.assign("z.add1", M.field("a").add(M.lit(1))))
        bare = _ast.SetStage(
            _ast.FromStageSimple(_b_bag(_b_doc(a=_b_lit_i(1)), _b_doc(a=_b_lit_i(2)))),
            (_ast.Assignment(("z", "add1"), _b_add(_b_field("a"), _b_lit_i(1))),),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"a": 1, "z": {"add1": 2}},
            {"a": 2, "z": {"add1": 3}},
        )

    async def test_unset(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.lit(1), b=M.lit(2))
        )).unset("b")
        bare = _ast.UnsetStage(
            _ast.FromStageSimple(_b_bag(_b_doc(a=_b_lit_i(1), b=_b_lit_i(2)))),
            _ast.Interior((("b", _ast.Leaf()),)),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": 1}]

    async def test_distinct_and_count(self, db):
        facade_distinct = M.from_(M.bag(
            M.lit(1), M.lit(1), M.lit(2), M.lit(3)
        )).distinct()
        bare_distinct = _ast.DistinctStage(
            _ast.FromStageSimple(_b_bag(_b_lit_i(1), _b_lit_i(1), _b_lit_i(2), _b_lit_i(3)))
        )
        _assert_same_ast(facade_distinct.stage, bare_distinct)
        assert _as_set(await _run(db, facade_distinct)) == _bset(
            {"value": 1}, {"value": 2}, {"value": 3}
        )

        facade_count = M.from_(M.bag(
            M.lit(1), M.lit(2), M.lit(3), M.lit(4), M.lit(5)
        )).count()
        bare_count = _ast.CountStage(
            _ast.FromStageSimple(_b_bag(
                _b_lit_i(1), _b_lit_i(2), _b_lit_i(3), _b_lit_i(4), _b_lit_i(5)
            ))
        )
        _assert_same_ast(facade_count.stage, bare_count)
        assert await _run(db, facade_count) == [{"value": 5}]

    async def test_unwind_simple(self, db):
        facade = M.from_(M.bag(M.arr(M.lit(1), M.lit(2), M.lit(3)))).unwind(M.current())
        bare = _ast.UnwindSimpleStage(
            _ast.FromStageSimple(_ast.BagConstructor((
                _ast.ArrayConstructor((_b_lit_i(1), _b_lit_i(2), _b_lit_i(3))),
            ))),
            _ast.CurrentValue(),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"value": 1}, {"value": 2}, {"value": 3}
        )

    async def test_any_expression_and_arrow(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.arr(M.doc(b=M.lit(1)), M.doc(b=M.lit(2)))),
            M.doc(a=M.arr(M.doc(b=M.lit(3)))),
        )).match(M.field("a").arrow("b").any_(M.current().eq(M.lit(2))))
        bare = _ast.MatchStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_ast.ArrayConstructor((
                    _b_doc(b=_b_lit_i(1)), _b_doc(b=_b_lit_i(2)),
                ))),
                _b_doc(a=_ast.ArrayConstructor((_b_doc(b=_b_lit_i(3)),))),
            )),
            _ast.Any(
                _ast.ArrowOp(_b_field("a"), "b"),
                _b_eq(_ast.CurrentValue(), _b_lit_i(2)),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": [{"b": 1}, {"b": 2}]}]

    async def test_group_with_sum_arrow(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.lit(1), b=M.lit(2)),
            M.doc(a=M.lit(1), b=M.lit(3)),
            M.doc(a=M.lit(2), b=M.lit(4)),
        )).group(
            [M.assign("k", M.field("a"))],
            [M.assign("s", M.sum_(M.current().arrow("b")))],
        )
        bare = _ast.GroupStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_b_lit_i(1), b=_b_lit_i(2)),
                _b_doc(a=_b_lit_i(1), b=_b_lit_i(3)),
                _b_doc(a=_b_lit_i(2), b=_b_lit_i(4)),
            )),
            (_ast.Assignment(("k",), _b_field("a")),),
            (_ast.Assignment(("s",), _ast.FunctionCall("sum", (
                _ast.ArrowOp(_ast.CurrentValue(), "b"),
            ))),),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset({"k": 1, "s": 5}, {"k": 2, "s": 4})

    async def test_let_expr(self, db):
        facade = M.from_(M.let_in([("x", M.lit(2))], M.var("x").add(M.lit(3))))
        bare = _ast.FromStageSimple(
            _ast.LetExpr(
                (("x", _b_lit_i(2)),),
                _ast.BinaryOp(_ast.BinaryOpType.ADD, _ast.VarRef("x"), _b_lit_i(3)),
            )
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 5}]

    async def test_top_level_agg_via_function_call(self, db):
        facade = M.from_(M.sum_(M.bag(M.lit(1), M.lit(2), M.lit(3), M.lit(4))))
        bare = _ast.FromStageSimple(
            _ast.FunctionCall("sum", (_b_bag(_b_lit_i(1), _b_lit_i(2), _b_lit_i(3), _b_lit_i(4)),))
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 10}]

    async def test_not_and_is_nullish(self, db):
        facade = M.from_(M.bag(
            M.doc(a=M.lit(1)),
            M.doc(a=M.null()),
            M.doc(a=M.missing()),
        )).match(M.is_nullish(M.field("a")).not_())
        bare = _ast.MatchStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_b_lit_i(1)),
                _b_doc(a=_ast.ValueLit(_ast.VNull())),
                _b_doc(a=_ast.ValueLit(_ast.VMissing())),
            )),
            _ast.UnaryOp(
                _ast.UnaryOpType.NOT,
                _ast.FunctionCall("isNullish", (_b_field("a"),)),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": 1}]

    async def test_cross_product_from_nested(self, db):
        facade = M.from_(
            s=M.bag(M.lit(1), M.lit(2), M.lit(3)),
            s2=M.bag(M.lit(10), M.lit(20)),
        )
        bare = _ast.FromStageNested((
            ("s",  _b_bag(_b_lit_i(1), _b_lit_i(2), _b_lit_i(3))),
            ("s2", _b_bag(_b_lit_i(10), _b_lit_i(20))),
        ))
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"s": 1, "s2": 10}, {"s": 1, "s2": 20},
            {"s": 2, "s2": 10}, {"s": 2, "s2": 20},
            {"s": 3, "s2": 10}, {"s": 3, "s2": 20},
        )

    async def test_join_default_inner(self, db):
        facade = M.from_(c=M.bag(
            M.doc(id=M.lit(1), items=M.lit(10)),
            M.doc(id=M.lit(2), items=M.lit(5)),
        )).join(
            None, "o",
            M.bag(
                M.doc(id=M.lit(1), items=M.lit(10)),
                M.doc(id=M.lit(2), items=M.lit(5)),
            ),
            M.field("c").field("id").eq(M.field("o").field("id")),
        )
        c_bag = _b_bag(
            _b_doc(id=_b_lit_i(1), items=_b_lit_i(10)),
            _b_doc(id=_b_lit_i(2), items=_b_lit_i(5)),
        )
        o_bag = _b_bag(
            _b_doc(id=_b_lit_i(1), items=_b_lit_i(10)),
            _b_doc(id=_b_lit_i(2), items=_b_lit_i(5)),
        )
        bare = _ast.JoinStage(
            _ast.FromStageNested((("c", c_bag),)),
            None, "o", o_bag,
            _b_eq(
                _ast.FieldAccess(_b_field("c"), "id"),
                _ast.FieldAccess(_b_field("o"), "id"),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"c": {"id": 1, "items": 10}, "o": {"id": 1, "items": 10}},
            {"c": {"id": 2, "items": 5},  "o": {"id": 2, "items": 5}},
        )

    async def test_join_left_outer(self, db):
        facade = M.from_(c=M.bag(
            M.doc(id=M.lit(1)), M.doc(id=M.lit(2)), M.doc(id=M.lit(3)),
        )).join(
            M.JoinType.LEFT_OUTER, "o",
            M.bag(
                M.doc(id=M.lit(1), v=M.lit("x")),
                M.doc(id=M.lit(3), v=M.lit("z")),
            ),
            M.field("c").field("id").eq(M.field("o").field("id")),
        )
        bare = _ast.JoinStage(
            _ast.FromStageNested((("c", _b_bag(
                _b_doc(id=_b_lit_i(1)), _b_doc(id=_b_lit_i(2)), _b_doc(id=_b_lit_i(3)),
            )),)),
            _ast.JoinType.LEFT_OUTER, "o",
            _b_bag(
                _b_doc(id=_b_lit_i(1), v=_b_lit_s("x")),
                _b_doc(id=_b_lit_i(3), v=_b_lit_s("z")),
            ),
            _b_eq(
                _ast.FieldAccess(_b_field("c"), "id"),
                _ast.FieldAccess(_b_field("o"), "id"),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"c": {"id": 1}, "o": {"id": 1, "v": "x"}},
            {"c": {"id": 2}},
            {"c": {"id": 3}, "o": {"id": 3, "v": "z"}},
        )

    async def test_date_extractors(self, db):
        # 2024-01-15T10:30:45.123Z — Monday, dayOfWeek=2 (Sun=1 convention)
        dt_millis = int(datetime(2024, 1, 15, 10, 30, 45, 123000, tzinfo=timezone.utc).timestamp() * 1000)

        facade = M.from_(M.bag(M.doc(dt=M.date_lit(dt_millis)))).format_(M.doc(
            y=M.year(M.field("dt")),
            m=M.month(M.field("dt")),
            dm=M.day_of_month(M.field("dt")),
            dy=M.day_of_year(M.field("dt")),
            dw=M.day_of_week(M.field("dt")),
            h=M.hour(M.field("dt")),
            mn=M.minute(M.field("dt")),
            s=M.second(M.field("dt")),
            ms=M.millisecond(M.field("dt")),
        ))
        b_dt = _ast.ValueLit(_ast.VDate(dt_millis))
        bare = _ast.FormatStage(
            _ast.FromStageSimple(_b_bag(_b_doc(dt=b_dt))),
            _b_doc(
                y=_b_fn("year",        _b_field("dt")),
                m=_b_fn("month",       _b_field("dt")),
                dm=_b_fn("dayOfMonth", _b_field("dt")),
                dy=_b_fn("dayOfYear",  _b_field("dt")),
                dw=_b_fn("dayOfWeek",  _b_field("dt")),
                h=_b_fn("hour",        _b_field("dt")),
                mn=_b_fn("minute",     _b_field("dt")),
                s=_b_fn("second",      _b_field("dt")),
                ms=_b_fn("millisecond", _b_field("dt")),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [
            {"y": 2024, "m": 1, "dm": 15, "dy": 15, "dw": 2,
             "h": 10, "mn": 30, "s": 45, "ms": 123}
        ]

    async def test_date_comparisons(self, db):
        jan1  = int(datetime(2024,  1,  1,  0,  0,  0, tzinfo=timezone.utc).timestamp() * 1000)
        dec31 = int(datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        mid   = int(datetime(2024,  6, 15, 10, 30,  0, tzinfo=timezone.utc).timestamp() * 1000)

        facade_lt = M.from_(M.date_lit(jan1).lt(M.date_lit(dec31)))
        bare_lt = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.LT,
                _ast.ValueLit(_ast.VDate(jan1)),
                _ast.ValueLit(_ast.VDate(dec31)))
        )
        _assert_same_ast(facade_lt.stage, bare_lt)
        assert await _run(db, facade_lt) == [{"value": True}]

        facade_eq_true = M.from_(M.date_lit(mid).eq(M.date_lit(mid)))
        bare_eq_true = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.EQ,
                _ast.ValueLit(_ast.VDate(mid)),
                _ast.ValueLit(_ast.VDate(mid)))
        )
        _assert_same_ast(facade_eq_true.stage, bare_eq_true)
        assert await _run(db, facade_eq_true) == [{"value": True}]

        facade_eq_false = M.from_(M.date_lit(jan1).eq(M.date_lit(dec31)))
        bare_eq_false = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.EQ,
                _ast.ValueLit(_ast.VDate(jan1)),
                _ast.ValueLit(_ast.VDate(dec31)))
        )
        _assert_same_ast(facade_eq_false.stage, bare_eq_false)
        assert await _run(db, facade_eq_false) == [{"value": False}]

        facade_is = M.from_(M.date_lit(mid).is_(M.date_lit(mid)))
        bare_is = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.IS,
                _ast.ValueLit(_ast.VDate(mid)),
                _ast.ValueLit(_ast.VDate(mid)))
        )
        _assert_same_ast(facade_is.stage, bare_is)
        assert await _run(db, facade_is) == [{"value": True}]


# ===========================================================================
# Typed-classes (subtyped) facade — mirrors SubtypedFacadeTest.java
# ===========================================================================

class TestTypedClassesFacade:

    async def test_match_simple(self, db):
        facade = TC.from_(TC.bag(TC.int_lit(1), TC.int_lit(2), TC.int_lit(3))).match(
            TC.int_current().eq(TC.int_lit(2))
        )
        bare = _ast.MatchStage(
            _ast.FromStageSimple(_b_bag(_b_lit_i(1), _b_lit_i(2), _b_lit_i(3))),
            _b_eq(_ast.CurrentValue(), _b_lit_i(2)),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 2}]

    async def test_format_with_doc_and_mul(self, db):
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.int_lit(1)), TC.doc(a=TC.int_lit(2))
        )).format_(TC.doc(doubled=TC.int_field("a").mul(TC.int_lit(2))))
        bare = _ast.FormatStage(
            _ast.FromStageSimple(_b_bag(_b_doc(a=_b_lit_i(1)), _b_doc(a=_b_lit_i(2)))),
            _b_doc(doubled=_b_mul(_b_field("a"), _b_lit_i(2))),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset({"doubled": 2}, {"doubled": 4})

    async def test_sort_desc_then_asc(self, db):
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.int_lit(3), b=TC.int_lit(2)),
            TC.doc(a=TC.int_lit(1), b=TC.int_lit(7)),
            TC.doc(a=TC.int_lit(5), b=TC.int_lit(2)),
            TC.doc(a=TC.int_lit(5), b=TC.int_lit(1)),
        )).sort(TC.desc(TC.field("a")), TC.asc(TC.field("b")))
        bare = _ast.SortStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_b_lit_i(3), b=_b_lit_i(2)),
                _b_doc(a=_b_lit_i(1), b=_b_lit_i(7)),
                _b_doc(a=_b_lit_i(5), b=_b_lit_i(2)),
                _b_doc(a=_b_lit_i(5), b=_b_lit_i(1)),
            )),
            (
                _ast.SortSpec(_b_field("a"), _ast.SortDirection.DESC),
                _ast.SortSpec(_b_field("b"), _ast.SortDirection.ASC),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [
            {"a": 5, "b": 1},
            {"a": 5, "b": 2},
            {"a": 3, "b": 2},
            {"a": 1, "b": 7},
        ]

    async def test_limit(self, db):
        facade = TC.from_(TC.bag(
            TC.int_lit(3), TC.int_lit(1), TC.int_lit(4), TC.int_lit(1),
            TC.int_lit(5), TC.int_lit(9), TC.int_lit(2), TC.int_lit(6),
        )).sort(TC.asc(TC.current())).limit(3)
        bare = _ast.LimitStage(
            _ast.SortStage(
                _ast.FromStageSimple(_b_bag(
                    _b_lit_i(3), _b_lit_i(1), _b_lit_i(4), _b_lit_i(1),
                    _b_lit_i(5), _b_lit_i(9), _b_lit_i(2), _b_lit_i(6),
                )),
                (_ast.SortSpec(_ast.CurrentValue(), _ast.SortDirection.ASC),),
            ),
            3,
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 1}, {"value": 1}, {"value": 2}]

    async def test_project_branching(self, db):
        facade = TC.from_(TC.bag(TC.doc(
            a=TC.doc(x=TC.int_lit(1), y=TC.int_lit(2), z=TC.int_lit(3)),
            b=TC.int_lit(9),
        ))).project("a.x", "a.z", "b")
        bare = _ast.ProjectStage(
            _ast.FromStageSimple(_b_bag(_b_doc(
                a=_b_doc(x=_b_lit_i(1), y=_b_lit_i(2), z=_b_lit_i(3)),
                b=_b_lit_i(9),
            ))),
            _ast.Interior((
                ("a", _ast.Interior((
                    ("x", _ast.Leaf()),
                    ("z", _ast.Leaf()),
                ))),
                ("b", _ast.Leaf()),
            )),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": {"x": 1, "z": 3}, "b": 9}]

    async def test_set_with_arithmetic(self, db):
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.int_lit(1)), TC.doc(a=TC.int_lit(2))
        )).set_(TC.assign("z.add1", TC.int_field("a").add(TC.int_lit(1))))
        bare = _ast.SetStage(
            _ast.FromStageSimple(_b_bag(_b_doc(a=_b_lit_i(1)), _b_doc(a=_b_lit_i(2)))),
            (_ast.Assignment(("z", "add1"), _b_add(_b_field("a"), _b_lit_i(1))),),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"a": 1, "z": {"add1": 2}},
            {"a": 2, "z": {"add1": 3}},
        )

    async def test_unset(self, db):
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.int_lit(1), b=TC.int_lit(2))
        )).unset("b")
        bare = _ast.UnsetStage(
            _ast.FromStageSimple(_b_bag(_b_doc(a=_b_lit_i(1), b=_b_lit_i(2)))),
            _ast.Interior((("b", _ast.Leaf()),)),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": 1}]

    async def test_distinct_and_count(self, db):
        facade_distinct = TC.from_(TC.bag(
            TC.int_lit(1), TC.int_lit(1), TC.int_lit(2), TC.int_lit(3)
        )).distinct()
        bare_distinct = _ast.DistinctStage(
            _ast.FromStageSimple(_b_bag(_b_lit_i(1), _b_lit_i(1), _b_lit_i(2), _b_lit_i(3)))
        )
        _assert_same_ast(facade_distinct.stage, bare_distinct)
        assert _as_set(await _run(db, facade_distinct)) == _bset(
            {"value": 1}, {"value": 2}, {"value": 3}
        )

        facade_count = TC.from_(TC.bag(
            TC.int_lit(1), TC.int_lit(2), TC.int_lit(3), TC.int_lit(4), TC.int_lit(5)
        )).count()
        bare_count = _ast.CountStage(
            _ast.FromStageSimple(_b_bag(
                _b_lit_i(1), _b_lit_i(2), _b_lit_i(3), _b_lit_i(4), _b_lit_i(5)
            ))
        )
        _assert_same_ast(facade_count.stage, bare_count)
        assert await _run(db, facade_count) == [{"value": 5}]

    async def test_unwind_simple(self, db):
        facade = TC.from_(TC.bag(
            TC.arr(TC.int_lit(1), TC.int_lit(2), TC.int_lit(3))
        )).unwind(TC.current())
        bare = _ast.UnwindSimpleStage(
            _ast.FromStageSimple(_ast.BagConstructor((
                _ast.ArrayConstructor((_b_lit_i(1), _b_lit_i(2), _b_lit_i(3))),
            ))),
            _ast.CurrentValue(),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"value": 1}, {"value": 2}, {"value": 3}
        )

    async def test_any_expression_and_arrow(self, db):
        # field("a").arr_arrow("b") → ArrExpr; .any_(int_current().eq(int_lit(2)))
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.arr(TC.doc(b=TC.int_lit(1)), TC.doc(b=TC.int_lit(2)))),
            TC.doc(a=TC.arr(TC.doc(b=TC.int_lit(3)))),
        )).match(TC.field("a").arr_arrow("b").any_(TC.int_current().eq(TC.int_lit(2))))
        bare = _ast.MatchStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_ast.ArrayConstructor((
                    _b_doc(b=_b_lit_i(1)), _b_doc(b=_b_lit_i(2)),
                ))),
                _b_doc(a=_ast.ArrayConstructor((_b_doc(b=_b_lit_i(3)),))),
            )),
            _ast.Any(
                _ast.ArrowOp(_b_field("a"), "b"),
                _b_eq(_ast.CurrentValue(), _b_lit_i(2)),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": [{"b": 1}, {"b": 2}]}]

    async def test_group_with_sum_arrow(self, db):
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.int_lit(1), b=TC.int_lit(2)),
            TC.doc(a=TC.int_lit(1), b=TC.int_lit(3)),
            TC.doc(a=TC.int_lit(2), b=TC.int_lit(4)),
        )).group(
            [TC.assign("k", TC.field("a"))],
            [TC.assign("s", TC.sum_(TC.current().num_arrow("b")))],
        )
        bare = _ast.GroupStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_b_lit_i(1), b=_b_lit_i(2)),
                _b_doc(a=_b_lit_i(1), b=_b_lit_i(3)),
                _b_doc(a=_b_lit_i(2), b=_b_lit_i(4)),
            )),
            (_ast.Assignment(("k",), _b_field("a")),),
            (_ast.Assignment(("s",), _ast.FunctionCall("sum", (
                _ast.ArrowOp(_ast.CurrentValue(), "b"),
            ))),),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset({"k": 1, "s": 5}, {"k": 2, "s": 4})

    async def test_let_expr(self, db):
        facade = TC.from_(TC.let_in([("x", TC.int_lit(2))], TC.int_var("x").add(TC.int_lit(3))))
        bare = _ast.FromStageSimple(
            _ast.LetExpr(
                (("x", _b_lit_i(2)),),
                _ast.BinaryOp(_ast.BinaryOpType.ADD, _ast.VarRef("x"), _b_lit_i(3)),
            )
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 5}]

    async def test_top_level_agg_via_function_call(self, db):
        facade = TC.from_(TC.sum_(TC.bag(
            TC.int_lit(1), TC.int_lit(2), TC.int_lit(3), TC.int_lit(4)
        ).as_int()))
        bare = _ast.FromStageSimple(
            _ast.FunctionCall("sum", (_b_bag(_b_lit_i(1), _b_lit_i(2), _b_lit_i(3), _b_lit_i(4)),))
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"value": 10}]

    async def test_not_and_is_nullish(self, db):
        facade = TC.from_(TC.bag(
            TC.doc(a=TC.int_lit(1)),
            TC.doc(a=TC.null_lit()),
            TC.doc(a=TC.missing_lit()),
        )).match(TC.is_nullish(TC.field("a")).not_())
        bare = _ast.MatchStage(
            _ast.FromStageSimple(_b_bag(
                _b_doc(a=_b_lit_i(1)),
                _b_doc(a=_ast.ValueLit(_ast.VNull())),
                _b_doc(a=_ast.ValueLit(_ast.VMissing())),
            )),
            _ast.UnaryOp(
                _ast.UnaryOpType.NOT,
                _ast.FunctionCall("isNullish", (_b_field("a"),)),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [{"a": 1}]

    async def test_cross_product_from_nested(self, db):
        facade = TC.from_(
            s=TC.bag(TC.int_lit(1), TC.int_lit(2), TC.int_lit(3)),
            s2=TC.bag(TC.int_lit(10), TC.int_lit(20)),
        )
        bare = _ast.FromStageNested((
            ("s",  _b_bag(_b_lit_i(1), _b_lit_i(2), _b_lit_i(3))),
            ("s2", _b_bag(_b_lit_i(10), _b_lit_i(20))),
        ))
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"s": 1, "s2": 10}, {"s": 1, "s2": 20},
            {"s": 2, "s2": 10}, {"s": 2, "s2": 20},
            {"s": 3, "s2": 10}, {"s": 3, "s2": 20},
        )

    async def test_join_default_inner(self, db):
        facade = TC.from_(c=TC.bag(
            TC.doc(id=TC.int_lit(1), items=TC.int_lit(10)),
            TC.doc(id=TC.int_lit(2), items=TC.int_lit(5)),
        )).join(
            None, "o",
            TC.bag(
                TC.doc(id=TC.int_lit(1), items=TC.int_lit(10)),
                TC.doc(id=TC.int_lit(2), items=TC.int_lit(5)),
            ),
            TC.doc_field("c").int_field("id").eq(TC.doc_field("o").int_field("id")),
        )
        c_bag = _b_bag(
            _b_doc(id=_b_lit_i(1), items=_b_lit_i(10)),
            _b_doc(id=_b_lit_i(2), items=_b_lit_i(5)),
        )
        o_bag = _b_bag(
            _b_doc(id=_b_lit_i(1), items=_b_lit_i(10)),
            _b_doc(id=_b_lit_i(2), items=_b_lit_i(5)),
        )
        bare = _ast.JoinStage(
            _ast.FromStageNested((("c", c_bag),)),
            None, "o", o_bag,
            _b_eq(
                _ast.FieldAccess(_b_field("c"), "id"),
                _ast.FieldAccess(_b_field("o"), "id"),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"c": {"id": 1, "items": 10}, "o": {"id": 1, "items": 10}},
            {"c": {"id": 2, "items": 5},  "o": {"id": 2, "items": 5}},
        )

    async def test_join_left_outer(self, db):
        facade = TC.from_(c=TC.bag(
            TC.doc(id=TC.int_lit(1)),
            TC.doc(id=TC.int_lit(2)),
            TC.doc(id=TC.int_lit(3)),
        )).join(
            TC.JoinType.LEFT_OUTER, "o",
            TC.bag(
                TC.doc(id=TC.int_lit(1), v=TC.str_lit("x")),
                TC.doc(id=TC.int_lit(3), v=TC.str_lit("z")),
            ),
            TC.doc_field("c").int_field("id").eq(TC.doc_field("o").int_field("id")),
        )
        bare = _ast.JoinStage(
            _ast.FromStageNested((("c", _b_bag(
                _b_doc(id=_b_lit_i(1)), _b_doc(id=_b_lit_i(2)), _b_doc(id=_b_lit_i(3)),
            )),)),
            _ast.JoinType.LEFT_OUTER, "o",
            _b_bag(
                _b_doc(id=_b_lit_i(1), v=_b_lit_s("x")),
                _b_doc(id=_b_lit_i(3), v=_b_lit_s("z")),
            ),
            _b_eq(
                _ast.FieldAccess(_b_field("c"), "id"),
                _ast.FieldAccess(_b_field("o"), "id"),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert _as_set(await _run(db, facade)) == _bset(
            {"c": {"id": 1}, "o": {"id": 1, "v": "x"}},
            {"c": {"id": 2}},
            {"c": {"id": 3}, "o": {"id": 3, "v": "z"}},
        )

    async def test_date_extractors(self, db):
        dt_millis = int(datetime(2024, 1, 15, 10, 30, 45, 123000, tzinfo=timezone.utc).timestamp() * 1000)

        facade = TC.from_(TC.bag(TC.doc(dt=TC.date_lit(dt_millis)))).format_(TC.doc(
            y=TC.date_field("dt").year(),
            m=TC.date_field("dt").month(),
            dm=TC.date_field("dt").day_of_month(),
            dy=TC.date_field("dt").day_of_year(),
            dw=TC.date_field("dt").day_of_week(),
            h=TC.date_field("dt").hour(),
            mn=TC.date_field("dt").minute(),
            s=TC.date_field("dt").second(),
            ms=TC.date_field("dt").millisecond(),
        ))
        b_dt = _ast.ValueLit(_ast.VDate(dt_millis))
        bare = _ast.FormatStage(
            _ast.FromStageSimple(_b_bag(_b_doc(dt=b_dt))),
            _b_doc(
                y=_b_fn("year",        _b_field("dt")),
                m=_b_fn("month",       _b_field("dt")),
                dm=_b_fn("dayOfMonth", _b_field("dt")),
                dy=_b_fn("dayOfYear",  _b_field("dt")),
                dw=_b_fn("dayOfWeek",  _b_field("dt")),
                h=_b_fn("hour",        _b_field("dt")),
                mn=_b_fn("minute",     _b_field("dt")),
                s=_b_fn("second",      _b_field("dt")),
                ms=_b_fn("millisecond", _b_field("dt")),
            ),
        )
        _assert_same_ast(facade.stage, bare)
        assert await _run(db, facade) == [
            {"y": 2024, "m": 1, "dm": 15, "dy": 15, "dw": 2,
             "h": 10, "mn": 30, "s": 45, "ms": 123}
        ]

    async def test_date_comparisons(self, db):
        jan1  = int(datetime(2024,  1,  1,  0,  0,  0, tzinfo=timezone.utc).timestamp() * 1000)
        dec31 = int(datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        mid   = int(datetime(2024,  6, 15, 10, 30,  0, tzinfo=timezone.utc).timestamp() * 1000)

        facade_lt = TC.from_(TC.date_lit(jan1).lt(TC.date_lit(dec31)))
        bare_lt = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.LT,
                _ast.ValueLit(_ast.VDate(jan1)),
                _ast.ValueLit(_ast.VDate(dec31)))
        )
        _assert_same_ast(facade_lt.stage, bare_lt)
        assert await _run(db, facade_lt) == [{"value": True}]

        facade_eq_true = TC.from_(TC.date_lit(mid).eq(TC.date_lit(mid)))
        bare_eq_true = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.EQ,
                _ast.ValueLit(_ast.VDate(mid)),
                _ast.ValueLit(_ast.VDate(mid)))
        )
        _assert_same_ast(facade_eq_true.stage, bare_eq_true)
        assert await _run(db, facade_eq_true) == [{"value": True}]

        facade_eq_false = TC.from_(TC.date_lit(jan1).eq(TC.date_lit(dec31)))
        bare_eq_false = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.EQ,
                _ast.ValueLit(_ast.VDate(jan1)),
                _ast.ValueLit(_ast.VDate(dec31)))
        )
        _assert_same_ast(facade_eq_false.stage, bare_eq_false)
        assert await _run(db, facade_eq_false) == [{"value": False}]

        facade_is = TC.from_(TC.date_lit(mid).is_(TC.date_lit(mid)))
        bare_is = _ast.FromStageSimple(
            _ast.BinaryOp(_ast.BinaryOpType.IS,
                _ast.ValueLit(_ast.VDate(mid)),
                _ast.ValueLit(_ast.VDate(mid)))
        )
        _assert_same_ast(facade_is.stage, bare_is)
        assert await _run(db, facade_is) == [{"value": True}]

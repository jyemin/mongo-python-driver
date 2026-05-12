"""Conformance tests using bare AST — mirrors Mqlv2ConformanceTest.java.

Requires a mongod with the experimental mqlv2 command on mongodb://localhost:27017.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

from pymongo.asynchronous.mqlv2 import _ast
from pymongo.asynchronous.mqlv2._command import Pipeline

pytestmark = [pytest.mark.default_async, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lit_i(n: int) -> _ast.Expr:
    return _ast.ValueLit(_ast.VInt(n))


def _lit_s(s: str) -> _ast.Expr:
    return _ast.ValueLit(_ast.VString(s))


def _field(name: str) -> _ast.Expr:
    return _ast.FieldAccess(_ast.CurrentValue(), name)


def _eq(l: _ast.Expr, r: _ast.Expr) -> _ast.Expr:
    return _ast.BinaryOp(_ast.BinaryOpType.EQ, l, r)


def _add(l: _ast.Expr, r: _ast.Expr) -> _ast.Expr:
    return _ast.BinaryOp(_ast.BinaryOpType.ADD, l, r)


def _mul(l: _ast.Expr, r: _ast.Expr) -> _ast.Expr:
    return _ast.BinaryOp(_ast.BinaryOpType.MUL, l, r)


def _bag(*es: _ast.Expr) -> _ast.Expr:
    return _ast.BagConstructor(es)


def _doc(**kv: _ast.Expr) -> _ast.Expr:
    return _ast.DocumentConstructor(tuple(
        (_ast.ValueLit(_ast.VString(k)), v) for k, v in kv.items()
    ))


async def _run(db, stage: _ast.Stage) -> list[dict]:
    cursor = await db.mqlv2(Pipeline(stage))
    docs: list[dict] = []
    async for doc in cursor:
        docs.append(doc)
    return docs


def _as_set(docs: list[dict]) -> frozenset:
    return frozenset(json.dumps(d, sort_keys=True) for d in docs)


def _bset(*dicts: dict) -> frozenset:
    return frozenset(json.dumps(d, sort_keys=True) for d in dicts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_match_simple(db):
    ast = _ast.MatchStage(
        _ast.FromStageSimple(_bag(_lit_i(1), _lit_i(2), _lit_i(3))),
        _eq(_ast.CurrentValue(), _lit_i(2)),
    )
    assert await _run(db, ast) == [{"value": 2}]


async def test_format_with_doc_and_mul(db):
    ast = _ast.FormatStage(
        _ast.FromStageSimple(_bag(_doc(a=_lit_i(1)), _doc(a=_lit_i(2)))),
        _doc(doubled=_mul(_field("a"), _lit_i(2))),
    )
    assert _as_set(await _run(db, ast)) == _bset({"doubled": 2}, {"doubled": 4})


async def test_sort_desc_then_asc(db):
    ast = _ast.SortStage(
        _ast.FromStageSimple(_bag(
            _doc(a=_lit_i(3), b=_lit_i(2)),
            _doc(a=_lit_i(1), b=_lit_i(7)),
            _doc(a=_lit_i(5), b=_lit_i(2)),
            _doc(a=_lit_i(5), b=_lit_i(1)),
        )),
        (
            _ast.SortSpec(_field("a"), _ast.SortDirection.DESC),
            _ast.SortSpec(_field("b"), _ast.SortDirection.ASC),
        ),
    )
    assert await _run(db, ast) == [
        {"a": 5, "b": 1},
        {"a": 5, "b": 2},
        {"a": 3, "b": 2},
        {"a": 1, "b": 7},
    ]


async def test_limit(db):
    ast = _ast.LimitStage(
        _ast.SortStage(
            _ast.FromStageSimple(_bag(
                _lit_i(3), _lit_i(1), _lit_i(4), _lit_i(1),
                _lit_i(5), _lit_i(9), _lit_i(2), _lit_i(6),
            )),
            (_ast.SortSpec(_ast.CurrentValue(), _ast.SortDirection.ASC),),
        ),
        3,
    )
    assert await _run(db, ast) == [{"value": 1}, {"value": 1}, {"value": 2}]


async def test_project_branching(db):
    tree = _ast.Interior((
        ("a", _ast.Interior((
            ("x", _ast.Leaf()),
            ("z", _ast.Leaf()),
        ))),
        ("b", _ast.Leaf()),
    ))
    ast = _ast.ProjectStage(
        _ast.FromStageSimple(_bag(_doc(
            a=_doc(x=_lit_i(1), y=_lit_i(2), z=_lit_i(3)),
            b=_lit_i(9),
        ))),
        tree,
    )
    assert await _run(db, ast) == [{"a": {"x": 1, "z": 3}, "b": 9}]


async def test_set_with_arithmetic(db):
    ast = _ast.SetStage(
        _ast.FromStageSimple(_bag(_doc(a=_lit_i(1)), _doc(a=_lit_i(2)))),
        (_ast.Assignment(("z", "add1"), _add(_field("a"), _lit_i(1))),),
    )
    assert _as_set(await _run(db, ast)) == _bset(
        {"a": 1, "z": {"add1": 2}},
        {"a": 2, "z": {"add1": 3}},
    )


async def test_unset(db):
    tree = _ast.Interior((("b", _ast.Leaf()),))
    ast = _ast.UnsetStage(
        _ast.FromStageSimple(_bag(_doc(a=_lit_i(1), b=_lit_i(2)))),
        tree,
    )
    assert await _run(db, ast) == [{"a": 1}]


async def test_distinct_and_count(db):
    distinct = _ast.DistinctStage(
        _ast.FromStageSimple(_bag(_lit_i(1), _lit_i(1), _lit_i(2), _lit_i(3))),
    )
    assert _as_set(await _run(db, distinct)) == _bset(
        {"value": 1}, {"value": 2}, {"value": 3}
    )

    count = _ast.CountStage(
        _ast.FromStageSimple(_bag(_lit_i(1), _lit_i(2), _lit_i(3), _lit_i(4), _lit_i(5))),
    )
    assert await _run(db, count) == [{"value": 5}]


async def test_unwind_simple(db):
    ast = _ast.UnwindSimpleStage(
        _ast.FromStageSimple(_ast.BagConstructor((
            _ast.ArrayConstructor((_lit_i(1), _lit_i(2), _lit_i(3))),
        ))),
        _ast.CurrentValue(),
    )
    assert _as_set(await _run(db, ast)) == _bset(
        {"value": 1}, {"value": 2}, {"value": 3}
    )


async def test_any_expression_and_arrow(db):
    arrow = _ast.ArrowOp(_field("a"), "b")
    predicate = _ast.Any(arrow, _eq(_ast.CurrentValue(), _lit_i(2)))
    ast = _ast.MatchStage(
        _ast.FromStageSimple(_bag(
            _doc(a=_ast.ArrayConstructor((_doc(b=_lit_i(1)), _doc(b=_lit_i(2))))),
            _doc(a=_ast.ArrayConstructor((_doc(b=_lit_i(3)),))),
        )),
        predicate,
    )
    assert await _run(db, ast) == [{"a": [{"b": 1}, {"b": 2}]}]


async def test_group_with_sum_arrow(db):
    ast = _ast.GroupStage(
        _ast.FromStageSimple(_bag(
            _doc(a=_lit_i(1), b=_lit_i(2)),
            _doc(a=_lit_i(1), b=_lit_i(3)),
            _doc(a=_lit_i(2), b=_lit_i(4)),
        )),
        (_ast.Assignment(("k",), _field("a")),),
        (_ast.Assignment(("s",), _ast.FunctionCall("sum", (
            _ast.ArrowOp(_ast.CurrentValue(), "b"),
        ))),),
    )
    assert _as_set(await _run(db, ast)) == _bset({"k": 1, "s": 5}, {"k": 2, "s": 4})


async def test_let_expr(db):
    ast = _ast.FromStageSimple(
        _ast.LetExpr(
            (("x", _lit_i(2)),),
            _add(_ast.VarRef("x"), _lit_i(3)),
        )
    )
    assert await _run(db, ast) == [{"value": 5}]


async def test_top_level_agg_via_function_call(db):
    ast = _ast.FromStageSimple(
        _ast.FunctionCall("sum", (_bag(_lit_i(1), _lit_i(2), _lit_i(3), _lit_i(4)),))
    )
    assert await _run(db, ast) == [{"value": 10}]


async def test_not_and_is_nullish(db):
    is_nullish = _ast.FunctionCall("isNullish", (_field("a"),))
    ast = _ast.MatchStage(
        _ast.FromStageSimple(_bag(
            _doc(a=_lit_i(1)),
            _doc(a=_ast.ValueLit(_ast.VNull())),
            _doc(a=_ast.ValueLit(_ast.VMissing())),
        )),
        _ast.UnaryOp(_ast.UnaryOpType.NOT, is_nullish),
    )
    assert await _run(db, ast) == [{"a": 1}]


async def test_cross_product_from_nested(db):
    ast = _ast.FromStageNested((
        ("s",  _bag(_lit_i(1), _lit_i(2), _lit_i(3))),
        ("s2", _bag(_lit_i(10), _lit_i(20))),
    ))
    assert _as_set(await _run(db, ast)) == _bset(
        {"s": 1, "s2": 10},
        {"s": 1, "s2": 20},
        {"s": 2, "s2": 10},
        {"s": 2, "s2": 20},
        {"s": 3, "s2": 10},
        {"s": 3, "s2": 20},
    )


async def test_join_default_inner(db):
    c_bag = _bag(
        _doc(id=_lit_i(1), items=_lit_i(10)),
        _doc(id=_lit_i(2), items=_lit_i(5)),
    )
    o_bag = _bag(
        _doc(id=_lit_i(1), items=_lit_i(10)),
        _doc(id=_lit_i(2), items=_lit_i(5)),
    )
    c_id = _ast.FieldAccess(_ast.FieldAccess(_ast.CurrentValue(), "c"), "id")
    o_id = _ast.FieldAccess(_ast.FieldAccess(_ast.CurrentValue(), "o"), "id")
    ast = _ast.JoinStage(
        _ast.FromStageNested((("c", c_bag),)),
        None,
        "o",
        o_bag,
        _eq(c_id, o_id),
    )
    assert _as_set(await _run(db, ast)) == _bset(
        {"c": {"id": 1, "items": 10}, "o": {"id": 1, "items": 10}},
        {"c": {"id": 2, "items": 5},  "o": {"id": 2, "items": 5}},
    )


async def test_join_left_outer(db):
    c_bag = _bag(_doc(id=_lit_i(1)), _doc(id=_lit_i(2)), _doc(id=_lit_i(3)))
    o_bag = _bag(
        _doc(id=_lit_i(1), v=_lit_s("x")),
        _doc(id=_lit_i(3), v=_lit_s("z")),
    )
    c_id = _ast.FieldAccess(_ast.FieldAccess(_ast.CurrentValue(), "c"), "id")
    o_id = _ast.FieldAccess(_ast.FieldAccess(_ast.CurrentValue(), "o"), "id")
    ast = _ast.JoinStage(
        _ast.FromStageNested((("c", c_bag),)),
        _ast.JoinType.LEFT_OUTER,
        "o",
        o_bag,
        _eq(c_id, o_id),
    )
    assert _as_set(await _run(db, ast)) == _bset(
        {"c": {"id": 1}, "o": {"id": 1, "v": "x"}},
        {"c": {"id": 2}},
        {"c": {"id": 3}, "o": {"id": 3, "v": "z"}},
    )

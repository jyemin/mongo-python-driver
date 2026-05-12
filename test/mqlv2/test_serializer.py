"""Serializer unit tests — mirrors SerializerTest.java. No server required."""
from __future__ import annotations

import pytest

from pymongo.asynchronous.mqlv2 import _ast
from pymongo.asynchronous.mqlv2._serializer import Serializer

pytestmark = pytest.mark.default

s = Serializer()


def test_simple_match():
    # from <<1, 2, 3>> | match ($ == 2)
    ast = _ast.MatchStage(
        _ast.FromStageSimple(_ast.BagConstructor((
            _ast.ValueLit(_ast.VInt(1)),
            _ast.ValueLit(_ast.VInt(2)),
            _ast.ValueLit(_ast.VInt(3)),
        ))),
        _ast.BinaryOp(
            _ast.BinaryOpType.EQ,
            _ast.CurrentValue(),
            _ast.ValueLit(_ast.VInt(2)),
        ),
    )
    assert s.serialize(ast) == "from <<1, 2, 3>> | match ($ == 2)"


def test_field_access_bare_ident():
    # FieldAccess from CurrentValue → bare identifier, no "$."
    fa = _ast.FieldAccess(_ast.CurrentValue(), "a")
    ast = _ast.MatchStage(
        _ast.FromStageSimple(_ast.BagConstructor(())),
        _ast.BinaryOp(_ast.BinaryOpType.EQ, fa, _ast.ValueLit(_ast.VInt(2))),
    )
    assert s.serialize(ast) == "from <<>> | match (a == 2)"


def test_sort_asc_omitted_desc_explicit():
    ast = _ast.SortStage(
        _ast.FromStageSimple(_ast.BagConstructor(())),
        (
            _ast.SortSpec(_ast.FieldAccess(_ast.CurrentValue(), "a"), _ast.SortDirection.DESC),
            _ast.SortSpec(_ast.FieldAccess(_ast.CurrentValue(), "b"), _ast.SortDirection.ASC),
        ),
    )
    assert s.serialize(ast) == "from <<>> | sort a desc, b"


def test_project_branching():
    # a, x.{y, z}, b
    tree = _ast.Interior((
        ("a", _ast.Leaf()),
        ("x", _ast.Interior((
            ("y", _ast.Leaf()),
            ("z", _ast.Leaf()),
        ))),
        ("b", _ast.Leaf()),
    ))
    ast = _ast.ProjectStage(
        _ast.FromStageSimple(_ast.BagConstructor(())),
        tree,
    )
    assert s.serialize(ast) == "from <<>> | project a, x.{y, z}, b"


def test_unwind_complex():
    a_star = _ast.UnwindExpr(_ast.FieldAccess(_ast.CurrentValue(), "a"))
    body = _ast.DocumentConstructor((
        (_ast.ValueLit(_ast.VString("idx")), _ast.VarRef("i")),
    ))
    ast = _ast.UnwindComplexStage(
        _ast.FromStageSimple(_ast.BagConstructor(())),
        "i",
        a_star,
        body,
    )
    assert s.serialize(ast) == 'from <<>> | unwind $i=a* in {"idx": $i}'


def test_group_with_sum_arrow():
    a = _ast.FieldAccess(_ast.CurrentValue(), "a")
    sum_expr = _ast.FunctionCall("sum", (
        _ast.ArrowOp(_ast.CurrentValue(), "b"),
    ))
    ast = _ast.GroupStage(
        _ast.FromStageSimple(_ast.BagConstructor((
            _ast.DocumentConstructor((
                (_ast.ValueLit(_ast.VString("a")), _ast.ValueLit(_ast.VInt(1))),
                (_ast.ValueLit(_ast.VString("b")), _ast.ValueLit(_ast.VInt(2))),
            )),
        ))),
        (_ast.Assignment(("k",), a),),
        (_ast.Assignment(("s",), sum_expr),),
    )
    assert s.serialize(ast) == 'from <<{"a": 1, "b": 2}>> | group (k = a) (s = sum($->b))'

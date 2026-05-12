"""MQLv2 serializer: Stage → surface text.

Rendering rules mirror the Java Serializer and follow language.yaml.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pymongo.asynchronous.mqlv2 import _ast


class Serializer:
    def serialize(self, stage: _ast.Stage) -> str:
        match stage:
            case _ast.FromStageSimple(source=src):
                return "from " + self._expr(src)
            case _ast.FromStageNested(sources=srcs):
                return "from " + ", ".join(k + "=" + self._expr(v) for k, v in srcs)
            case _ast.MatchStage(source=prev, predicate=pred):
                return self.serialize(prev) + " | match " + self._expr(pred)
            case _ast.FormatStage(source=prev, expr=expr):
                return self.serialize(prev) + " | format " + self._expr(expr)
            case _ast.AggStage(source=prev, expr=expr):
                return self.serialize(prev) + " | agg " + self._expr(expr)
            case _ast.ProjectStage(source=prev, tree=tree):
                return self.serialize(prev) + " | project " + self._tree_top(tree)
            case _ast.LimitStage(source=prev, count=n):
                return self.serialize(prev) + " | limit " + str(n)
            case _ast.SortStage(source=prev, specs=specs):
                return self.serialize(prev) + " | sort " + ", ".join(
                    self._sort_spec(s) for s in specs
                )
            case _ast.GroupStage(source=prev, group_keys=gk, agg_keys=ak):
                return (
                    self.serialize(prev)
                    + " | group ("
                    + ", ".join(self._assign(a) for a in gk)
                    + ") ("
                    + ", ".join(self._assign(a) for a in ak)
                    + ")"
                )
            case _ast.SetStage(source=prev, assignments=assigns):
                return self.serialize(prev) + " | set " + ", ".join(
                    self._assign(a) for a in assigns
                )
            case _ast.UnsetStage(source=prev, tree=tree):
                return self.serialize(prev) + " | unset " + self._tree_top(tree)
            case _ast.DistinctStage(source=prev):
                return self.serialize(prev) + " | distinct"
            case _ast.CountStage(source=prev):
                return self.serialize(prev) + " | count"
            case _ast.UnwindSimpleStage(source=prev, expr=expr):
                return self.serialize(prev) + " | unwind " + self._expr(expr)
            case _ast.UnwindComplexStage(
                source=prev, var_name=vn, source_expr=se, body_expr=be
            ):
                return (
                    self.serialize(prev)
                    + " | unwind $" + vn + "=" + self._expr(se)
                    + " in " + self._expr(be)
                )
            case _ast.JoinStage(
                source=prev, join_type=jt, var_name=vn, right=right, condition=cond
            ):
                jt_frag = "" if jt is None else jt.value + " "
                return (
                    self.serialize(prev)
                    + " | join " + jt_frag
                    + vn + "=" + self._expr(right)
                    + " (" + self._expr(cond) + ")"
                )
        raise TypeError(f"Unhandled Stage: {type(stage).__name__}")  # pragma: no cover

    def _expr(self, expr: _ast.Expr) -> str:
        match expr:
            case _ast.ValueLit(value=v):
                return self._value(v)
            case _ast.CurrentValue():
                return "$"
            case _ast.VarRef(name=n):
                return "$" + n
            case _ast.BinaryOp(op=op, left=l, right=r):
                return "(" + self._expr(l) + " " + op.value + " " + self._expr(r) + ")"
            case _ast.UnaryOp(op=op, arg=a):
                return "(" + op.value + " " + self._expr(a) + ")"
            case _ast.FieldAccess(target=t, field=f):
                if isinstance(t, _ast.CurrentValue):
                    return f
                return self._expr(t) + "." + f
            case _ast.ArrowOp(target=t, field=f):
                return self._expr(t) + "->" + f
            case _ast.ArrayIndex(array=a, index=i):
                return self._expr(a) + "[" + self._expr(i) + "]"
            case _ast.UnwindExpr(arg=a):
                return self._expr(a) + "*"
            case _ast.BagConstructor(elements=els):
                return "<<" + ", ".join(self._expr(e) for e in els) + ">>"
            case _ast.ArrayConstructor(elements=els):
                return "[" + ", ".join(self._expr(e) for e in els) + "]"
            case _ast.DocumentConstructor(fields=flds):
                return "{" + ", ".join(
                    self._expr(k) + ": " + self._expr(v) for k, v in flds
                ) + "}"
            case _ast.Any(sequence=seq, predicate=pred):
                return self._expr(seq) + " any (" + self._expr(pred) + ")"
            case _ast.FunctionCall(name=nm, args=args):
                return nm + "(" + ", ".join(self._expr(a) for a in args) + ")"
            case _ast.SubPipelineExpr(pipeline=p):
                return "(" + self.serialize(p) + ")"
            case _ast.LetExpr(bindings=binds, body=body):
                binds_str = ", ".join("$" + k + " = " + self._expr(v) for k, v in binds)
                return "let " + binds_str + " in " + self._expr(body)
        raise TypeError(f"Unhandled Expr: {type(expr).__name__}")  # pragma: no cover

    def _value(self, v: _ast.Value) -> str:
        match v:
            case _ast.VNull():
                return "null"
            case _ast.VMissing():
                return "missing"
            case _ast.VUndefined():
                return "undefined()"
            case _ast.VBool(value=b):
                return "true" if b else "false"
            case _ast.VInt(value=n):
                return str(n)
            case _ast.VDouble(value=d):
                return repr(d)
            case _ast.VString(value=s):
                return '"' + self._escape(s) + '"'
            case _ast.VDate(millis_since_epoch=ms):
                return 'date("' + self._iso(ms) + '")'
            case _ast.VDocument(fields=flds):
                return "{" + ", ".join(k + ": " + self._value(val) for k, val in flds) + "}"
            case _ast.VSequence(elements=els, ordered=ordered):
                body = ", ".join(self._value(e) for e in els)
                return "[" + body + "]" if ordered else "<<" + body + ">>"
        raise TypeError(f"Unhandled Value: {type(v).__name__}")  # pragma: no cover

    @staticmethod
    def _escape(s: str) -> str:
        out: list[str] = []
        for ch in s:
            if   ch == '"':  out.append('\\"')
            elif ch == '\\': out.append('\\\\')
            elif ch == '\n': out.append('\\n')
            elif ch == '\r': out.append('\\r')
            elif ch == '\t': out.append('\\t')
            else:            out.append(ch)
        return "".join(out)

    @staticmethod
    def _iso(millis: int) -> str:
        dt = datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        ms = millis % 1000
        return (base + f".{ms:03d}Z") if ms else (base + "Z")

    def _sort_spec(self, s: _ast.SortSpec) -> str:
        e = self._expr(s.expr)
        return e if s.direction is _ast.SortDirection.ASC else e + " desc"

    def _assign(self, a: _ast.Assignment) -> str:
        return ".".join(a.path) + " = " + self._expr(a.value)

    def _tree_top(self, tree: _ast.FieldPathTree) -> str:
        if isinstance(tree, _ast.Leaf):
            return ""
        assert isinstance(tree, _ast.Interior)
        return ", ".join(self._tree_path(k, v) for k, v in tree.children)

    def _tree_path(self, name: str, subtree: _ast.FieldPathTree) -> str:
        if isinstance(subtree, _ast.Leaf):
            return name
        assert isinstance(subtree, _ast.Interior)
        if len(subtree.children) == 1:
            k, v = subtree.children[0]
            return name + "." + self._tree_path(k, v)
        return name + ".{" + ", ".join(
            self._tree_path(k, v) for k, v in subtree.children
        ) + "}"

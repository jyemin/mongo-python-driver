# pymongo.asynchronous.mqlv2 (Experimental)

Experimental PyMongo API for MongoDB's new MQLv2 query language. This package is a
**skunkworks** — not for production, not on the public driver release path. Its purpose
is to explore what driver-side APIs over MQLv2 could feel like *if* MQLv2 ever becomes
real.

`db.mqlv2(...)` (added in `Database`) is experimental. The schema and API can change
at any time.

## What's here

1. A hand-written **AST taxonomy** mirroring the MQLv2 surface syntax (`_ast.py` —
   frozen dataclasses, Python 3.10+).
2. A **serializer** that turns an AST into canonical MQLv2 text (`_serializer.py`).
3. A **`Pipeline`** class that holds a root `Stage` and serializes on demand;
   `db.mqlv2(Pipeline(...))` is the primary entry point.
4. Two **builder facades** on top of the AST — one methods-based, one typed-class.
   Same AST underneath; different ergonomics on top.

All code lives under `pymongo/asynchronous/mqlv2/`. The synchronous mirror at
`pymongo/synchronous/mqlv2/` is **generated** by `tools/synchro.py` — all hand-written
work is async-first.

## Architecture

```
pymongo/asynchronous/mqlv2/
  _ast.py          ← frozen dataclasses: Stage, Expr, Value, enums, helpers
  _serializer.py   ← Serializer: Stage → MQLv2 surface text
  _command.py      ← Pipeline (Mqlv2Source impl) + Mqlv2Source protocol; db.mqlv2() returns AsyncCommandCursor
  facades/
    methods.py     ← .eq(), .ne(), .add(), .mul() — named methods only
    typed_classes.py ← IntExpr(NumExpr(Expr)), StrExpr(Expr), DateExpr(Expr) etc.;
                       mypy/pyright enforced
```

```
db.mqlv2(source)                     ← AsyncCommandCursor[Any]
    │
    │  source.to_mqlv2()  (either facade, or a raw string)
    │
    ▼
cursor_command({"mqlv2": "<text>"})
    │
    ▼  wire
  mongod: mqlv2 command → Haskell interpreter → result
```

The driver entry point `db.mqlv2(source)` accepts any object with a `to_mqlv2() -> str`
method (the `Mqlv2Source` protocol), or a plain `str`. Facades produce `Pipeline` objects
that implement this protocol; they share the same `_ast.py` / `_serializer.py` underneath.

## The AST

`pymongo.asynchronous.mqlv2._ast` — hand-written from the schema at
`src/third_party/mqlv2/schema/language.yaml` in the mongodb/mongo repository.

All types are `@dataclass(frozen=True)`. The `Stage` and `Expr` families use `__init_subclass__`
to reject external subclassing (approximate sealing; not enforced at compile time).

- **`Stage`** — 16 frozen dataclass subtypes: `FromStageSimple`, `FromStageNested`,
  `MatchStage`, `FormatStage`, `AggStage`, `ProjectStage`, `LimitStage`, `SortStage`,
  `GroupStage`, `SetStage`, `UnsetStage`, `DistinctStage`, `CountStage`,
  `UnwindSimpleStage`, `UnwindComplexStage`, `JoinStage`.
- **`Expr`** — 16 frozen dataclass subtypes: `ValueLit`, `CurrentValue`, `VarRef`,
  `BinaryOp`, `UnaryOp`, `FieldAccess`, `ArrowOp`, `ArrayIndex`, `UnwindExpr`,
  `BagConstructor`, `ArrayConstructor`, `DocumentConstructor`, `Any`, `FunctionCall`,
  `SubPipelineExpr`, `LetExpr`.
- **`Value`** — 10 literal variants: `VNull`, `VMissing`, `VUndefined`, `VBool`,
  `VInt`, `VDouble`, `VString`, `VDate`, `VDocument`, `VSequence`.
- **Helpers** — `FieldPathTree` (`Interior` / `Leaf`), `SortSpec`, `Assignment`.
- **Enums** — `BinaryOpType` (13 ops), `UnaryOpType` (`NOT`), `SortDirection`
  (`ASC`/`DESC`), `JoinType` (4 variants), `DatePart` (9 variants).

## The serializer

`_serializer.py` is a single module (~200 LOC) that converts any `Stage` to canonical
MQLv2 surface text. Stylistic choices:

- `BinaryOp` and `UnaryOp` always parenthesized (unambiguous, never wrong).
- `FieldAccess` from `CurrentValue` emits the bare identifier (`a`, not `$.a`).
- `DocumentConstructor` keys are quoted strings (`{"a": 1}`).
- `SortSpec` omits `asc` (default); `desc` is always explicit.
- `JoinStage.join_type` segment omitted when `None` (server defaults to inner).
- `BagConstructor`, `ArrayConstructor`: `<<...>>` and `[...]`.

## The facades

Python-specific notes that apply across both facades:

- `from` is a reserved keyword → `from_`. `format`, `sum`, `set`, `filter` are builtins
  → `format_`, `sum_`, `set_`, `filter_`.
- `doc(a=expr, b=expr)` uses keyword args for clean identifier keys. For non-identifier
  keys, `doc_kv({"key with space": expr})` is the escape hatch.
- `from_(c=bag(...), o=bag(...))` — keyword args map naturally to `FromStageNested`
  bindings.
- Python's `and` / `or` cannot be overloaded. Both facades use `.and_()` / `.or_()` and
  `.not_()`.

---

### Bare AST (no facade)

Construct AST dataclasses directly. Verbose, unambiguous, the baseline.

```python
# orders: {customerId, total, status}
MatchStage(
    source=FromStageSimple(VarRef("orders")),
    predicate=BinaryOp(BinaryOpType.EQ,
        FieldAccess(CurrentValue(), "status"),
        ValueLit(VString("shipped")))
)
```

Used directly in conformance tests — the reference shape every facade must match.

---

### Methods facade — `pymongo.asynchronous.mqlv2.facades.methods`

All operations are named methods: `.eq()`, `.ne()`, `.lt()`, `.add()`, `.mul()` etc.
Python's `==` on `Expr` is the default `object.__eq__` — structural equality preserved.

```python
from pymongo.asynchronous.mqlv2.facades.methods import (
    from_, lit, doc, field, current, var, let_in, assign,
    sum_, count_, avg_, min_, max_, any_, JoinType
)

from_(var("orders")).match(field("status").eq(lit("shipped")))
```

No type-level constraints. Mistakes (e.g. `lit("x").mul(lit("y"))`) are accepted at
facade level; the server rejects them at execution time.

---

### Typed-classes facade — `pymongo.asynchronous.mqlv2.facades.typed_classes`

A class hierarchy where operations are gated by subtype: only `NumExpr`/`IntExpr` have
`.add()`/`.mul()` etc.; `StrExpr` and `DateExpr` do not. Type errors are caught by
mypy/pyright statically; at runtime, `AttributeError` is the backstop.

```
Expr  (root)
├── NumExpr(Expr)     — add() / sub() / mul() / div()  (NumExpr × NumExpr → NumExpr)
│   └── IntExpr(NumExpr)  — same methods, covariant: IntExpr × IntExpr → IntExpr  (@overload)
├── BoolExpr(Expr)    — and_() / or_() / not_()
├── StrExpr(Expr)     — regex_match()
├── DateExpr(Expr)    — year() / month() / day_of_month() / … / millisecond()  → IntExpr
├── DocExpr(Expr)     — field() / int_field() / str_field() / bool_field() /
│                       num_field() / date_field() / doc_field() / arr_field()
└── ArrExpr[E](Expr)  — element_at() / unwind() / any_() / size()
```

Factories return the narrowest type. `as_int()`, `as_str()`, `as_num()`, `as_bool()`,
`as_date()`, `as_doc()`, `as_arr()` are pure-cast refiners — same underlying `Expr`
node, different wrapper class, no AST change.

Arrow traversal sits on base `Expr` (MQLv2 allows arrow on any expression), with typed
variants `int_arrow()`, `num_arrow()`, `str_arrow()`, `bool_arrow()`, `date_arrow()`,
`doc_arrow()`, `arr_arrow()` on `Expr` to recover a narrower type from the traversal.

```python
from pymongo.asynchronous.mqlv2.facades.typed_classes import (
    from_, int_lit, str_lit, bool_lit, date_lit, num_lit, lit, doc,
    field, int_field, str_field, bool_field, num_field, date_field, doc_field,
    current, int_current, str_current, num_current,
    var, int_var, str_var,
    let_in, assign, sum_, count_, avg_, min_, max_, any_, JoinType
)

from_(var("orders")).match(str_field("status").eq(str_lit("shipped")))
```

**Two bugs the methods facade admits that typed-classes rejects:**

```python
# methods — both accepted silently at facade level
lit("x").mul(lit("y"))         # Str × Str: server error at runtime
int_lit(1).mul(date_lit(1000)) # Long × Date-valued-as-number: server error

# typed-classes — both caught before execution
str_lit("x").mul(str_lit("y"))     # AttributeError / mypy: StrExpr has no mul()
int_lit(1).mul(date_lit(1000))     # AttributeError / mypy: DateExpr is not NumExpr
```

---

## Side-by-side comparison

Five queries, three ways.

Collection schemas used below:
- `orders`:    `{ customerId, total, status }`
- `products`:  `{ name, price, category }`
- `employees`: `{ name, salary, department: { name } }`
- `customers`: `{ id, name }`

### 1. Match on a collection

```mql
from $orders | match status == "shipped"
```

```python
# Bare AST
MatchStage(
    source=FromStageSimple(VarRef("orders")),
    predicate=BinaryOp(BinaryOpType.EQ,
        FieldAccess(CurrentValue(), "status"),
        ValueLit(VString("shipped")))
)

# Methods
from_(var("orders")).match(field("status").eq(lit("shipped")))

# Typed-classes
from_(var("orders")).match(str_field("status").eq(str_lit("shipped")))
```

### 2. Format with arithmetic

```mql
from $products | format {name, discounted: price * 0.9}
```

```python
# Methods
from_(var("products")).format_(doc(
    name=field("name"),
    discounted=field("price").mul(lit(0.9)),
))

# Typed-classes — num_field returns NumExpr; .mul() is only on NumExpr/IntExpr
from_(var("products")).format_(doc(
    name=str_field("name"),
    discounted=num_field("price").mul(num_lit(0.9)),
))
```

### 3. Group with aggregation

```mql
from $orders | group (customerId=customerId) (orderCount=count($*), totalSpent=sum($->total))
```

```python
# Methods
from_(var("orders")).group(
    [assign("customerId", field("customerId"))],
    [assign("orderCount", count_()), assign("totalSpent", sum_(current().arrow("total")))],
)

# Typed-classes — num_arrow returns NumExpr; sum_ accepts NumExpr
from_(var("orders")).group(
    [assign("customerId", field("customerId"))],
    [assign("orderCount", count_()), assign("totalSpent", sum_(current().num_arrow("total")))],
)
```

### 4. Multi-stage with arrow traversal

```mql
from $employees | match salary > 80000 | format {name, dept: department->name}
```

```python
# Methods
from_(var("employees")) \
    .match(field("salary").gt(lit(80000))) \
    .format_(doc(name=field("name"), dept=field("department").arrow("name")))

# Typed-classes — int_field for salary; doc_field then str_arrow to type the traversal
from_(var("employees")) \
    .match(int_field("salary").gt(int_lit(80000))) \
    .format_(doc(name=str_field("name"), dept=doc_field("department").str_arrow("name")))
```

### 5. Left-outer join

```mql
from c=$customers
  | join leftOuter o=$orders (c.id == o.customerId)
  | format {customer: c.name, total: o.total}
```

```python
# Methods
from_(c=var("customers")).join(
    JoinType.LEFT_OUTER, "o", var("orders"),
    field("c").field("id").eq(field("o").field("customerId")),
).format_(doc(
    customer=field("c").field("name"),
    total=field("o").field("total"),
))

# Typed-classes — typed field accessors on DocExpr recover the leaf type
from_(c=var("customers")).join(
    JoinType.LEFT_OUTER, "o", var("orders"),
    doc_field("c").int_field("id").eq(doc_field("o").int_field("customerId")),
).format_(doc(
    customer=doc_field("c").str_field("name"),
    total=doc_field("o").num_field("total"),
))
```

---

## Trade-offs summary

|                                   | Bare AST | Methods | Typed-classes |
|-----------------------------------|----------|---------|---------------|
| Lines per query (median)          | ~2–4×    | 1×      | 1×            |
| Reads like MQLv2 source           | ✗        | ✓       | ✓ (mostly)    |
| Python `==` means structural eq?  | yes      | yes     | yes           |
| Type-level operation gating       | none     | none    | mypy + runtime |
| `Int × Int → Int` (covariant)     | no       | no      | **yes** (@overload) |
| Arithmetic on strings caught?     | no       | no      | **yes**       |
| Date confused with Int caught?    | no       | no      | **yes**       |
| Explicit type annotations needed  | n/a      | none    | int_lit / int_field etc. |
| mypy / pyright clean              | n/a      | with stubs | natively   |

**Methods** is the simpler facade: one flat `Expr` type, all operations available as
named methods, no factory proliferation. Mistakes reach the server.

**Typed-classes** adds a type hierarchy that gates operations by subtype. The cost is
a wider set of factory names (`int_lit`, `str_lit`, `int_field`, `int_current`,
`int_var`, …); the payoff is that the most common MQLv2 type mistakes (arithmetic on
strings, date/int confusion) become local errors caught by the type checker or at
construction time.

## Sync / async

All hand-written code lives under `pymongo/asynchronous/mqlv2/`. The synchronous mirror
at `pymongo/synchronous/mqlv2/` is generated by `tools/synchro.py`. The replacement table
in `synchro.py` is extended for the new async identifiers:

| async name                    | sync replacement             |
|-------------------------------|------------------------------|
| `AsyncCommandCursor`          | `CommandCursor`              |
| `async for doc in cursor`     | `for doc in cursor`          |
| `await db.mqlv2(...)`         | `db.mqlv2(...)`              |

## Running the tests

A mongod with the experimental `mqlv2` command must be reachable on the default URI
(`mongodb://localhost:27017`).

```bash
python -m pytest tests/asynchronous/mqlv2/               # all mqlv2 tests
python -m pytest tests/asynchronous/mqlv2/test_conformance.py  # AST + server
python -m pytest tests/asynchronous/mqlv2/test_facades.py      # both facades
```

Every conformance test asserts both **AST equivalence with the bare form** (dataclass
`==` on the underlying frozen records) and **result equality against the live server**,
so both facade files exercise the same queries by different construction styles and
prove they produce identical results.

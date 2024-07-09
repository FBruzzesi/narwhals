# Utilities for expression parsing
# Useful for backends which don't have any concept of expressions, such
# and pandas or PyArrow.
from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar
from typing import Union
from typing import cast
from typing import overload

from narwhals.dependencies import get_numpy
from narwhals.utils import flatten

if TYPE_CHECKING:
    from narwhals._arrow.dataframe import ArrowDataFrame
    from narwhals._arrow.expr import ArrowExpr
    from narwhals._arrow.namespace import ArrowNamespace
    from narwhals._arrow.series import ArrowSeries
    from narwhals._arrow.typing import IntoArrowExpr
    from narwhals._pandas_like.dataframe import PandasDataFrame
    from narwhals._pandas_like.expr import PandasExpr
    from narwhals._pandas_like.namespace import PandasNamespace
    from narwhals._pandas_like.series import PandasSeries
    from narwhals._pandas_like.typing import IntoPandasExpr

    CompliantNamespace = Union[PandasNamespace, ArrowNamespace]
    CompliantExpr = Union[PandasExpr, ArrowExpr]
    IntoCompliantExpr = Union[IntoPandasExpr, IntoArrowExpr]
    IntoCompliantExprT = TypeVar("IntoCompliantExprT", bound=IntoCompliantExpr)
    CompliantExprT = TypeVar("CompliantExprT", bound=CompliantExpr)
    CompliantSeries = Union[PandasSeries, ArrowSeries]
    ListOfCompliantSeries = Union[list[PandasSeries], list[ArrowSeries]]
    ListOfCompliantExpr = Union[list[PandasExpr], list[ArrowExpr]]
    CompliantDataFrame = Union[PandasDataFrame, ArrowDataFrame]

    T = TypeVar("T")


def evaluate_into_expr(
    df: CompliantDataFrame, into_expr: IntoCompliantExpr
) -> ListOfCompliantSeries:
    """
    Return list of raw columns.
    """
    expr = parse_into_expr(into_expr, namespace=df.__narwhals_namespace__())
    return expr._call(df)  # type: ignore[arg-type]


@overload
def evaluate_into_exprs(
    df: PandasDataFrame,
    *exprs: IntoPandasExpr,
    **named_exprs: IntoPandasExpr,
) -> list[PandasSeries]: ...


@overload
def evaluate_into_exprs(
    df: ArrowDataFrame,
    *exprs: IntoArrowExpr,
    **named_exprs: IntoArrowExpr,
) -> list[ArrowSeries]: ...


def evaluate_into_exprs(
    df: CompliantDataFrame,
    *exprs: IntoCompliantExprT,
    **named_exprs: IntoCompliantExprT,
) -> ListOfCompliantSeries:
    """Evaluate each expr into Series."""
    series: ListOfCompliantSeries = [  # type: ignore[assignment]
        item
        for sublist in [evaluate_into_expr(df, into_expr) for into_expr in flatten(exprs)]
        for item in sublist
    ]
    for name, expr in named_exprs.items():
        evaluated_expr = evaluate_into_expr(df, expr)
        if len(evaluated_expr) > 1:
            msg = "Named expressions must return a single column"  # pragma: no cover
            raise AssertionError(msg)
        series.append(evaluated_expr[0].alias(name))  # type: ignore[arg-type]
    return series


def maybe_evaluate_expr(
    df: CompliantDataFrame, expr: CompliantExpr | T
) -> ListOfCompliantSeries | T:
    """Evaluate `expr` if it's an expression, otherwise return it as is."""
    if hasattr(expr, "__narwhals_expr__"):
        expr = cast("CompliantExpr", expr)
        return expr._call(df)  # type: ignore[arg-type]
    return expr


@overload
def parse_into_exprs(
    *exprs: IntoPandasExpr,
    namespace: PandasNamespace,
    **named_exprs: IntoPandasExpr,
) -> list[PandasExpr]: ...


@overload
def parse_into_exprs(
    *exprs: IntoArrowExpr,
    namespace: ArrowNamespace,
    **named_exprs: IntoArrowExpr,
) -> list[ArrowExpr]: ...


def parse_into_exprs(
    *exprs: IntoCompliantExpr,
    namespace: CompliantNamespace,
    **named_exprs: IntoCompliantExpr,
) -> ListOfCompliantExpr:
    """Parse each input as an expression (if it's not already one). See `parse_into_expr` for
    more details."""
    out = [
        parse_into_expr(into_expr, namespace=namespace) for into_expr in flatten(exprs)
    ]
    for name, expr in named_exprs.items():
        out.append(parse_into_expr(expr, namespace=namespace).alias(name))
    return out  # type: ignore[return-value]


def parse_into_expr(
    into_expr: IntoCompliantExpr,
    *,
    namespace: CompliantNamespace,
) -> CompliantExpr:
    """Parse `into_expr` as an expression.

    For example, in Polars, we can do both `df.select('a')` and `df.select(pl.col('a'))`.
    We do the same in Narwhals:

    - if `into_expr` is already an expression, just return it
    - if it's a Series, then convert it to an expression
    - if it's a numpy array, then convert it to a Series and then to an expression
    - if it's a string, then convert it to an expression
    - else, raise
    """

    if hasattr(into_expr, "__narwhals_expr__"):
        return into_expr  # type: ignore[return-value]
    if hasattr(into_expr, "__narwhals_series__"):
        return namespace._create_expr_from_series(into_expr)  # type: ignore[arg-type]
    if isinstance(into_expr, str):
        return namespace.col(into_expr)
    if (np := get_numpy()) is not None and isinstance(into_expr, np.ndarray):
        series = namespace._create_native_series(into_expr)
        return namespace._create_expr_from_series(series)
    msg = f"Expected IntoExpr, got {type(into_expr)}"  # pragma: no cover
    raise AssertionError(msg)


def reuse_series_implementation(
    expr: CompliantExprT,
    attr: str,
    *args: Any,
    returns_scalar: bool = False,
    **kwargs: Any,
) -> CompliantExprT:
    """Reuse Series implementation for expression.

    If Series.foo is already defined, and we'd like Expr.foo to be the same, we can
    leverage this method to do that for us.

    Arguments
        expr: expression object.
        attr: name of method.
        returns_scalar: whether the Series version returns a scalar. In this case,
            the expression version should return a 1-row Series.
        args, kwargs: arguments and keyword arguments to pass to function.
    """
    plx = expr.__narwhals_namespace__()

    def func(df: CompliantDataFrame) -> list[CompliantSeries]:
        out: list[CompliantSeries] = []
        for column in expr._call(df):  # type: ignore[arg-type]
            _out = getattr(column, attr)(
                *[maybe_evaluate_expr(df, arg) for arg in args],
                **{
                    arg_name: maybe_evaluate_expr(df, arg_value)
                    for arg_name, arg_value in kwargs.items()
                },
            )
            if returns_scalar:
                out.append(plx._create_series_from_scalar(_out, column))  # type: ignore[arg-type]
            else:
                out.append(_out)
        if expr._output_names is not None:  # safety check
            assert [s.name for s in out] == expr._output_names
        return out

    # Try tracking root and output names by combining them from all
    # expressions appearing in args and kwargs. If any anonymous
    # expression appears (e.g. nw.all()), then give up on tracking root names
    # and just set it to None.
    root_names = copy(expr._root_names)
    output_names = expr._output_names
    for arg in list(args) + list(kwargs.values()):
        if root_names is not None and isinstance(arg, expr.__class__):
            if arg._root_names is not None:
                root_names.extend(arg._root_names)
            else:
                root_names = None
                output_names = None
                break
        elif root_names is None:
            output_names = None
            break

    assert (output_names is None and root_names is None) or (
        output_names is not None and root_names is not None
    )  # safety check

    return plx._create_expr_from_callable(  # type: ignore[return-value]
        func,  # type: ignore[arg-type]
        depth=expr._depth + 1,
        function_name=f"{expr._function_name}->{attr}",
        root_names=root_names,
        output_names=output_names,
    )


def reuse_series_namespace_implementation(
    expr: CompliantExprT, series_namespace: str, attr: str, *args: Any, **kwargs: Any
) -> CompliantExprT:
    """Just like `reuse_series_implementation`, but for e.g. `Expr.dt.foo` instead
    of `Expr.foo`.
    """
    plx = expr.__narwhals_namespace__()
    return plx._create_expr_from_callable(  # type: ignore[return-value]
        lambda df: [
            getattr(getattr(series, series_namespace), attr)(*args, **kwargs)
            for series in expr._call(df)  # type: ignore[arg-type]
        ],
        depth=expr._depth + 1,
        function_name=f"{expr._function_name}->{series_namespace}.{attr}",
        root_names=expr._root_names,
        output_names=expr._output_names,
    )
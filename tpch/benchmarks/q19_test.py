from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import narwhals.stable.v1 as nw
from tpch.benchmarks.utils import lib_to_reader

if TYPE_CHECKING:
    from pytest_codspeed.plugin import BenchmarkFixture

DATA_FOLDER = Path("tests/data")


@pytest.mark.parametrize("library", ["pandas", "polars", "pyarrow", "dask"])
def test_q19(benchmark: BenchmarkFixture, library: str) -> None:
    read_fn = lib_to_reader[library]

    lineitem = nw.from_native(read_fn(DATA_FOLDER / "lineitem.parquet")).lazy()
    part = nw.from_native(read_fn(DATA_FOLDER / "part.parquet")).lazy()

    _ = benchmark(q19, lineitem, part)


def q19(lineitem: nw.LazyFrame, part: nw.LazyFrame) -> nw.DataFrame:
    return (
        part.join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .filter(nw.col("l_shipmode").is_in(["AIR", "AIR REG"]))
        .filter(nw.col("l_shipinstruct") == "DELIVER IN PERSON")
        .filter(
            (
                (nw.col("p_brand") == "Brand#12")
                & nw.col("p_container").is_in(["SM CASE", "SM BOX", "SM PACK", "SM PKG"])
                & (nw.col("l_quantity").is_between(1, 11))
                & (nw.col("p_size").is_between(1, 5))
            )
            | (
                (nw.col("p_brand") == "Brand#23")
                & nw.col("p_container").is_in(
                    ["MED BAG", "MED BOX", "MED PKG", "MED PACK"]
                )
                & (nw.col("l_quantity").is_between(10, 20))
                & (nw.col("p_size").is_between(1, 10))
            )
            | (
                (nw.col("p_brand") == "Brand#34")
                & nw.col("p_container").is_in(["LG CASE", "LG BOX", "LG PACK", "LG PKG"])
                & (nw.col("l_quantity").is_between(20, 30))
                & (nw.col("p_size").is_between(1, 15))
            )
        )
        .select(
            (nw.col("l_extendedprice") * (1 - nw.col("l_discount")))
            .sum()
            .round(2)
            .alias("revenue")
        )
        .collect()
    )
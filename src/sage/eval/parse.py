"""SQL string parsing helpers used by exec-match evaluation.

These Spider-style helpers normalize SQL strings, replace literal values, and
generate value permutations for execution-match comparison.
"""

from __future__ import annotations

import itertools
import re
from collections import namedtuple
from typing import Any, Iterator

import sqlparse
from sqlparse.sql import Comparison, Identifier
from sqlparse.tokens import Whitespace

Token = namedtuple("Token", ["ttype", "value"])
VALUE_NUM_SYMBOL = "VALUERARE"
QUOTE_CHARS = {"`", "'", '"'}


def tokenize(query: str) -> list[Token]:
    return [Token(t.ttype, t.value) for t in sqlparse.parse(query)[0].flatten()]


def join_tokens(tokens: list[Token]) -> str:
    return "".join(x.value for x in tokens).strip().replace("  ", " ")


def round_trip_test(query: str) -> None:
    tokens = tokenize(query)
    reconstructed = "".join(token.value for token in tokens)
    assert query == reconstructed, f"Round trip test fails for string {query}"


def postprocess(query: str) -> str:
    return query.replace("> =", ">=").replace("< =", "<=").replace("! =", "!=")


def strip_query(query: str) -> tuple[list[str], list[str]]:
    """Strip and tokenize a query, replacing literal values with VALUERARE."""
    query_keywords: list[str] = []
    all_values: list[str] = []

    toks = sqlparse.parse(query)[0].flatten()
    values = [
        t.value
        for t in toks
        if t.ttype == sqlparse.tokens.Literal.String.Single
        or t.ttype == sqlparse.tokens.Literal.String.Symbol
    ]

    for val in values:
        all_values.append(val)
        query = query.replace(val.strip(), VALUE_NUM_SYMBOL)

    query_tokenized = query.split()
    float_nums = re.findall(r"[-+]?\d*\.\d+", query)
    all_values += [qt for qt in query_tokenized if qt in float_nums]
    query_tokenized = [VALUE_NUM_SYMBOL if qt in float_nums else qt for qt in query_tokenized]

    query = " ".join(query_tokenized)
    int_nums = [i.strip() for i in re.findall(r"[^tT]\d+", query)]

    all_values += [qt for qt in query_tokenized if qt in int_nums]
    query_tokenized = [VALUE_NUM_SYMBOL if qt in int_nums else qt for qt in query_tokenized]

    for tok in query_tokenized:
        if "." in tok:
            table = re.findall(r"[Tt]\d+\.", tok)
            if len(table) > 0:
                to = tok.replace(".", " . ").split()
                to = [t.lower() for t in to if len(t) > 0]
                query_keywords.extend(to)
            else:
                query_keywords.append(tok.lower())
        elif len(tok) > 0:
            query_keywords.append(tok.lower())
    return query_keywords, all_values


def reformat_query(query: str) -> str:
    query = query.strip().replace(";", "").replace("\t", "")
    query = " ".join(t.value for t in tokenize(query) if t.ttype != sqlparse.tokens.Whitespace)
    for ts in ("t1.*", "t2.*", "t3.*", "T1.*", "T2.*", "T3.*"):
        query = query.replace(ts, "*")
    return query


def replace_values(sql: str) -> tuple[list[str], set[str]]:
    sql = sqlparse.format(sql, reindent=False, keyword_case="upper")
    sql = re.sub(r"(T\d+\.)\s", r"\1", sql)
    query_toks_no_value, values = strip_query(sql)
    return query_toks_no_value, set(values)


def extract_query_values(sql: str) -> tuple[list[str], set[str]]:
    reformated = reformat_query(query=sql)
    query_value_replaced, values = replace_values(reformated)
    return query_value_replaced, values


def plugin(query_value_replaced: list[str], values_in_order: list[str]) -> str:
    q_length = len(query_value_replaced)
    query_w_values = query_value_replaced[:]
    value_idx = [idx for idx in range(q_length) if query_value_replaced[idx] == VALUE_NUM_SYMBOL.lower()]
    assert len(value_idx) == len(values_in_order)
    for idx, value in zip(value_idx, values_in_order):
        query_w_values[idx] = value
    return " ".join(query_w_values)


def plugin_all_permutations(query_value_replaced: list[str], values: set[str]) -> Iterator[str]:
    num_slots = len([v for v in query_value_replaced if v == VALUE_NUM_SYMBOL.lower()])
    for values_perm in itertools.product(*[list(values) for _ in range(num_slots)]):
        yield plugin(query_value_replaced, list(values_perm))


def get_all_preds_for_execution(gold: str, pred: str) -> tuple[int, Iterator[str]]:
    _, gold_values = extract_query_values(gold)
    pred_query_value_replaced, _ = extract_query_values(pred)
    num_slots = len([v for v in pred_query_value_replaced if v == VALUE_NUM_SYMBOL.lower()])
    num_alternatives = len(gold_values) ** num_slots
    return num_alternatives, plugin_all_permutations(pred_query_value_replaced, gold_values)


def remove_distinct(s: str) -> str:
    toks = [t.value for t in list(sqlparse.parse(s)[0].flatten())]
    return "".join(t for t in toks if t.lower() != "distinct")


def extract_all_comparison_from_node(node: Any) -> list[Comparison]:
    comparison_list: list[Comparison] = []
    if hasattr(node, "tokens"):
        for t in node.tokens:
            comparison_list.extend(extract_all_comparison_from_node(t))
    if type(node) == Comparison:
        comparison_list.append(node)
    return comparison_list


def extract_all_comparison(query: str) -> list[Comparison]:
    tree = sqlparse.parse(query)[0]
    return extract_all_comparison_from_node(tree)


def extract_toks_from_comparison(comparison_node: Comparison) -> list[Token]:
    return [t for t in comparison_node.tokens if t.ttype != Whitespace]


def process_str_value(v: str) -> str:
    if len(v) > 0 and v[0] in QUOTE_CHARS:
        v = v[1:]
    if len(v) > 0 and v[-1] in QUOTE_CHARS:
        v = v[:-1]
    for c in QUOTE_CHARS:
        v = v.replace(c + c, c)
    return v


def extract_info_from_comparison(comparison_node: Comparison) -> dict[str, Any]:
    tokens = extract_toks_from_comparison(comparison_node)
    left, op, right = tokens

    returned_dict: dict[str, Any] = {"left": left, "op": op.value, "right": right}

    if type(left) != Identifier:
        return returned_dict

    table = None
    if len(left.tokens) == 3 and re.match(r"^[tT][0-9]$", left.tokens[0].value) is None:
        table = left.tokens[0].value.lower()
    col = left.tokens[-1].value

    if type(right) == Identifier:
        if len(right.tokens) == 1 and type(right.tokens[0]) == sqlparse.sql.Token:
            right_val = right.tokens[0].value
        else:
            return returned_dict
    elif type(right) == sqlparse.sql.Token:
        right_val = right.value
    else:
        return returned_dict

    returned_dict["table_col"] = (table, col.upper())
    returned_dict["val"] = process_str_value(right_val)
    return returned_dict


def extract_all_comparison_from_query(query: str) -> list[dict[str, Any]]:
    return [extract_info_from_comparison(c) for c in extract_all_comparison(query)]


def extract_typed_value_in_comparison_from_query(
    query: str,
) -> list[tuple[tuple[str | None, str], str]]:
    cmps = extract_all_comparison_from_query(query)
    typed_values = [(cmp["table_col"], cmp["val"]) for cmp in cmps if "table_col" in cmp]
    for table, col, val1, val2 in re.findall(
        r"(?:([^\.\s]*)\.)?([^\.\s]+) between ([^\s;]+) and ([^\s;]+)", query, re.IGNORECASE
    ):
        if table == "":
            table = None
        else:
            table = table.lower()
        col = col.upper()
        for v in (val1, val2):
            typed_values.append(((table, col), v))
    return typed_values

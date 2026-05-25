from __future__ import annotations

import ast
import operator
from pathlib import Path
from typing import Any

import yaml

from .bench_config import BenchConfigExtended


def load_bench_yaml(path_or_dict: str | Path | dict) -> BenchConfigExtended:
    """Load and validate a bench configuration from a YAML file or dictionary."""
    if isinstance(path_or_dict, str | Path):
        with open(path_or_dict) as f:
            data = yaml.safe_load(f)
    elif isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        raise TypeError("Input must be a path or dict.")
    config = BenchConfigExtended.model_validate(data)
    return config


def build_validation_context(config: BenchConfigExtended) -> dict[str, Any]:
    """Build a context dictionary for custom validation expressions."""
    context = {}
    for alias, entry in config.devices.items():
        context[alias] = entry.model_dump()
    for alias, entry in config.instruments.items():
        context[alias] = entry.model_dump()
    context["experiment"] = config.experiment.model_dump() if config.experiment else {}
    return context


def run_custom_validations(config: BenchConfigExtended, context: dict) -> None:
    """Run custom validation expressions and raise ValueError if any fail."""
    if not config.custom_validations:
        return
    for expr in config.custom_validations:
        try:
            if not _safe_eval_validation(expr, context):
                raise ValueError(f"Custom validation failed: {expr}")
        except Exception as e:
            raise ValueError(f"Error evaluating custom validation '{expr}': {e}") from e


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def _safe_eval_validation(expr: str, context: dict[str, Any]) -> Any:
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body, context)


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in context:
            raise ValueError(f"Unknown validation name: {node.id}")
        return context[node.id]
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        key = _eval_node(node.slice, context)
        return value[key]
    if isinstance(node, ast.List):
        return [_eval_node(item, context) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item, context) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval_node(key, context): _eval_node(value, context)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for value in node.values:
                result = _eval_node(value, context)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value in node.values:
                result = _eval_node(value, context)
                if result:
                    return result
            return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, context))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](
            _eval_node(node.left, context), _eval_node(node.right, context)
        )
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if type(op) not in _CMP_OPS:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            right = _eval_node(comparator, context)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ValueError(f"Unsupported validation expression: {type(node).__name__}")

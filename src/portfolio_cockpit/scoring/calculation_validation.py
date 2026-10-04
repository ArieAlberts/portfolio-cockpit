from __future__ import annotations

import ast
import math
import operator
from dataclasses import asdict, dataclass
from typing import Any


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculationExpressionError(ValueError):
    """Raised when a stored calculation is not safe, finite arithmetic."""


@dataclass(frozen=True)
class CalculationCheck:
    ticker: str
    metric_name: str
    status: str
    stored_value: float | None
    calculated_value: float | None
    calculation: str
    absolute_error: float | None
    score_eligible: bool
    blocking: bool


def _evaluate_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculationExpressionError("CALCULATION_NON_NUMERIC_CONSTANT")
        value = float(node.value)
        if not math.isfinite(value):
            raise CalculationExpressionError("CALCULATION_NON_FINITE_CONSTANT")
        return value

    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        try:
            value = _ALLOWED_BINOPS[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise CalculationExpressionError("CALCULATION_DIVISION_BY_ZERO") from exc
        if not math.isfinite(value):
            raise CalculationExpressionError("CALCULATION_NON_FINITE_RESULT")
        return float(value)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        value = _ALLOWED_UNARYOPS[type(node.op)](_evaluate_node(node.operand))
        if not math.isfinite(value):
            raise CalculationExpressionError("CALCULATION_NON_FINITE_RESULT")
        return float(value)

    raise CalculationExpressionError(
        f"CALCULATION_UNSUPPORTED_SYNTAX:{type(node).__name__}"
    )


def evaluate_calculation(expression: str) -> float:
    """Evaluate a restricted arithmetic expression without Python eval()."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalculationExpressionError("CALCULATION_EMPTY")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculationExpressionError("CALCULATION_SYNTAX_ERROR") from exc
    return _evaluate_node(tree)


def validate_metric_calculation(
    *,
    ticker: str,
    metric_name: str,
    metric: dict[str, Any],
    absolute_tolerance: float,
    relative_tolerance: float,
) -> CalculationCheck | None:
    expression = metric.get("calculation")
    if expression is None:
        return None

    score_eligible = bool(metric.get("score_eligible", False))
    stored = metric.get("value")
    if stored is None:
        return CalculationCheck(
            ticker=ticker,
            metric_name=metric_name,
            status="NO_STORED_VALUE",
            stored_value=None,
            calculated_value=None,
            calculation=str(expression),
            absolute_error=None,
            score_eligible=score_eligible,
            blocking=False,
        )

    stored_value = float(stored)
    try:
        calculated = evaluate_calculation(str(expression))
    except CalculationExpressionError:
        return CalculationCheck(
            ticker=ticker,
            metric_name=metric_name,
            status="INVALID_CALCULATION",
            stored_value=stored_value,
            calculated_value=None,
            calculation=str(expression),
            absolute_error=None,
            score_eligible=score_eligible,
            blocking=score_eligible,
        )

    error = abs(calculated - stored_value)
    matches = math.isclose(
        calculated,
        stored_value,
        rel_tol=float(relative_tolerance),
        abs_tol=float(absolute_tolerance),
    )
    status = "MATCH" if matches else "CALCULATION_MISMATCH"
    return CalculationCheck(
        ticker=ticker,
        metric_name=metric_name,
        status=status,
        stored_value=stored_value,
        calculated_value=calculated,
        calculation=str(expression),
        absolute_error=error,
        score_eligible=score_eligible,
        blocking=(not matches and score_eligible),
    )


def validate_dataset_calculations(
    *,
    dataset: dict[str, Any],
    absolute_tolerance: float = 0.001,
    relative_tolerance: float = 0.00001,
) -> dict[str, Any]:
    if absolute_tolerance < 0 or relative_tolerance < 0:
        raise ValueError("Calculation tolerances must be non-negative.")

    checks: list[CalculationCheck] = []
    for ticker, company in dataset.get("companies", {}).items():
        for metric_name, metric in company.get("metrics", {}).items():
            if not isinstance(metric, dict) or "calculation" not in metric:
                continue
            check = validate_metric_calculation(
                ticker=ticker,
                metric_name=metric_name,
                metric=metric,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
            if check is not None:
                checks.append(check)

    blocking = [check for check in checks if check.blocking]
    nonblocking_issues = [
        check
        for check in checks
        if not check.blocking and check.status not in {"MATCH", "NO_STORED_VALUE"}
    ]
    return {
        "checks_evaluated": len(checks),
        "matched": sum(check.status == "MATCH" for check in checks),
        "blocking_issue_count": len(blocking),
        "nonblocking_issue_count": len(nonblocking_issues),
        "blocking_issues": [asdict(check) for check in blocking],
        "nonblocking_issues": [asdict(check) for check in nonblocking_issues],
        "integrity_pass": not blocking,
    }

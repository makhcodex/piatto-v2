"""The one architectural boundary a machine guards.

Everything else in this codebase ("handlers must not calculate", "handlers must
not open a session") rests on review. That is exactly the discipline v1 lost.
This test is the reason domain/ is a top-level package and not services/pricing.py.
"""

import ast
import pathlib

import pytest

DOMAIN = pathlib.Path(__file__).resolve().parents[2] / "domain"

BANNED_ROOTS = {"aiogram", "sqlalchemy", "asyncpg", "apscheduler", "db", "services", "handlers"}


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    return roots


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda p: p.name)
def test_domain_module_imports_no_framework(path: pathlib.Path) -> None:
    offenders = _imported_roots(path) & BANNED_ROOTS
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)}. domain/ must stay pure — "
        f"move the impure part into services/."
    )


def test_domain_package_is_not_empty() -> None:
    """Guards against the test passing because someone deleted domain/."""
    assert len(list(DOMAIN.glob("*.py"))) >= 3

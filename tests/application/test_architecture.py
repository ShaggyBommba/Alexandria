from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ROOT = PROJECT_ROOT / "src" / "application"
PROVIDER_MODULE_PREFIXES = ("openai", "langchain", "langchain_openai")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_application_usecases_do_not_import_provider_sdks() -> None:
    files = [
        APPLICATION_ROOT / "ports.py",
        *sorted((APPLICATION_ROOT / "usecases").glob("*.py")),
    ]

    violations: list[str] = []
    for path in files:
        for module in imported_modules(path):
            if module.startswith(PROVIDER_MODULE_PREFIXES):
                violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")

    assert violations == []

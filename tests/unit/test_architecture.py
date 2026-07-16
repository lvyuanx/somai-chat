import ast
from pathlib import Path


def test_application_does_not_import_provider_or_transport_clients() -> None:
    application = Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "application"
    forbidden = {"openai", "httpx", "somai_chat.providers"}

    for source_path in application.glob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported.update(
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(name == prefix or name.startswith(f"{prefix}.") for name in imported for prefix in forbidden)

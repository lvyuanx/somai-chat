from somai_chat.admin.models import Base


def test_client_key_schema_keeps_key_material_separate() -> None:
    assert set(Base.metadata.tables) == {"clients", "client_access_keys", "capabilities"}
    columns = Base.metadata.tables["client_access_keys"].c

    assert {"id", "client_id", "key_id", "secret_digest", "encrypted_key", "expires_at", "revoked_at"} <= set(
        columns.keys()
    )
    assert "raw_key" not in columns


def test_capability_schema_keeps_api_key_encrypted() -> None:
    columns = Base.metadata.tables["capabilities"].c

    assert {
        "key",
        "enabled",
        "configuration",
        "encrypted_api_key",
        "created_at",
        "updated_at",
    } == set(columns.keys())
    assert "api_key" not in columns


def test_client_schema_indexes_public_key_lookup() -> None:
    keys = Base.metadata.tables["client_access_keys"]

    assert any(index.columns.keys() == ["key_id"] for index in keys.indexes)

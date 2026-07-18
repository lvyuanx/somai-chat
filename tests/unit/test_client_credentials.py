from somai_chat.admin.credentials import create_key_material, verify_key


def test_generated_key_is_verifiable_without_storing_secret() -> None:
    key, material = create_key_material("pepper")

    assert key.startswith(f"somai_sk_{material.key_id}_")
    assert material.secret_digest != key
    assert verify_key(key, material.key_id, material.secret_digest, "pepper")


def test_wrong_key_is_not_verifiable() -> None:
    key, material = create_key_material("pepper")

    assert not verify_key(f"{key}x", material.key_id, material.secret_digest, "pepper")

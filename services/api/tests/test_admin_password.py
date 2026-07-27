from app.core.admin_password import hash_password, verify_password


def test_hash_then_verify_succeeds():
    encoded = hash_password("a reasonably long passphrase")

    assert verify_password("a reasonably long passphrase", encoded) is True


def test_wrong_password_fails():
    encoded = hash_password("correct-horse-battery-staple")

    assert verify_password("wrong-password", encoded) is False


def test_none_hash_fails_without_raising():
    assert verify_password("anything", None) is False


def test_empty_string_hash_fails_without_raising():
    assert verify_password("anything", "") is False


def test_malformed_hash_fails_without_raising():
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_hash_is_not_plaintext():
    encoded = hash_password("super-secret-admin-password")

    assert "super-secret-admin-password" not in encoded
    assert encoded.startswith("$argon2id$")

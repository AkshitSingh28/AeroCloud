from aeroos.security import hash_pin, verify_pin


def test_pin_hash_round_trip() -> None:
    encoded = hash_pin("0420")
    assert verify_pin("0420", encoded)
    assert not verify_pin("0000", encoded)
    assert "0420" not in encoded


import pytest
from auth import verify_password, get_password_hash, create_access_token

def test_password_hashing():
    password = "supersecretpassword"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_jwt_creation():
    data = {"sub": "123"}
    token = create_access_token(data)
    assert isinstance(token, str)
    assert len(token) > 0
    assert token.count('.') == 2  # JWTs have 3 parts separated by dots

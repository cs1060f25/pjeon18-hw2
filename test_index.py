# tests/test_index.py
import base64
import json
import os
import sys
import pathlib
import pytest


# Ensure 'api' package is importable in local runs
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.index import app, convert_number  # noqa: E402


# ----------- Unit tests for pure conversion -----------

@pytest.mark.parametrize(
    "value, itype, otype, expected",
    [
        ("42", "decimal", "binary", "101010"),
        ("42", "decimal", "octal", "52"),
        ("42", "decimal", "hexadecimal", "2a"),
        ("42", "decimal", "decimal", "42"),
        ("101010", "binary", "decimal", "42"),
        ("52", "octal", "decimal", "42"),
        ("2a", "hexadecimal", "decimal", "42"),
        ("forty two", "text", "decimal", "42"),
    ],
)
def test_round_basic(value, itype, otype, expected):
    out, n = convert_number(value, itype, otype)
    assert out == expected
    assert isinstance(n, int)


def test_text_out_rough():
    out, _ = convert_number("42", "decimal", "text")
    # Accept either "forty two", "forty-two", or similar variants
    assert "forty" in out


# ----- Base64 LITTLE-ENDIAN correctness -----

def le64(n: int) -> str:
    ln = max(1, (n.bit_length() + 7) // 8)
    raw = n.to_bytes(ln, "little", signed=False)
    return base64.b64encode(raw).decode()

@pytest.mark.parametrize(
    "n, b64",
    [
        (0, "AA=="),
        (42, "Kg=="),       # 42 -> 0x2A -> b'*' -> "Kg=="
        (255, "/w=="),
        (256, "AAE="),      # 0x0100 -> little-endian bytes b'\x00\x01'
        (257, "AQE="),      # 0x0101 -> b'\x01\x01'
    ],
)
def test_decimal_to_base64_little_endian(n, b64):
    out, _ = convert_number(str(n), "decimal", "base64")
    assert out == b64 == le64(n)

@pytest.mark.parametrize(
    "b64, n",
    [
        ("AA==", 0),
        ("Kg==", 42),
        ("/w==", 255),
        ("AAE=", 256),
        ("AQE=", 257),
    ],
)
def test_base64_to_decimal_little_endian(b64, n):
    out, _ = convert_number(b64, "base64", "decimal")
    assert out == str(n)


# ----- Error handling -----

@pytest.mark.parametrize(
    "value, itype",
    [
        ("", "decimal"),
        ("", "binary"),
        ("", "hexadecimal"),
    ],
)
def test_empty_input_errors(value, itype):
    with pytest.raises(Exception):
        convert_number(value, itype, "decimal")

@pytest.mark.parametrize(
    "value, itype",
    [
        ("102", "binary"),
        ("89", "octal"),
        ("2g", "hexadecimal"),
        ("@@@", "base64"),
    ],
)
def test_invalid_digits(value, itype):
    with pytest.raises(Exception):
        convert_number(value, itype, "decimal")

def test_base64_negative_forbidden():
    with pytest.raises(Exception):
        convert_number("-5", "decimal", "base64")


# ----- Negative numbers (non-base64) -----

@pytest.mark.parametrize(
    "value, otype, expected",
    [
        ("-5", "decimal", "-5"),
        ("-5", "binary", "-101"),
        ("-5", "octal", "-5"),
        ("-5", "hexadecimal", "-5"),
    ],
)
def test_negative_numbers_supported(value, otype, expected):
    out, _ = convert_number(value, "decimal", otype)
    # note: oct(-5)[2:] == 'o5' if we used prefix; our code strips prefix, so '-5' expected
    assert out == expected


# ----------- Integration tests (Flask route) -----------

@pytest.fixture(scope="module")
def client():
    app.testing = True
    with app.test_client() as c:
        yield c

def post_convert(client, payload):
    return client.post(
        "/convert",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )

def test_route_success_decimal_to_binary(client):
    r = post_convert(client, {"input_value": "42", "input_type": "decimal", "output_type": "binary"})
    assert r.status_code == 200
    assert r.get_json()["result"] == "101010"

def test_route_handles_form_data(client):
    r = client.post(
        "/convert",
        data={"input_value": "2a", "input_type": "hexadecimal", "output_type": "decimal"},
        content_type="application/x-www-form-urlencoded",
    )
    assert r.status_code == 200
    assert r.get_json()["result"] == "42"

def test_route_error_status_and_message(client):
    r = post_convert(client, {"input_value": "2g", "input_type": "hexadecimal", "output_type": "decimal"})
    assert r.status_code == 400
    j = r.get_json()
    assert "error" in j and isinstance(j["error"], str)

def test_route_requires_input_value(client):
    r = post_convert(client, {"input_type": "decimal", "output_type": "binary"})
    assert r.status_code == 400
    assert "input_value" in r.get_json()["error"]

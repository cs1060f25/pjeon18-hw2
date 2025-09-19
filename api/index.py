from __future__ import annotations
import base64
import binascii
import re
from typing import Literal, Tuple

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

SUPPORTED_TYPES = {"text", "binary", "octal", "decimal", "hexadecimal", "base64"}
NumberType = Literal["text", "binary", "octal", "decimal", "hexadecimal", "base64"]

HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Numeric Converter</title>
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <style>
      body { font-family: system-ui, sans-serif; padding: 2rem; max-width: 800px; margin: auto; }
      form { display: grid; gap: 0.75rem; grid-template-columns: 1fr 1fr; align-items: end; }
      label { font-weight: 600; margin-bottom: 0.25rem; }
      input, select, button { padding: 0.6rem; font-size: 1rem; }
      button { grid-column: span 2; cursor: pointer; }
      .row { grid-column: span 2; }
      .result { margin-top: 1rem; padding: 0.8rem; background: #f6f6f6; border-radius: 8px; }
      code { font-family: monospace; }
    </style>
  </head>
  <body>
    <h1>Numeric Converter</h1>
    <p>Convert between Text, Binary, Octal, Decimal, Hexadecimal, and Base64.</p>
    <form id="form">
      <div class="row">
        <label for="input_value">Input</label>
        <input id="input_value" name="input_value" placeholder="e.g., 42 or 101010 or forty two" />
      </div>
      <div>
        <label for="input_type">Input Type</label>
        <select id="input_type" name="input_type">
          <option>decimal</option>
          <option>binary</option>
          <option>octal</option>
          <option>hexadecimal</option>
          <option>base64</option>
          <option>text</option>
        </select>
      </div>
      <div>
        <label for="output_type">Output Type</label>
        <select id="output_type" name="output_type">
          <option>decimal</option>
          <option>binary</option>
          <option>octal</option>
          <option>hexadecimal</option>
          <option>base64</option>
          <option>text</option>
        </select>
      </div>
      <button type="submit">Convert</button>
    </form>
    <div id="result" class="result" hidden></div>
    <script>
      const form = document.getElementById('form');
      const resultEl = document.getElementById('result');
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = new FormData(form);
        const payload = {
          input_value: data.get('input_value'),
          input_type: data.get('input_type'),
          output_type: data.get('output_type'),
        };
        const r = await fetch('/convert', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        const j = await r.json();
        resultEl.hidden = false;
        if (r.ok) {
          resultEl.innerHTML = '<strong>Result:</strong> <code>' + j.result + '</code>';
        } else {
          resultEl.innerHTML = '<strong>Error:</strong> ' + j.error;
        }
      });
    </script>
  </body>
</html>
"""

# ---------- Helpers ----------

_WS_RE = re.compile(r"[\s_]+")


def _clean(s: str) -> str:
    return _WS_RE.sub("", s.strip().lower())


def _require_supported(t: str) -> NumberType:
    t = t.strip().lower()
    if t not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported type '{t}'. Supported: {sorted(SUPPORTED_TYPES)}")
    return t  # type: ignore[return-value]


def _text_to_int(s: str) -> int:
    """
    Convert simple English text (“forty two”, “one hundred twenty-three”) to int.
    Always handles spaces/hyphens.
    """
    s = s.strip().lower().replace("-", " ")
    tokens = s.split()

    # try word2number if installed
    try:
        from word2number import w2n  # type: ignore
        return int(w2n.word_to_num(" ".join(tokens)))
    except Exception:
        pass

    # simple numbers
    UNITS = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }
    MULT = {"hundred": 100, "thousand": 1000}

    total, current = 0, 0
    for token in tokens:
        if token in UNITS:
            current += UNITS[token]
        elif token in MULT:
            if current == 0:
                current = 1
            current *= MULT[token]
            if token == "thousand":
                total += current
                current = 0
        elif token == "and":
            continue
        else:
            raise ValueError(f"Unsupported text token: {token}")
    return total + current



def _int_to_text(n: int) -> str:
    try:
        from num2words import num2words  # type: ignore
        return num2words(n, to="cardinal", lang="en").replace(",", "")
    except Exception:
        return str(n)


def _parse_to_int(value: str, in_type: NumberType) -> int:
    if in_type == "text":
        return _text_to_int(value)

    neg = False
    s = value.strip()
    if s.startswith("-"):
        neg, s = True, s[1:]

    if in_type == "decimal":
        if s == "":
            raise ValueError("Empty decimal value")
        n = int(s, 10)

    elif in_type == "binary":
        s = _clean(s.replace("0b", ""))
        if not re.fullmatch(r"[01]*", s):
            raise ValueError("Invalid binary digits")
        n = int(s or "0", 2)

    elif in_type == "octal":
        s = _clean(s.replace("0o", ""))
        if not re.fullmatch(r"[0-7]*", s):
            raise ValueError("Invalid octal digits")
        n = int(s or "0", 8)

    elif in_type == "hexadecimal":
        s = _clean(s.replace("0x", ""))
        if not re.fullmatch(r"[0-9a-f]*", s):
            raise ValueError("Invalid hexadecimal digits")
        n = int(s or "0", 16)

    elif in_type == "base64":
        try:
            raw = base64.b64decode(s, validate=True)
        except binascii.Error:
            raise ValueError("Invalid base64")
        n = int.from_bytes(raw, byteorder="little", signed=False)
    else:
        raise ValueError(f"Unsupported input type: {in_type}")

    return -n if neg and in_type != "base64" else n


def _from_int(n: int, out_type: NumberType) -> str:
    if out_type == "decimal":
        return str(n)
    if out_type == "binary":
        return "-" + bin(-n)[2:] if n < 0 else bin(n)[2:]
    if out_type == "octal":
        return "-" + oct(-n)[2:] if n < 0 else oct(n)[2:]
    if out_type == "hexadecimal":
        return "-" + hex(-n)[2:] if n < 0 else hex(n)[2:]
    if out_type == "text":
        return _int_to_text(n)
    if out_type == "base64":
        if n < 0:
            raise ValueError("Base64 only supports non-negative integers")
        length = max(1, (n.bit_length() + 7) // 8)
        raw = n.to_bytes(length, byteorder="little", signed=False)
        return base64.b64encode(raw).decode("ascii")
    raise ValueError(f"Unsupported output type: {out_type}")


def convert_number(value: str, input_type: str, output_type: str) -> Tuple[str, int]:
    it = _require_supported(input_type)
    ot = _require_supported(output_type)
    n = _parse_to_int(value, it)
    return _from_int(n, ot), n

# ---------- Routes ----------

@app.get("/")
def home():
    return render_template_string(HTML)


@app.post("/convert")
def convert_route():
    try:
        data = {}
        if request.is_json:
            data.update(request.get_json(silent=True) or {})
        if request.form:
            data.update(request.form)

        input_value = str(data.get("input_value", "")).strip()
        input_type = str(data.get("input_type", "")).strip().lower()
        output_type = str(data.get("output_type", "")).strip().lower()

        if not input_value:
            return jsonify(error="input_value is required"), 400

        result, _ = convert_number(input_value, input_type, output_type)
        return jsonify(result=result)
    except Exception as e:
        return jsonify(error=str(e)), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

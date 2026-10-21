set -eu
ROOT=/aosp/development/lax-three-context-20261018-r01
OUT="$ROOT/qualification/role-decision-build-r251"
test ! -e "$OUT"
test ! -e /opt/lax-three-context-20261018-r01/venv-r251
mkdir -m 700 "$OUT"
mkdir -m 700 "$OUT/tmp"
export TMPDIR="$OUT/tmp"
/opt/lax-three-context-20261018-r01/venv-r212/bin/python -m pip freeze | sed '/^hollywood-cli /d; /^lax-hollywood-connector /d' > "$OUT/dependencies.txt"
/opt/lax-three-context-20261018-r01/venv-r212/bin/python -m pip wheel --no-deps "$ROOT/hollywood" "$ROOT/lax/losangelex/connector" -w "$OUT/wheels" > "$OUT/wheel.log" 2>&1
python3 -m venv /opt/lax-three-context-20261018-r01/venv-r251
/opt/lax-three-context-20261018-r01/venv-r251/bin/python -m pip install -r "$OUT/dependencies.txt" "$OUT"/wheels/*.whl > "$OUT/install.log" 2>&1
/opt/lax-three-context-20261018-r01/venv-r251/bin/python -m pip check

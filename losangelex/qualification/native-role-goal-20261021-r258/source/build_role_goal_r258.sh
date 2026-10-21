set -eu
ROOT=/aosp/development/lax-three-context-20261018-r01
OUT="$ROOT/qualification/role-goal-build-r258"
test ! -e "$OUT"
test ! -e /opt/lax-three-context-20261018-r01/venv-r258
mkdir -m 700 "$OUT"
mkdir -m 700 "$OUT/tmp"
export TMPDIR="$OUT/tmp"
cp -a /opt/lax-three-context-20261018-r01/venv-r251 /opt/lax-three-context-20261018-r01/venv-r258
/opt/lax-three-context-20261018-r01/venv-r212/bin/python -m pip wheel --no-deps "$ROOT/lax/losangelex/connector" -w "$OUT/wheels" > "$OUT/wheel.log" 2>&1
/opt/lax-three-context-20261018-r01/venv-r258/bin/python -m pip install --no-deps "$OUT"/wheels/*.whl > "$OUT/install.log" 2>&1
/opt/lax-three-context-20261018-r01/venv-r258/bin/python -m pip check

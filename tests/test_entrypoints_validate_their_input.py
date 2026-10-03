"""The node entrypoints check their input by behaviour, not by spelling.

The WireGuard entrypoint (nodes/alice/entrypoint.sh) and the IPsec entrypoint
(nodes/strongswan/entrypoint.sh) both hand ARNIKA_PSK, PQC_ENABLED and
ARNIKA_INTERVAL to arnika. The guard this file replaces looked for the literal
text `${#ARNIKA_PSK}`, so it failed on the IPsec entrypoint's `wc -c`, which is
the correct way to count bytes there, and it would have passed a check that
counted characters. So this file cuts each check out of the script and runs it
under bash with a stubbed environment, in both entrypoints unless it says
otherwise:

  * ARNIKA_PSK: 31 ASCII bytes fail; 20 x U+00E9 (40 bytes, 20 characters)
    passes, run in a UTF-8 locale where `${#VAR}` counts characters, so a check
    that counts characters would fail it; the example env files' placeholder
    fails, although it is 37 bytes and passes arnika's own length check;
  * PQC_ENABLED: only "true" and "false" pass; "True" and an unset value fail.
    arnika reads every value other than "true" as off;
  * WireGuard entrypoint only, ARNIKA_INTERVAL: the start alignment parses it
    as a Go duration in whole hours, minutes and seconds, and fails on
    anything else;
  * WireGuard entrypoint only, the start alignment sleeps to a wall-clock
    multiple of the interval and runs once, before every arnika start, with
    nothing that waits in between. The pinned arnika counts its intervals per
    process from its own start, so two ends that start a second or more apart
    fail closed in some of the later one's BACKUP intervals ("Start alignment"
    in the WireGuard entrypoint gives the inference and the local figures);
  * the IPsec entrypoint does NOT align: its lane is the one the before/after
    PPK measurement compares, so it keeps the start behaviour it had at v0.1.0,
    and nothing before its arnika start sleeps or waits except what v0.1.0
    already did (see "No start alignment in this lane" there);
  * the IPsec entrypoint derives its bootstrap credentials from ARNIKA_PSK
    with HKDF-SHA256, and gets the right key for a PSK that repeats a 16-byte
    block. `od` without `-v` printed such a block as `*`, and openssl then
    stopped the node with "odd number of digits".
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest
from conftest import read_env_example

ROOT = Path(__file__).resolve().parents[1]
ALICE = ROOT / "nodes" / "alice" / "entrypoint.sh"
STRONGSWAN = ROOT / "nodes" / "strongswan" / "entrypoint.sh"
ENTRYPOINTS = [ALICE, STRONGSWAN]
IDS = [p.parent.name for p in ENTRYPOINTS]
# The entrypoints that align their arnika start: the WireGuard lane only.
ALIGNED = [ALICE]
ALIGNED_IDS = [p.parent.name for p in ALIGNED]
EXAMPLE_ENV = [p for p in (ROOT / ".env.example", ROOT / "deploy" / ".env.example") if p.is_file()]
MAIN_GO = ROOT / "submodules" / "arnika" / "main.go"

VALIDATE = "validate_arnika_input"
PARSE = "go_duration_seconds"
ALIGN = "align_arnika_start"
DERIVE = "derive_bootstrap_secret"
ARNIKA_BIN = "/usr/local/bin/arnika"

# arnika's floor (minArnikaPSKLen) and the entrypoints' copy of it.
MIN_PSK_BYTES = 32
E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"   # U+00E9, two bytes in UTF-8
# A PSK that passes every check, built here so that no PSK-shaped literal sits
# in the tree.
GOOD_PSK = "t" * (MIN_PSK_BYTES + 8)
# How far the alignment's boundary may sit from a whole multiple of the
# interval: the time bash takes between the harness reading the clock and the
# function reading it.
ALIGN_TOLERANCE_S = 0.05
# Locales in which bash's `${#VAR}` counts characters, first one present wins.
UTF8_LOCALES = ("C.UTF-8", "C.utf8", "en_US.UTF-8")
BASH_TIMEOUT_S = 30
DOCKER_TIMEOUT_S = 120
# The two info strings the IPsec entrypoint derives its bootstrap values with.
BOOTSTRAP_INFOS = ("pqcqkd bootstrap ike-psk", "pqcqkd bootstrap ppk")
# Where the IPsec lane's image comes from when this runs next to a built stack.
STRONGSWAN_IMAGE = os.environ.get("PQCQKD_STRONGSWAN_IMAGE", "pqcqkd/strongswan:local")
# The tag of the release whose IPsec start behaviour arm A of the before/after
# measurement runs, and the one wait its entrypoint did before starting arnika:
# the one-second poll for charon's VICI socket.
V010_TAG = "v0.1.0"
V010_WAITS_BEFORE_ARNIKA = ("sleep 1",)
# A command that waits or sleeps, at the start of a statement.
WAITING_COMMAND = re.compile(r"(?:^|[;&|(){}]|\bdo|\bthen|\belse)\s*(sleep|wait|read|timeout)\b")
GIT_TIMEOUT_S = 60


# --------------------------------------------------------------- helpers --

@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def shell_function(path: Path, name: str) -> str:
    """The definition of one top-level function, `name() {` to the `}` at column 0."""
    m = re.search(rf"^{name}\(\) \{{.*?^\}}", _text(path), re.M | re.S)
    assert m, f"{path.relative_to(ROOT)} no longer defines {name}()"
    return m.group(0)


def shell_constant(path: Path, name: str) -> str:
    """The one top-level `NAME=value` line."""
    found = re.findall(rf"^{name}=.*$", _text(path), re.M)
    assert len(found) == 1, f"{path.relative_to(ROOT)} assigns {name} {len(found)} times at top level"
    return found[0]


def code_lines(path: Path) -> list[str]:
    """The script's lines with comment-only lines blanked, numbering kept."""
    return ["" if ln.lstrip().startswith("#") else ln for ln in _text(path).splitlines()]


@cache
def utf8_locale() -> str:
    probe = E_ACUTE * 20
    for loc in UTF8_LOCALES:
        out = subprocess.run(["bash", "-c", 'printf %s "${#X}"'], capture_output=True, text=True,
                             env={"PATH": os.environ["PATH"], "LC_ALL": loc, "X": probe},
                             timeout=BASH_TIMEOUT_S)
        if out.stdout == str(len(probe)):
            return loc
    pytest.skip(f"no UTF-8 locale among {UTF8_LOCALES}: bash counts bytes in every locale here, "
                "so a check that counts characters would pass unnoticed")


def run_bash(script: str, env: dict[str, str | None], args: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """`script` under bash with the entrypoints' shell options and only `env`."""
    loc = utf8_locale()
    full = {"PATH": os.environ["PATH"], "LC_ALL": loc, "LANG": loc}
    full.update({k: v for k, v in env.items() if v is not None})
    return subprocess.run(["bash", "-c", "set -euo pipefail\n" + script, "bash", *args],
                          capture_output=True, text=True, env=full, timeout=BASH_TIMEOUT_S)


def _placeholder() -> str:
    found = {read_env_example(p).get("ARNIKA_PSK") for p in EXAMPLE_ENV} - {None}
    assert len(found) == 1, f"the example env files disagree on the ARNIKA_PSK placeholder: {found}"
    return found.pop()


# ------------------------------------------------------------ validation --

def _validation_block(path: Path) -> str:
    return "\n".join([shell_constant(path, "MIN_ARNIKA_PSK_BYTES"),
                      shell_constant(path, "ARNIKA_PSK_PLACEHOLDER"),
                      shell_function(path, VALIDATE)])


def _psk_cases() -> list[tuple[str, dict[str, str | None], str | None]]:
    """(label, environment, None for pass or the variable the failure must name)."""
    placeholder = _placeholder()
    return [
        ("32 ASCII bytes pass", {"ARNIKA_PSK": "a" * MIN_PSK_BYTES, "PQC_ENABLED": "true"}, None),
        ("31 ASCII bytes fail", {"ARNIKA_PSK": "a" * (MIN_PSK_BYTES - 1), "PQC_ENABLED": "true"}, "ARNIKA_PSK"),
        ("20 x U+00E9 is 40 bytes and passes",
         {"ARNIKA_PSK": E_ACUTE * 20, "PQC_ENABLED": "true"}, None),
        ("15 x U+00E9 is 30 bytes and fails",
         {"ARNIKA_PSK": E_ACUTE * 15, "PQC_ENABLED": "true"}, "ARNIKA_PSK"),
        ("the example placeholder fails", {"ARNIKA_PSK": placeholder, "PQC_ENABLED": "true"}, "placeholder"),
        ("ARNIKA_PSK unset fails", {"ARNIKA_PSK": None, "PQC_ENABLED": "true"}, "ARNIKA_PSK"),
        ("PQC_ENABLED=false passes", {"ARNIKA_PSK": GOOD_PSK, "PQC_ENABLED": "false"}, None),
        ("PQC_ENABLED=True fails", {"ARNIKA_PSK": GOOD_PSK, "PQC_ENABLED": "True"}, "PQC_ENABLED"),
        ("PQC_ENABLED=1 fails", {"ARNIKA_PSK": GOOD_PSK, "PQC_ENABLED": "1"}, "PQC_ENABLED"),
        ("PQC_ENABLED unset fails", {"ARNIKA_PSK": GOOD_PSK, "PQC_ENABLED": None}, "PQC_ENABLED"),
        ("PQC_ENABLED empty fails", {"ARNIKA_PSK": GOOD_PSK, "PQC_ENABLED": ""}, "PQC_ENABLED"),
    ]


PSK_CASES = _psk_cases()


def test_the_placeholder_the_entrypoints_refuse_is_the_one_the_examples_ship():
    placeholder = _placeholder()
    assert len(placeholder.encode()) >= MIN_PSK_BYTES, (
        "the placeholder is now shorter than arnika's floor, so the length check alone refuses it "
        "and the separate placeholder check could be simplified")
    for path in ENTRYPOINTS:
        assert shell_constant(path, "ARNIKA_PSK_PLACEHOLDER").split("=", 1)[1].strip("'\"") == placeholder, (
            f"{path.relative_to(ROOT)} refuses a different placeholder from the one the example env files ship")
        assert shell_constant(path, "MIN_ARNIKA_PSK_BYTES") == f"MIN_ARNIKA_PSK_BYTES={MIN_PSK_BYTES}"


@pytest.mark.parametrize("label,env,names", PSK_CASES, ids=[c[0] for c in PSK_CASES])
@pytest.mark.parametrize("path", ENTRYPOINTS, ids=IDS)
def test_the_validation_block_accepts_and_refuses_by_behaviour(path, label, env, names):
    out = run_bash(_validation_block(path) + f"\n{VALIDATE}\necho validated", env)
    if names is None:
        assert out.returncode == 0 and out.stdout.strip() == "validated", (
            f"{path.relative_to(ROOT)}: {label}, but it was refused (exit {out.returncode}): {out.stderr.strip()}")
    else:
        assert out.returncode != 0 and "validated" not in out.stdout, (
            f"{path.relative_to(ROOT)}: {label}, but it was accepted")
        assert names in out.stderr, (
            f"{path.relative_to(ROOT)}: {label}, but the message does not name {names}: {out.stderr.strip()}")


@pytest.mark.parametrize("path", ENTRYPOINTS, ids=IDS)
def test_the_validation_runs_before_arnika_is_handed_anything(path):
    """Defined is not enough: the script must call it, at top level, before the
    first arnika start and, in the IPsec entrypoint, before the bootstrap
    credentials are derived from ARNIKA_PSK."""
    lines = code_lines(path)
    calls = [i for i, ln in enumerate(lines) if ln.strip() == VALIDATE and not ln.startswith((" ", "\t"))]
    assert len(calls) == 1, f"{path.relative_to(ROOT)} calls {VALIDATE} {len(calls)} times at top level"
    uses = [i for i, ln in enumerate(lines) if ARNIKA_BIN in ln or re.search(rf"\$\({DERIVE}\b", ln)]
    assert uses, f"{path.relative_to(ROOT)} no longer starts arnika at {ARNIKA_BIN}"
    assert calls[0] < min(uses), (
        f"{path.relative_to(ROOT)} uses ARNIKA_PSK (line {min(uses) + 1}) before {VALIDATE} "
        f"(line {calls[0] + 1})")


# ------------------------------------------------------- start alignment --

def _parser_block(path: Path) -> str:
    return "\n".join([shell_constant(path, "SECONDS_PER_MINUTE"),
                      shell_constant(path, "SECONDS_PER_HOUR"),
                      shell_function(path, PARSE)])


INTERVALS_OK = [("30s", 30), ("2m", 120), ("1m30s", 90), ("1h", 3600), ("1h0m5s", 3605), ("08s", 8)]
INTERVALS_BAD = ["abc", "", "30", "500ms", "1.5s", "0s", "30S", "-30s", "30s ", "s"]


@pytest.mark.parametrize("value,seconds", INTERVALS_OK, ids=[v for v, _ in INTERVALS_OK])
@pytest.mark.parametrize("path", ALIGNED, ids=ALIGNED_IDS)
def test_the_interval_parser_reads_whole_go_durations(path, value, seconds):
    out = run_bash(_parser_block(path) + f'\n{PARSE} "$1"', {}, (value,))
    assert out.returncode == 0, f"{path.relative_to(ROOT)} refused {value!r}: {out.stderr.strip()}"
    assert out.stdout.strip() == str(seconds), f"{path.relative_to(ROOT)}: {value!r} -> {out.stdout.strip()!r}"


@pytest.mark.parametrize("value", INTERVALS_BAD, ids=[repr(v) for v in INTERVALS_BAD])
@pytest.mark.parametrize("path", ALIGNED, ids=ALIGNED_IDS)
def test_the_interval_parser_fails_loudly_on_anything_else(path, value):
    out = run_bash(_parser_block(path) + f'\n{PARSE} "$1"', {}, (value,))
    assert out.returncode != 0, (
        f"{path.relative_to(ROOT)} accepted ARNIKA_INTERVAL={value!r} as {out.stdout.strip()!r}; "
        "a boundary in whole seconds cannot honour it")
    assert "ARNIKA_INTERVAL" in out.stderr, f"{path.relative_to(ROOT)}: the message does not name ARNIKA_INTERVAL"


@pytest.mark.parametrize("path", ALIGNED, ids=ALIGNED_IDS)
def test_the_interval_is_parsed_before_anything_is_started(path):
    """A bad ARNIKA_INTERVAL has to stop the node before it touches an
    interface, not after the other daemons are up."""
    lines = code_lines(path)
    parsed = [i for i, ln in enumerate(lines)
              if re.fullmatch(rf'ARNIKA_INTERVAL_S="\$\({PARSE} "\$ARNIKA_INTERVAL"\)"', ln.strip())]
    assert len(parsed) == 1, f"{path.relative_to(ROOT)} does not parse ARNIKA_INTERVAL into ARNIKA_INTERVAL_S once"
    first_side_effect = min(i for i, ln in enumerate(lines)
                            if re.match(r"\s*(mkdir|create_wg_iface|\"\$\{CHARON_BIN\}\")", ln))
    assert parsed[0] < first_side_effect
    exported = [ln for ln in lines if re.match(r"\s*export INTERVAL=", ln)]
    assert exported and all("ARNIKA_INTERVAL" in ln for ln in exported), (
        f"{path.relative_to(ROOT)} hands arnika an INTERVAL other than the ARNIKA_INTERVAL it aligned to")


@pytest.mark.parametrize("interval", [30, 7])
@pytest.mark.parametrize("path", ALIGNED, ids=ALIGNED_IDS)
def test_the_alignment_sleeps_to_a_wall_clock_multiple_of_the_interval(path, interval):
    """`sleep` is stubbed to print its argument; the clock is read just before
    the call, so the target is that reading plus the sleep."""
    script = "\n".join([
        shell_constant(path, "MICROSECONDS_PER_SECOND"),
        shell_function(path, ALIGN),
        'sleep() { echo "SLEPT $1"; }',
        'echo "NOW ${EPOCHREALTIME/[^0-9]/}"',
        f'{ALIGN} "$1"',
    ])
    out = run_bash(script, {}, (str(interval),))
    assert out.returncode == 0, out.stderr
    now_us = int(re.search(r"^NOW (\d+)$", out.stdout, re.M).group(1))
    slept = float(re.search(r"^SLEPT ([0-9.]+)$", out.stdout, re.M).group(1))
    assert 0 < slept <= interval, f"slept {slept}s for a {interval}s interval"
    target = now_us / 1e6 + slept
    off = target % interval
    assert min(off, interval - off) < ALIGN_TOLERANCE_S, (
        f"{path.relative_to(ROOT)} wakes {off:.3f}s past a multiple of {interval}s")


def _arnika_starts(lines: list[str]) -> list[int]:
    return [i for i, ln in enumerate(lines) if re.search(rf"(^|\s){re.escape(ARNIKA_BIN)}(\s|$)", ln)]


@pytest.mark.parametrize("path", ALIGNED, ids=ALIGNED_IDS)
def test_the_alignment_runs_once_before_every_arnika_start(path):
    """One call, at top level, above every line that starts an arnika, and
    nothing between the two that sleeps or waits, so every instance a node
    runs starts at the same boundary."""
    lines = code_lines(path)
    starts = _arnika_starts(lines)
    assert starts, f"{path.relative_to(ROOT)} no longer starts {ARNIKA_BIN}"
    calls = [i for i, ln in enumerate(lines) if re.match(rf"{ALIGN} ", ln)]
    assert len(calls) == 1, f"{path.relative_to(ROOT)} calls {ALIGN} {len(calls)} times at top level"
    assert "ARNIKA_INTERVAL_S" in lines[calls[0]], "the alignment is not given the parsed interval"
    early = [i + 1 for i in starts if i < calls[0]]
    assert not early, f"{path.relative_to(ROOT)} starts arnika at line(s) {early}, before {ALIGN}"
    between = [(i + 1, lines[i].strip()) for i in range(calls[0] + 1, max(starts))
               if re.search(r"\b(sleep|wait|wait_for_\w+|seq|read)\b", lines[i])]
    assert not between, (
        f"{path.relative_to(ROOT)} waits between the alignment and an arnika start, which "
        f"moves that start off the boundary: {between}")


def _waits_before_arnika(text: str) -> list[str]:
    """Every line above the first arnika start that sleeps or waits, stripped."""
    lines = ["" if ln.lstrip().startswith("#") else ln for ln in text.splitlines()]
    starts = _arnika_starts(lines)
    assert starts, f"the IPsec entrypoint no longer starts {ARNIKA_BIN}"
    return [ln.strip() for ln in lines[:min(starts)] if WAITING_COMMAND.search(ln)]


def test_the_ipsec_entrypoint_does_not_align_its_arnika_start():
    """Arm A of the before/after measurement runs v0.1.0, whose IPsec
    entrypoint started arnika as soon as the connection was loaded. Arm B has
    to run the same entrypoint start behaviour, or a change in it would be
    measured as a difference between the pins. So no alignment code, and
    nothing before the arnika start that sleeps or waits beyond the VICI
    socket poll v0.1.0 already had. This does not hold the start offset
    between the two nodes equal: arm B drops the depends_on on the WireGuard
    nodes, so the offset is measured in each arm."""
    code = "\n".join(code_lines(STRONGSWAN))
    present = [name for name in (PARSE, ALIGN, "ARNIKA_INTERVAL_S", "EPOCHREALTIME") if name in code]
    assert not present, (
        f"nodes/strongswan/entrypoint.sh has start-alignment code again ({present}). The IPsec lane "
        "is the measured one and keeps the v0.1.0 start behaviour; align only the WireGuard lane.")
    waits = _waits_before_arnika(_text(STRONGSWAN))
    assert tuple(waits) == V010_WAITS_BEFORE_ARNIKA, (
        f"nodes/strongswan/entrypoint.sh sleeps or waits before starting arnika in {waits}, where "
        f"{V010_TAG} did only {list(V010_WAITS_BEFORE_ARNIKA)}; that changes the IPsec start "
        "behaviour, which both arms of the before/after measurement share")
    exported = [ln.strip() for ln in code_lines(STRONGSWAN) if re.match(r"\s*export INTERVAL=", ln)]
    assert exported == ['export INTERVAL="${ARNIKA_INTERVAL:?ARNIKA_INTERVAL must be set}"'], (
        f"nodes/strongswan/entrypoint.sh hands arnika its interval as {exported}, not ARNIKA_INTERVAL as is")


def test_the_v010_waits_this_file_allows_are_the_ones_v010_had():
    """V010_WAITS_BEFORE_ARNIKA, checked against the tagged file itself when
    the tag is in this checkout (a shallow CI checkout has no tags)."""
    out = subprocess.run(["git", "show", f"{V010_TAG}:nodes/strongswan/entrypoint.sh"], cwd=ROOT,
                         capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    if out.returncode != 0:
        pytest.skip(f"{V010_TAG} is not in this checkout: {out.stderr.strip()}")
    assert tuple(_waits_before_arnika(out.stdout)) == V010_WAITS_BEFORE_ARNIKA


# `path:first[-last]` citations of the pinned main.go in the entrypoints, and
# what each cited range must contain. A pin bump that moves the code fails
# here, so the comments that explain the alignment cannot go stale silently.
MAIN_GO_CITATIONS = {
    (327, 333): ("time.NewTicker(interval)", "var intervalCounter uint64", "cfg.IsPrimary(intervalCounter)"),
    (349, 349): ("now.Truncate(time.Second).Add(time.Second)",),
    (409, 418): ("peerSentKeyID.Swap(false)", "if backup && !sawKeyID", '"no key_id from the peer"',
                 "setPSK(keyWriter, pqc, nil, cfg, backupLog)"),
}


def test_the_main_go_lines_the_entrypoints_cite_still_say_that():
    if not MAIN_GO.is_file():
        pytest.skip("arnika submodule not checked out")
    main = MAIN_GO.read_text(encoding="utf-8").splitlines()
    cited = set()
    for path in ENTRYPOINTS:
        for m in re.finditer(r"main\.go:(\d+)(?:-(\d+))?", _text(path)):
            cited.add((int(m.group(1)), int(m.group(2) or m.group(1))))
    assert cited, "the entrypoints no longer cite main.go; drop this check or restore the citations"
    unknown = cited - set(MAIN_GO_CITATIONS)
    assert not unknown, f"cited main.go ranges this test does not know what to expect in: {sorted(unknown)}"
    for first, last in sorted(cited):
        span = "\n".join(main[first - 1:last])
        missing = [s for s in MAIN_GO_CITATIONS[(first, last)] if s not in span]
        assert not missing, (
            f"main.go:{first}-{last} no longer contains {missing}. The arnika pin moved: re-read the "
            "interval loop and update the 'Start alignment' comment in the WireGuard entrypoint and "
            "the 'No start alignment in this lane' comment in the IPsec entrypoint.")


# ------------------------------------------------ bootstrap derivation --

def hkdf_sha256(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 with no salt, which the RFC defines as HashLen zero bytes."""
    prk = hmac.new(b"\0" * hashlib.sha256().digest_size, ikm, hashlib.sha256).digest()
    okm, block, counter = b"", b"", 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


# Both repeat a 16-byte block, which is what od without -v folded into `*`.
REPEATING_PSKS = [("16 x U+00E9", E_ACUTE * 16), ("three identical 16-byte ASCII blocks", "0123456789abcdef" * 3)]


def _derive_script() -> str:
    return shell_function(STRONGSWAN, DERIVE) + f'\n{DERIVE} "$1"\ntest ! -e "$ARNIKA_PSK_TMP"'


def test_the_psk_file_path_is_a_named_constant():
    assert shell_constant(STRONGSWAN, "ARNIKA_PSK_TMP") == "ARNIKA_PSK_TMP=/run/arnika-psk.tmp"


@pytest.mark.parametrize("info", BOOTSTRAP_INFOS)
@pytest.mark.parametrize("label,psk", REPEATING_PSKS, ids=[c[0] for c in REPEATING_PSKS])
def test_a_repeating_psk_derives_the_right_bootstrap_value_on_the_host(label, psk, info, tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("no openssl on this host")
    if subprocess.run([openssl, "kdf", "-help"], capture_output=True, timeout=BASH_TIMEOUT_S).returncode != 0:
        pytest.skip("this host's openssl has no `kdf` command (OpenSSL 3 is needed)")
    assert len(psk.encode()) >= MIN_PSK_BYTES
    out = run_bash(_derive_script(), {"ARNIKA_PSK": psk, "ARNIKA_PSK_TMP": str(tmp_path / "psk")}, (info,))
    assert out.returncode == 0, f"{label}: the derivation failed: {out.stderr.strip()}"
    assert out.stdout == hkdf_sha256(psk.encode(), info.encode()).hex(), (
        f"{label}: the derivation returned a value other than HKDF-SHA256(ARNIKA_PSK, info={info!r})")


def test_a_repeating_psk_gets_through_the_derivation_in_the_image():
    """The same, with the image's own od and openssl, when the image is built."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", STRONGSWAN_IMAGE], capture_output=True,
                      timeout=DOCKER_TIMEOUT_S).returncode != 0:
        pytest.skip(f"{STRONGSWAN_IMAGE} is not built here; set PQCQKD_STRONGSWAN_IMAGE to another tag")
    label, psk = REPEATING_PSKS[0]
    info = BOOTSTRAP_INFOS[1]
    script = "set -euo pipefail\n" + _derive_script()
    out = subprocess.run(
        [docker, "run", "--rm", "-e", "ARNIKA_PSK", "-e", "ARNIKA_PSK_TMP=/tmp/psk",
         "--entrypoint", "bash", STRONGSWAN_IMAGE, "-c", script, "bash", info],
        capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S,
        env={**os.environ, "ARNIKA_PSK": psk})
    assert out.returncode == 0, f"{label} in {STRONGSWAN_IMAGE}: {out.stderr.strip()}"
    assert out.stdout == hkdf_sha256(psk.encode(), info.encode()).hex()

"""Cross-implementation check: the Python and TypeScript key-rate models agree.

The closed-form decoy-state model exists three times in this repository -- the
backend reference (`_skr.py`), the browser port (`keyrate.ts`) and the offline
table builder. The browser port is what the public demo actually shows, so a
divergence between it and the backend would mean the demo displays numbers the
project cannot reproduce.

This drives the TypeScript through node and compares it against the Python over
a parameter sweep. It is skipped when node is unavailable.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest
from conftest import REPO_ROOT, load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
_skr = importlib.import_module("bb84_kme_app.backends._skr")

KEYRATE_TS = REPO_ROOT / "services" / "webui-frontend" / "src" / "lib" / "sim" / "keyrate.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not KEYRATE_TS.exists(),
    reason="node or keyrate.ts unavailable",
)

# (eta_total, Y0, e_d, mu, nu1, nu2, f_EC)
CASES = [
    (0.045, 1.7e-6, 0.033, 0.48, 0.05, 0.0, 1.22),   # GYS at L = 0
    (0.020, 1.0e-6, 0.015, 0.50, 0.10, 0.0, 1.16),   # repo defaults
    (0.002, 1.0e-5, 0.030, 0.60, 0.10, 0.0, 1.20),   # long link
    (0.200, 1.0e-7, 0.005, 0.40, 0.08, 0.0, 1.10),   # short, low-noise link
    # Dark channel: no transmittance, no dark counts, so Q_mu = Y0 + 1 -
    # exp(0) = 0 and the QBER is undefined. Both ports guard this with
    # `if q <= 0: return 0.5` -- maximally uncertain rather than a division by
    # zero -- and until this fixture existed neither guard was ever executed by
    # the parity test. Every other case has Y0 > 0 and eta > 0, which makes
    # Q_mu strictly positive.
    (0.000, 0.0,    0.015, 0.50, 0.10, 0.0, 1.16),   # dark channel, q == 0
    # nu2 > 0. Every case above pinned nu2 = 0.0, and so did every other test
    # in the suite -- which is why 301 of them passed over a Y1 denominator
    # that was the nu2 = 0 special case of Ma Eq. (18) while the numerator kept
    # its (nu1^2 - nu2^2) term. Correct at the default, wrong above it.
    #
    # Not a hypothetical input: config/qkd_params.yaml gives the optimiser the
    # grid nu2: [0.00, 0.01], and /physics exposes nu2 as an editable field.
    (0.020, 1.0e-6, 0.015, 0.50, 0.10, 0.01, 1.16),  # optimiser grid point
    (0.020, 1.0e-6, 0.015, 0.50, 0.10, 0.05, 1.16),  # nu1 + nu2 still < mu
    (0.045, 1.7e-6, 0.033, 0.48, 0.05, 0.02, 1.22),  # GYS with a second decoy
]


def _run_ts(cases) -> list[dict]:
    """Transpile keyrate.ts with the real tsc and evaluate it in node.

    Using the actual compiler rather than stripping types with string
    substitution: the module uses inline object type annotations, which no
    naive shim survives, and a shim that quietly mis-parses would compare the
    wrong thing.
    """
    tsc = REPO_ROOT / "services" / "webui-frontend" / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.exists():
        pytest.skip("typescript not installed (run npm ci in services/webui-frontend)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shutil.copy(KEYRATE_TS, tmp_path / "keyrate.ts")
        build = subprocess.run(
            ["node", str(tsc), "keyrate.ts", "--target", "ES2022",
             "--module", "ESNext", "--outDir", str(tmp_path)],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
        )
        assert build.returncode == 0, f"tsc failed:\n{build.stdout}{build.stderr}"

        driver = tmp_path / "driver.mjs"
        driver.write_text(textwrap.dedent(f"""
            import {{ gainQmu, qberEmu, asymptoticSkrPerPulse }} from "./keyrate.js";
            const cases = {json.dumps(cases)};
            const out = cases.map(([etaTotal, Y0, eD, mu, nu1, nu2, fEC]) => ({{
              gain: gainQmu(Y0, etaTotal, mu),
              qber: qberEmu(Y0, etaTotal, eD, mu),
              rate: asymptoticSkrPerPulse({{ Y0, etaTotal, eD, mu, nu1, nu2, fEC }}),
            }}));
            console.log(JSON.stringify(out));
        """))
        res = subprocess.run(
            ["node", str(driver)], cwd=tmp_path,
            capture_output=True, text=True, timeout=30,
        )
        # Deliberately a failure, not a skip: if this stops evaluating, the
        # comparison silently stops happening and the ports can drift again.
        assert res.returncode == 0, f"could not run keyrate.js:\n{res.stderr}"
        return json.loads(res.stdout)


def test_typescript_port_matches_python_reference():
    ts = _run_ts(CASES)
    for (eta, Y0, e_d, mu, nu1, nu2, f_EC), got in zip(CASES, ts):
        py_gain = _skr.gain_Qmu(Y0, eta, mu)
        py_qber = _skr.qber_Emu(Y0, eta, e_d, mu)
        py_rate = _skr.asymptotic_skr_per_pulse(
            Y0=Y0, eta_total=eta, e_d=e_d, mu=mu, nu1=nu1, nu2=nu2, f_EC=f_EC,
        )
        label = f"eta={eta} Y0={Y0} e_d={e_d} mu={mu}"
        assert got["gain"] == pytest.approx(py_gain, rel=1e-12), f"Q_mu drift @ {label}"
        assert got["qber"] == pytest.approx(py_qber, rel=1e-12), f"E_mu drift @ {label}"
        assert got["rate"] == pytest.approx(py_rate, rel=1e-9), f"rate drift @ {label}"

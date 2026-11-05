# Decoy-state BB84 key rate

The model every simulation page and backend in this project rests on, written
out once. It previously existed only as code in three places, with no
derivation and nothing pinning it to a published value.

Implementations:

| Where | File |
|---|---|
| Backend reference | [`services/bb84-kme/app/backends/_skr.py`](../services/bb84-kme/app/backends/_skr.py) |
| Browser port | [`services/webui-frontend/src/lib/sim/keyrate.ts`](../services/webui-frontend/src/lib/sim/keyrate.ts) |
| Offline table builder | [`tools/precompute_keyrate_table_fallback.py`](../tools/precompute_keyrate_table_fallback.py) |

`tests/test_keyrate_golden_vector.py` pins the model to the published values in
§6, and `tests/test_keyrate_ports_agree.py` checks the browser port still
matches the backend. Both run in CI.

**Math delimiters.** Inline math in this repository's Markdown is written
``$`x`$``, never bare `$x$`. GitHub renders both, but the bare form leaves
LaTeX exposed to the Markdown parser first: an expression containing two
underscores -- ``$\varepsilon_{\text{sec}} = 21\varepsilon$`` is one of many
here -- can be consumed as emphasis before the math renderer ever sees it. The
backtick form is a code span, so it cannot be. This file mixed the two (64
bare against 23 backticked, and `references.md` used both in a single table
row) until 2026-08-29. `tests/test_math_delimiters_are_uniform.py` keeps it
uniform. Display math stays in ```` ```math ```` fences and is unaffected.

---

## 1. Notation

| Symbol | Meaning | Config key |
|---|---|---|
| $`\alpha`$ | Fibre attenuation (dB/km) | `physical.fiber_attenuation_db_per_km` |
| $`L`$ | Link length (km) | `physical.link_length_km` |
| $`\eta_d`$ | Detector efficiency | `physical.detector_efficiency` |
| $`\eta`$ | Total transmittance | derived |
| $`Y_0`$ | Dark-count yield (per pulse) | derived from `physical.dark_count_rate_hz` |
| $`e_d`$ | Detector misalignment error | `physical.misalignment_error_ed` |
| $`e_0`$ | Error rate of background counts, $`=\tfrac12`$ | fixed by theory |
| $`\mu`$ | Signal intensity (mean photon number) | `source.intensity_signal_mu` |
| $`\nu_1,\nu_2`$ | Decoy intensities | `source.intensity_decoy_1_nu1`, `..._2_nu2` |
| $`f_{\mathrm{EC}}`$ | Error-correction efficiency | `protocol.ec_efficiency_f` |
| $`q`$ | Sifting factor in the ASYMPTOTIC rate, $`=\tfrac12`$ for symmetric BB84 | hard-coded `0.5` |
| $`q_x`$ | Probability of choosing the KEY basis, in the finite-key analysis. **Not the same quantity as $`q`$** -- the sifted fraction is $`q_x^2`$. Both readings coincide at the shipped `0.5`, which is why one field served both; they differ by 106x at 0.9. | `source.basis_bias_pz` |
| $`p_{\mu}, p_{\nu_1}, p_{\nu_2}`$ | Intensity-choice probabilities. Load-bearing: $`\tau_n = \sum_k p_k e^{-k} k^n / n!`$ and the Hoeffding deviation is divided by $`p_k`$. Must sum to 1. | `source.prob_signal_mu`, `source.prob_decoy_1_nu1`, `source.prob_decoy_2_nu2` |
| $`\varepsilon_{\text{sec}}`$ | Secrecy parameter. Composed from seven terms; all equal gives $`\varepsilon_{\text{sec}} = 21\varepsilon`$. | `protocol.security_epsilon` |
| $`\varepsilon_{\text{cor}}`$ | Correctness parameter -- the error-verification hash collision probability. A distinct quantity, previously absent entirely. | `protocol.correctness_epsilon` |

---

## 2. Channel model

Transmittance combines fibre loss with detector efficiency (Ma *et al.* 2005, Eq. 5):

```math
\eta \;=\; 10^{-\alpha L / 10}\,\eta_d
```

The dark-count yield is the dark-count rate normalised by the pulse rate:

```math
Y_0 \;=\; \frac{R_{\mathrm{dark}}}{R_{\mathrm{pulse}}}
```

For a weak coherent source, the **gain** — the probability that a pulse of
intensity $`\mu`$ produces a detection — is (Eq. 10):

```math
Q_\mu \;=\; Y_0 + 1 - e^{-\eta\mu}
```

and the **quantum bit error rate** is (Eq. 11):

```math
E_\mu \;=\; \frac{e_0 Y_0 + e_d\left(1 - e^{-\eta\mu}\right)}{Q_\mu}
\qquad e_0 = \tfrac12
```

Background counts are random, hence $`e_0 = 1/2`$: half of them land in the wrong
detector.

> **Note on the approximation.** These use the standard $`Y_i \simeq Y_0 + \eta_i`$
> with $`\eta_i = 1-(1-\eta)^i`$. Carrying the exact $`Y_i = Y_0 + \eta_i - Y_0\eta_i`$
> through the sum gives $`Q_\mu^{\text{exact}} = 1-(1-Y_0)e^{-\eta\mu}`$, which
> differs by $`\mathcal{O}(Y_0)`$ — negligible for $`Y_0 \lesssim 10^{-5}`$, but the
> reason two code paths should not be compared for exact equality.

---

## 3. Asymptotic secret-key rate (GLLP)

With the single-photon contribution separated out
(Gottesman–Lo–Lütkenhaus–Preskill; Lo–Ma–Chen 2005):

```math
R \;\geq\; q\left\{-Q_\mu f_{\mathrm{EC}}\,h_2(E_\mu) \;+\; Q_1\left[1 - h_2(e_1)\right]\right\}
```

where $`h_2`$ is the binary entropy

```math
h_2(x) \;=\; -x\log_2 x - (1-x)\log_2(1-x)
```

Reading the two terms: the first is what error correction *costs* — it leaks
$`f_{\mathrm{EC}}h_2(E_\mu)`$ bits per sifted bit. The second is what the
single-photon pulses *earn*, after privacy amplification removes $`h_2(e_1)`$ bits
to account for what an eavesdropper could know. Multi-photon pulses contribute
nothing: they are assumed fully compromised (the photon-number-splitting attack).

---

## 4. Decoy-state estimation

$`Q_1`$ and $`e_1`$ are not directly observable. Decoy states bound them by
transmitting extra intensities $`\nu_1 > \nu_2 \geq 0`$ and comparing the
resulting gains.

With $`0 \leq \nu_2 < \nu_1`$ and $`\nu_1 + \nu_2 < \mu`$ (Ma et al. 2005,
Eq. (13)), the single-photon yield is bounded below by the general two-decoy
form, Eq. (18):

```math
Y_1^{L} \;=\; \frac{\mu}{\mu\nu_1 - \mu\nu_2 - \nu_1^{2} + \nu_2^{2}}
\left(Q_{\nu_1}e^{\nu_1} - Q_{\nu_2}e^{\nu_2}
- \frac{\nu_1^{2}-\nu_2^{2}}{\mu^{2}}\left(Q_\mu e^{\mu} - Y_0\right)\right)
```

and the single-photon error rate above by Eq. (22):

```math
e_1^{U} \;=\; \frac{E_{\nu_1}Q_{\nu_1}e^{\nu_1} - E_{\nu_2}Q_{\nu_2}e^{\nu_2}}{(\nu_1 - \nu_2)\,Y_1^{L}}
```

The single-photon gain follows from $`Y_1^L`$:

```math
Q_1 \;=\; \mu e^{-\mu} Y_1^{L}
```

At $`\nu_2 = 0`$ (the shipped default) the second decoy is the vacuum,
$`Q_{\nu_2} = Y_0`$ and $`E_{\nu_2} = e_0 = \tfrac12`$, and $`Y_1^L`$ and
$`e_1^U`$ reduce to the vacuum-plus-weak forms, with denominator
$`\mu\nu_1 - \nu_1^2`$ and
$`e_1^U = (E_{\nu_1}Q_{\nu_1}e^{\nu_1} - e_0 Y_0)/(Y_1^L\nu_1)`$. This
section showed only those reduced forms until 2026-09-25, while `_skr.py` and
`keyrate.ts` implement the general ones; the code is what
`tests/test_keyrate_ports_agree.py` checks, including cases with
$`\nu_2 > 0`$.

**In these asymptotic expressions $`Y_0`$ is the configured dark-count yield,
not an estimate:** $`Y_0 = \text{dark\_count\_rate\_hz} / \text{pulse\_rate\_hz}`$.
A real protocol bounds it from the vacuum decoy ($`Y_0^L`$). This asymptotic
rate is the one `/physics` and `/verify` display (checklist row 4.7.3). The
finite-key rate of section 5 -- the rate the KME backends and `/protocol-lab`
use -- does bound the vacuum contribution from the decoy counts ($`s_{X,0}`$);
what it inherits instead is the caveat stated there, that those counts are
expected under the channel model rather than observed. The two are different
numbers, and at the same parameters the finite-key one is lower.

Both bounds are clamped to physical ranges ($`Y_1^L \geq 0`$,
$`0 \leq e_1^U \leq \tfrac12`$); the rate is clamped at $`0`$, since a negative
result means no secret key can be distilled.

In the limit of infinitely many decoy states the bounds become exact:

```math
Y_1 = Y_0 + \eta, \qquad e_1 = \frac{e_0 Y_0 + e_d\eta}{Y_1}
```

This is what §6 uses, so the rate expression is tested independently of the
estimator.

---

## 5. Finite-key correction

Real runs are finite. The implementation is Lim, Curty, Walenta, Xu, Zbinden,
*Phys. Rev. A* **89**, 022307 (2014), [arXiv:1311.7129](https://arxiv.org/abs/1311.7129),
main text Eqs. (1)-(5) and supplementary Eqs. (1)-(14). It produces a key
**length in bits**, not a rate:

```math
\ell \;=\; \left\lfloor s_{X,0} + s_{X,1}\left[1 - h(\phi_X)\right] - \text{leak}_{\text{EC}}
        - 6\log_2\frac{21}{\varepsilon_{\text{sec}}} - \log_2\frac{2}{\varepsilon_{\text{cor}}} \right\rfloor
```

and the rate is $`R = \ell / N`$ with $`N`$ the **pulses Alice sent** -- all
bases, all intensities, detected or not (`protocol.block_size_N`). Note $`N`$
appears in *no bound*: the statistics are driven by the detection counts
$`n_X, n_Z, m_Z`$, which are channel-dependent.

The single-photon and vacuum counts $`s_{X,0}, s_{X,1}`$ come from the decoy
inversion with Hoeffding deviations *inside* it
($`\delta(n,\varepsilon) = \sqrt{(n/2)\ln(1/\varepsilon)}`$, natural log), and
$`\phi_X`$ adds a random-sampling-without-replacement term (Fung-Ma-Chau).
Every $`\varepsilon`$ is $`\varepsilon_{\text{sec}}/21`$, which is where the 21
and the coefficient 6 above come from.

### What this replaced, and why

This section previously typeset

```math
R_{\text{finite}} = \max\left(0,\; R - \sqrt{2/N}\,\sqrt{\log_2(2/\varepsilon)}\right)
```

credited to a paper that contains no such expression. Beyond the citation it
was wrong three further ways: it is $`2.402\times`$ a two-sided Hoeffding
deviation with $`\log_2`$ where $`\ln`$ belongs; being channel-independent it
never entered the decoy inversion, where near-cancelling differences over small
denominators amplify the deviation by one to two orders of magnitude -- the
dominant finite-size effect in decoy BB84; and subtracting a constant from a
rate bounds nothing, since a rate is not an empirical mean of $`N`$ bounded
i.i.d. variables.

> **Limitation, stated plainly.** The counts fed to these estimators are
> **expected** values from the channel model, not observed ones. Lim's theorem
> is conditioned on the data of a single run: *given* the observed
> $`(n_{X,k}, m_{Z,k})`$, a key of length $`\ell`$ is
> $`\varepsilon_{\text{sec}}`$-secret. Substituting expectations yields
> $`\ell(\mathbb{E}[\text{data}])`$, which is neither $`\mathbb{E}[\ell]`$ nor
> a bound for any particular run -- a real run lands below it about half the
> time. This is the standard simulation convention (Lim's own Fig. 1 does it),
> but read the output as an **expected key length under a modelled channel**,
> never as an achieved one. The $`\varepsilon_{\text{sec}}`$ guarantee does not
> attach to a simulated number. Hoeffding also assumes independent trials,
> while `dead_time_s` and `after_pulse_prob` in the shipped config correlate
> consecutive ones and this channel model ignores both.

---

## 6. Golden vector

The GYS parameter set at $`L=0`$, worked through Ma *et al.* (2005). CI asserts
the implementation reproduces every line.

| Quantity | Value |
|---|---|
| $`\eta`$ | $`0.045`$ |
| $`Y_0`$ | $`1.7\times10^{-6}`$ |
| $`e_d`$ | $`0.033`$ |
| $`\mu`$ | $`0.48`$ |
| $`f_{\mathrm{EC}}`$ | $`1.22`$ |
| $`Q_\mu`$ | $`2.13701\times10^{-2}`$ |
| $`E_\mu`$ | $`3.3037\times10^{-2}`$ |
| $`Q_1`$ | $`1.33670\times10^{-2}`$ |
| $`e_1`$ | $`3.3017\times10^{-2}`$ |
| **$`R`$** | $`\mathbf{2.555\times10^{-3}}`$ bits/pulse |

At a 2 MHz repetition rate that is $`\approx 5.1`$ kbit/s.

**If an implementation does not reproduce $`R = 2.555\times10^{-3}`$ here, the
error is in the asymptotic core, not the decoy estimator** — §6 bypasses the
estimator entirely by using the infinite-decoy values.

---

## 7. What this model does not include

Being explicit, since the WebUI presents these numbers as physics:

- **Afterpulsing** is configured (`physical.after_pulse_prob`) but only enters
  through one backend's noise term, not the closed-form rate.
- **Temperature drift, chromatic dispersion, and wavelength-dependent detector
  efficiency** are not modelled at all.
- **Error correction is not performed.** `reconciliation.py` hashes Alice's bits
  and applies a heuristic entropy margin; it does not run Cascade or LDPC, and
  no real leakage is measured. $`f_{\mathrm{EC}}`$ is an assumed constant.
- **Privacy amplification** uses a Toeplitz hash, but the admission test is a
  fixed margin rather than a leftover-hash-lemma bound.
- **Coherent attacks** are covered by the GLLP bound asymptotically. The
  finite-key half now DOES carry composable accounting -- Lim et al. track
  $`\varepsilon_{\text{sec}}`$ and $`\varepsilon_{\text{cor}}`$ separately and
  the key length subtracts both -- so the blanket "there is no composable
  security accounting" that stood here is no longer true. What remains is that
  the counts are expected rather than observed (section 5), which is a
  different limitation and does not make the accounting absent.

---

## 8. Could an existing OSS package do this instead?

Asked because "we wrote our own" is a claim that needs defending, and because
this project's own history says it should be: the finite-key term shipped here
until 2026-08-28 was wrong four ways, and the asymptotic bound had two
estimator defects. Code that does not exist cannot be wrong; code someone else
maintains is wrong less often.

Surveyed 2026-08-28. Licence and last-push verified through the GitHub API, not
from memory.

### Already in use

`tno-qkd-key-rate` (TNO, **Apache-2.0**, v2.0.4) is the independent cross-check
on `/verify`. It is a genuinely separate implementation, which is what makes
the comparison worth anything -- see section 5 and the `verdict` field.

### Not in use, and worth knowing about

| Package | What it computes | Licence | Last push |
|---|---|---|---|
| [ConicQKD.jl](https://github.com/araujoms/ConicQKD.jl) | Finite-size rates from Renyi entropies via non-symmetric conic optimisation | MIT | 2026-08-24 |
| [Renyi-security-framework](https://github.com/Optical-Quantum-Communication-Theory/Renyi-security-framework) | Decoy BB84, 1- and 2-decoy, against **coherent** attacks | MIT | 2026-08-09 |
| [1-decoy BB84 key-rate simulation](https://github.com/JeromeWiesemann/Quantum-key-distribution-secure-key-rate-simulation-1-decoy-BB84) | Reference implementation for Wiesemann et al., arXiv:2405.16578 | MIT | 2026-01-20 |
| [LDPC4QKD](https://github.com/XQP-Munich/LDPC4QKD) | Rate-adaptive LDPC reconciliation -- would **measure** $`f_{\mathrm{EC}}`$ instead of assuming it | GPL-3.0 | 2026-08-22 |

Several more sit in the same Waterloo group as `openQKDsecurity` (numerical
security proofs, entropy-accumulation finite-size analysis), all MIT, all
MATLAB.

### Why none of them replaced the code here

**Language.** Of the four above, two are Julia or MATLAB, as are the
Waterloo packages, and LDPC4QKD is C++. This is a Python service
with a TypeScript port that runs the same model in the browser, and
`tests/test_keyrate_ports_agree.py` holds the two within a relative $`10^{-9}`$. Adding a third
runtime to a container that currently needs none would cost more than the
~200 lines it would remove.

**The one that is Python** is a *1-decoy* reference implementation. This
project ships three intensities, so the 2-decoy form is the structural match --
which is why Lim et al. was implemented from the paper rather than adapted from
that code, and then cross-checked against an independent transcription to eight
significant figures.

**Not a licence problem.** All four are commercially usable; LDPC4QKD's GPL-3.0
is copyleft but this repository already documents how it handles GPL components
(see `THIRD_PARTY_NOTICES.md`), so that is a distribution question, not a bar.

### The one that would change a real claim

`LDPC4QKD` is the interesting entry. $`f_{\mathrm{EC}}`$ (`protocol.ec_efficiency_f`) is
currently an **assumed constant** -- `docs/roadmap.md` lists "no real error correction" as a known gap,
and the leakage is never measured. A rate-adaptive LDPC reconciliation would
turn $`f_{\mathrm{EC}}`$ from an assumption into a measurement, which is the kind of
change that makes a claim stronger rather than merely different. It is
recorded here rather than scheduled: it is a substantial piece of work, and
GPL-3.0 in the key path is a decision for the maintainer.

Excluded after checking: **NetSquid** (non-commercial licence), **QuNetSim**
(MIT but no decoy maths and no release since 2024-04), and two topical
repositories in the same area that carry **no LICENSE file at all**, which
means all rights reserved rather than permissive.

---

## 9. Other protocol families: the curves on `/qkd-protocols`

`/qkd-protocols` draws the key rate of three protocols against fibre length, in
the browser. It is a teaching model. No backend computes these rates, no key comes
from them, and nothing in the running stack reads them; the rate that does stand
behind this stack's keys is the decoy-state BB84 model above. The decision record
is in [`roadmap.md`](roadmap.md).

| Where | File |
|---|---|
| Reference, standard library only | [`tools/protocol_rates.py`](../tools/protocol_rates.py) |
| Browser port | [`services/webui-frontend/src/lib/sim/protocolRates.ts`](../services/webui-frontend/src/lib/sim/protocolRates.ts) |
| Golden vectors, written by the reference | [`services/webui-frontend/src/lib/sim/protocolRatesGolden.json`](../services/webui-frontend/src/lib/sim/protocolRatesGolden.json) |

`tests/test_protocol_rates.py` holds the reference to the sources, and
`protocolRates.test.ts` holds the browser port to the golden vectors. Both run in CI.

### 9.1 What the three share

Every rate here is **asymptotic**, with infinitely many decoy states where there
are decoys. The basis factor is $`q = 1`$, the limit of very biased bases, so the
numbers are bits per pulse (per pair of pulses for MDI-QKD) sent in the key basis.
With balanced bases, BB84 and BBM92 halve, and MDI-QKD quarters if only the Z basis
gives key.

All detectors are threshold detectors with one efficiency $`\eta_d`$ and one
background probability $`p_d`$, per detector and per pulse. Two detectors at one end
give the $`Y_0`$ of sections 2 and 4:

```math
Y_0 = 1 - (1 - p_d)^2 \approx 2 p_d
```

Fibre of length $`L`$ and loss $`\alpha`$ dB/km, with a relay or source at a share
$`s`$ of the way from Alice, gives the two arms:

```math
\eta_A = \eta_d\, 10^{-\alpha s L / 10}, \qquad
\eta_B = \eta_d\, 10^{-\alpha (1 - s) L / 10}
```

The parameters on the page start at those behind Lo, Curty and Qi (2012), Fig. 2:
$`\alpha = 0.2`$ dB/km, $`\eta_d = 14.5\%`$, $`e_d = 1.5\%`$, $`f = 1.16`$, with
$`p_d = 3.0 \times 10^{-6}`$ per detector (Ma and Razavi, Table I, half the
two-detector $`6.02 \times 10^{-6}`$ of the experiment they come from).

### 9.2 MDI-QKD

Alice and Bob each send phase-randomised weak coherent pulses to an untrusted relay,
which announces a partial Bell-state measurement. The formulas are Ma and Razavi
(2012), Appendixes A and B, for the original polarisation scheme of Lo, Curty and Qi.
The rate, their Eq. (B27):

```math
R \;\geq\; Q_{11}\left[1 - h_2(e_{11})\right] - Q_{\mathrm{rect}}\, f\, h_2(E_{\mathrm{rect}})
```

The single-photon terms, Eqs. (B1), (A9) and (A11), with $`e_0 = 1/2`$:

```math
Q_{11} = \mu_a \mu_b e^{-\mu_a - \mu_b} Y_{11}
```

```math
Y_{11} = (1 - p_d)^2 \left[\frac{\eta_A \eta_B}{2} + (2\eta_A + 2\eta_B - 3\eta_A\eta_B)\, p_d + 4(1 - \eta_A)(1 - \eta_B)\, p_d^2\right]
```

```math
e_{11} Y_{11} = e_0 Y_{11} - (e_0 - e_d)(1 - p_d)^2 \frac{\eta_A \eta_B}{2}
```

The overall gain and error in the key basis, Eqs. (B28)-(B31), where $`I_0`$ is the
modified Bessel function, $`\mu' = \eta_A\mu_a + \eta_B\mu_b`$ and
$`x = \sqrt{\eta_A\mu_a\,\eta_B\mu_b}/2`$:

```math
Q_C = 2(1 - p_d)^2 e^{-\mu'/2} \left[1 - (1 - p_d) e^{-\eta_A\mu_a/2}\right]\left[1 - (1 - p_d) e^{-\eta_B\mu_b/2}\right]
```

```math
Q_E = 2 p_d (1 - p_d)^2 e^{-\mu'/2} \left[I_0(2x) - (1 - p_d) e^{-\mu'/2}\right]
```

```math
Q_{\mathrm{rect}} = Q_C + Q_E, \qquad E_{\mathrm{rect}} Q_{\mathrm{rect}} = e_d Q_C + (1 - e_d) Q_E
```

$`Q_C`$ is the case of different modes, which gives correct anticorrelated bits, and
$`Q_E`$ the case of one mode, which can only produce the event with a background
count. The intensity is chosen at each length; with the arms unequal, $`\mu_b`$ is
set so that $`\eta_A\mu_a = \eta_B\mu_b`$, which minimises the intrinsic error (Ma and
Razavi, after Eq. (B14)) and is not a joint optimum of the two intensities.

### 9.3 BBM92 from a thermal source

A parametric down-conversion source with half the expected pair number $`\lambda`$,
at the same position. Ma, Fung and Lo (2007), Eqs. (9)-(12), with no decoys:

```math
Q_\lambda = 1 - \frac{1 - Y_0}{(1 + \eta_A\lambda)^2} - \frac{1 - Y_0}{(1 + \eta_B\lambda)^2} + \frac{(1 - Y_0)^2}{(1 + \eta_A\lambda + \eta_B\lambda - \eta_A\eta_B\lambda)^2}
```

```math
E_\lambda Q_\lambda = e_0 Q_\lambda - \frac{2(e_0 - e_d)\,\eta_A\eta_B\,\lambda(1 + \lambda)}{(1 + \eta_A\lambda)(1 + \eta_B\lambda)(1 + \eta_A\lambda + \eta_B\lambda - \eta_A\eta_B\lambda)}
```

```math
R \;\geq\; Q_\lambda\left[1 - f\, h_2(E_\lambda) - h_2(E_\lambda)\right]
```

The curve assumes the best $`\lambda`$ at each length, and a real source's brightness
is limited by technology, as Lo, Curty and Qi say of their own such curve.

### 9.4 Decoy-state BB84, and the bound

BB84 is sections 2 and 3 with infinitely many decoys, $`\eta = \eta_d 10^{-\alpha L/10}`$
and the same $`Y_0`$:

```math
R \;\geq\; Q_1\left[1 - h_2(e_1)\right] - f\, Q_\mu h_2(E_\mu),
\qquad Y_1 = Y_0 + \eta - Y_0\eta, \quad e_1 = \frac{Y_0/2 + e_d\eta}{Y_1}
```

The dashed curve is the repeaterless bound of Pirandola *et al.* (2017), Eq. (19),
bits per channel use over a pure-loss channel of the fibre's transmittance
$`\eta_f = 10^{-\alpha L/10}`$, without the detectors:

```math
K(\eta_f) = -\log_2(1 - \eta_f)
```

### 9.5 Golden vectors and checks

At the parameters of section 9.1, with the intensity chosen at each length:

| $`L`$ (km) | BB84 | BBM92 | MDI-QKD |
|---|---|---|---|
| 0 | $`3.216\times10^{-2}`$ | $`8.783\times10^{-4}`$ | $`5.752\times10^{-4}`$ |
| 50 | $`3.132\times10^{-3}`$ | $`8.009\times10^{-5}`$ | $`5.298\times10^{-5}`$ |
| 100 | $`2.903\times10^{-4}`$ | $`7.741\times10^{-6}`$ | $`4.935\times10^{-6}`$ |
| 150 | $`9.916\times10^{-6}`$ | $`7.531\times10^{-7}`$ | $`4.150\times10^{-7}`$ |
| 200 | no key | $`7.066\times10^{-8}`$ | $`2.151\times10^{-8}`$ |
| Longest fibre with key | 159.6 km | 310.8 km | 232.1 km |

`tests/test_protocol_rates.py` checks the reference without using its closed forms:

- **The single-photon terms against exact optics.** Two photons in the Fock basis of
  the four output modes, with lossy arms and threshold detectors, reproduce $`Y_{11}`$
  and $`e_{11}`$ at $`e_d = 0`$, and the outcome table of the walk-through: equal Z
  inputs bunch, opposite Z inputs give a result every time, X inputs half the time,
  and mismatched bases give $`\psi^+`$ and $`\psi^-`$ a quarter each. A pair in a
  given basis succeeds with probability $`\tfrac{1}{2}\eta_A\eta_B`$ only as an
  average over the bits.
- **The overall gain against a direct count.** The same detectors, counted over a
  numerically integrated relative phase, reproduce $`Q_{\mathrm{rect}}`$ and
  $`E_{\mathrm{rect}}`$ to a part in $`10^{6}`$.
- **The thermal gain against its sum.** $`Q_\lambda`$ against the sum over $`n`$ of
  Ma, Fung and Lo's Eqs. (5) and (7).
- **The published curves, read from the figure.** With $`q = 1/4`$ for balanced bases
  and a Z-only key, the MDI curve of Lo, Curty and Qi's Fig. 2 reads about
  $`1.5\times10^{-4}`$ at 0 km and $`1.2\times10^{-6}`$ at 100 km, and this model gives
  $`1.44\times10^{-4}`$ and $`1.23\times10^{-6}`$. That curve reaches $`10^{-10}`$ at
  about 222 km, and this model at 229.8 km with $`p_d = 3.0\times10^{-6}`$ and at 201 km
  with $`6.02\times10^{-6}`$ per detector: they model misalignment with two rotations,
  this is Ma and Razavi's simpler model, and the end of the curve is where the two part.
  Their entanglement curve reads about $`8\times10^{-4}`$ at 0 km and reaches
  $`10^{-10}`$ at about 300 km, and this model gives $`8.78\times10^{-4}`$ and 303.0 km,
  with $`q = 1`$. These are readings from a logarithmic plot, not digits.
- **Section 6 again.** The BB84 line at $`q = 1/2`$ reproduces $`2.555\times10^{-3}`$.

### 9.6 What these models do not include

- **Finite-key effects.** MDI-QKD's finite-size analysis is a separate piece of work
  (Xu *et al.* 2013 and later), and two-photon components make it harder than BB84's.
  Nothing here is a statement about a block of data.
- **Finite decoy states.** The single-photon terms are computed, not estimated.
- **Mode mismatch, detector imbalance and source flaws.** All sources are taken as
  perfectly characterised, and all detectors as identical. A model cannot show the
  point of MDI-QKD, which is removing attacks on the measurement unit: there is no
  attack model here, and the page draws no comparison of security.
- **A comparison of systems.** A curve's reach is a statement about these formulas at
  these parameters. Fig. 2's own authors warn about the optimal-brightness assumption
  of the entanglement curve, and real records depend on hardware none of this models.

---

## 10. References

Full citations in [`references.md`](references.md).

- X. Ma, B. Qi, Y. Zhao, H.-K. Lo, *Practical decoy state for quantum key
  distribution*, Phys. Rev. A **72**, 012326 (2005) — the channel model,
  Eqs. 5/10/11, and the decoy bounds.
- H.-K. Lo, X. Ma, K. Chen, *Decoy state quantum key distribution*,
  Phys. Rev. Lett. **94**, 230504 (2005).
- D. Gottesman, H.-K. Lo, N. Lütkenhaus, J. Preskill, QIC **4**, 325 (2004) —
  the GLLP rate.
- C. C. W. Lim *et al.*, Phys. Rev. A **89**, 022307 (2014) — the finite-key
  treatment this project approximates.
- H.-K. Lo, M. Curty, B. Qi, Phys. Rev. Lett. **108**, 130503 (2012) — MDI-QKD, its
  rate and Fig. 2.
- X. Ma, M. Razavi, Phys. Rev. A **86**, 062319 (2012) — the closed forms of section 9.2.
- F. Xu, H. Xu, H.-K. Lo, New J. Phys. **15**, 113007 (2013) — a system model and the
  finite-decoy analysis of MDI-QKD.
- X. Ma, C.-H. F. Fung, H.-K. Lo, Phys. Rev. A **76**, 012307 (2007) — section 9.3.
- S. Pirandola, R. Laurenza, C. Ottaviani, L. Banchi, Nat. Commun. **8**, 15043 (2017) —
  the repeaterless bound.

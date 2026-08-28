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

---

## 1. Notation

| Symbol | Meaning | Config key |
|---|---|---|
| $\alpha$ | Fibre attenuation (dB/km) | `physical.fiber_attenuation_db_per_km` |
| $L$ | Link length (km) | `physical.link_length_km` |
| $\eta_d$ | Detector efficiency | `physical.detector_efficiency` |
| $\eta$ | Total transmittance | derived |
| $Y_0$ | Dark-count yield (per pulse) | derived from `physical.dark_count_rate_hz` |
| $e_d$ | Detector misalignment error | `physical.misalignment_error_ed` |
| $e_0$ | Error rate of background counts, $=\tfrac12$ | fixed by theory |
| $\mu$ | Signal intensity (mean photon number) | `source.intensity_signal_mu` |
| $\nu_1,\nu_2$ | Decoy intensities | `source.intensity_decoy_1_nu1`, `..._2_nu2` |
| $f_{\mathrm{EC}}$ | Error-correction efficiency | `protocol.ec_efficiency_f` |
| $q$ | Sifting factor in the ASYMPTOTIC rate, $=\tfrac12$ for symmetric BB84 | hard-coded `0.5` |
| $q_x$ | Probability of choosing the KEY basis, in the finite-key analysis. **Not the same quantity as $q$** -- the sifted fraction is $q_x^2$. Both readings coincide at the shipped `0.5`, which is why one field served both; they differ by 106x at 0.9. | `source.basis_bias_pz` |
| $p_{\mu}, p_{\nu_1}, p_{\nu_2}$ | Intensity-choice probabilities. Load-bearing: $\tau_n = \sum_k p_k e^{-k} k^n / n!$ and the Hoeffding deviation is divided by $p_k$. Must sum to 1. | `source.prob_signal_mu`, `source.prob_decoy_1_nu1`, `source.prob_decoy_2_nu2` |
| $\varepsilon_{\text{sec}}$ | Secrecy parameter. Composed from seven terms; all equal gives $\varepsilon_{\text{sec}} = 21\varepsilon$. | `protocol.security_epsilon` |
| $\varepsilon_{\text{cor}}$ | Correctness parameter -- the error-verification hash collision probability. A distinct quantity, previously absent entirely. | `protocol.correctness_epsilon` |

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
intensity $\mu$ produces a detection — is (Eq. 10):

```math
Q_\mu \;=\; Y_0 + 1 - e^{-\eta\mu}
```

and the **quantum bit error rate** is (Eq. 11):

```math
E_\mu \;=\; \frac{e_0 Y_0 + e_d\left(1 - e^{-\eta\mu}\right)}{Q_\mu}
\qquad e_0 = \tfrac12
```

Background counts are random, hence $e_0 = 1/2$: half of them land in the wrong
detector.

> **Note on the approximation.** These use the standard $Y_i \simeq Y_0 + \eta_i$
> with $\eta_i = 1-(1-\eta)^i$. Carrying the exact $Y_i = Y_0 + \eta_i - Y_0\eta_i$
> through the sum gives $Q_\mu^{\text{exact}} = 1-(1-Y_0)e^{-\eta\mu}$, which
> differs by $\mathcal{O}(Y_0)$ — negligible for $Y_0 \lesssim 10^{-5}$, but the
> reason two code paths should not be compared for exact equality.

---

## 3. Asymptotic secret-key rate (GLLP)

With the single-photon contribution separated out
(Gottesman–Lo–Lütkenhaus–Preskill; Lo–Ma–Chen 2005):

```math
R \;\geq\; q\left\{-Q_\mu f_{\mathrm{EC}}\,h_2(E_\mu) \;+\; Q_1\left[1 - h_2(e_1)\right]\right\}
```

where $h_2$ is the binary entropy

```math
h_2(x) \;=\; -x\log_2 x - (1-x)\log_2(1-x)
```

Reading the two terms: the first is what error correction *costs* — it leaks
$f_{\mathrm{EC}}h_2(E_\mu)$ bits per sifted bit. The second is what the
single-photon pulses *earn*, after privacy amplification removes $h_2(e_1)$ bits
to account for what an eavesdropper could know. Multi-photon pulses contribute
nothing: they are assumed fully compromised (the photon-number-splitting attack).

---

## 4. Decoy-state estimation

$Q_1$ and $e_1$ are not directly observable. Decoy states bound them by
transmitting extra intensities $\nu_1 > \nu_2 \geq 0$ and comparing the
resulting gains.

With $\mu > \nu_1 + \nu_2$, the single-photon yield is bounded below by:

```math
Y_1^{L} \;=\; \frac{\mu}{\mu\nu_1 - \nu_1^{2}}
\left(Q_{\nu_1}e^{\nu_1} - Q_{\nu_2}e^{\nu_2}
- \frac{\nu_1^{2}-\nu_2^{2}}{\mu^{2}}\left(Q_\mu e^{\mu} - Y_0\right)\right)
```

and the single-photon error rate above by:

```math
e_1^{U} \;=\; \frac{E_{\nu_1}Q_{\nu_1}e^{\nu_1} - e_0 Y_0}{Y_1^{L}\,\nu_1}
```

giving the single-photon gain

```math
Q_1 \;=\; \mu e^{-\mu} Y_1^{L}
```

Both bounds are clamped to physical ranges ($Y_1^L \geq 0$,
$0 \leq e_1^U \leq \tfrac12$); the rate is clamped at $0$, since a negative
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

The GYS parameter set at $L=0$, worked through Ma *et al.* (2005). CI asserts
the implementation reproduces every line.

| Quantity | Value |
|---|---|
| $\eta$ | $0.045$ |
| $Y_0$ | $1.7\times10^{-6}$ |
| $e_d$ | $0.033$ |
| $\mu$ | $0.48$ |
| $f_{\mathrm{EC}}$ | $1.22$ |
| $Q_\mu$ | $2.13701\times10^{-2}$ |
| $E_\mu$ | $3.3037\times10^{-2}$ |
| $Q_1$ | $1.33670\times10^{-2}$ |
| $e_1$ | $3.3017\times10^{-2}$ |
| **$R$** | $\mathbf{2.555\times10^{-3}}$ bits/pulse |

At a 2 MHz repetition rate that is $\approx 5.1$ kbit/s.

**If an implementation does not reproduce $R = 2.555\times10^{-3}$ here, the
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
  no real leakage is measured. $f_{\mathrm{EC}}$ is an assumed constant.
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

## 8. References

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

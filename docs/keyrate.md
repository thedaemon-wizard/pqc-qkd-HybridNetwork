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
| $q$ | Sifting factor, $=\tfrac12$ for symmetric BB84 | `source.basis_bias_pz` |

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

Real runs are finite, so the asymptotic rate is optimistic. A first-order
correction is applied:

```math
R_{\text{finite}} \;=\; \max\left(0,\; R - \sqrt{\frac{2}{N}}\sqrt{\log_2\frac{2}{\varepsilon}}\right)
```

with block size $N$ (`protocol.block_size_N`) and security parameter
$\varepsilon$ (`protocol.security_epsilon`).

> **Limitation, stated plainly.** This is a first-order penalty term, not a
> composable finite-key security proof. A rigorous treatment needs the bounds of
> Lim *et al.*, *Phys. Rev. A* **89**, 022307 (2014), which track
> $\varepsilon_{\text{sec}}$, $\varepsilon_{\text{cor}}$, $\varepsilon_{\text{PA}}$
> and $\varepsilon_{\text{EC}}$ separately and use Chernoff/Hoeffding bounds on
> each estimated quantity. Numbers from this project's finite-key path should be
> read as indicative, not as certified key lengths.

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
- **Coherent attacks** are covered only insofar as the GLLP bound covers them
  asymptotically; there is no composable security accounting.

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

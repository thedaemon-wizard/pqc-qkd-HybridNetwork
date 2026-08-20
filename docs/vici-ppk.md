# Delivering a QKD key to strongSwan

How the IPsec lane injects arnika's `HKDF-SHA3-256(QKD ‖ PQC)` output into
IKEv2, why it uses RFC 8784 rather than a preshared key, and what the
construction does *not* give you.

---

## 1. Why a plain PSK is the wrong mechanism

An IKEv2 preshared key is consumed in exactly one place: computing the `AUTH`
payload of `IKE_AUTH` (RFC 7296 §2.15).

$$\mathrm{AUTH} \;=\; \mathrm{prf}\Big(\mathrm{prf}\big(\text{PSK},\ \texttt{"Key Pad for IKEv2"}\big),\ \text{SignedOctets}\Big)$$

It **authenticates** the peers. It never enters `SKEYSEED`, so it contributes
nothing to the session keys. Those come entirely from the (EC)DH exchange in
`IKE_SA_INIT`.

The consequence is the whole point of this document: an adversary who records
traffic today and later runs Shor's algorithm on the DH exchange recovers the
session keys regardless of the PSK. **Rotating a QKD key as an IKEv2 PSK
provides zero confidentiality benefit against a harvest-now-decrypt-later
adversary.**

This project's IPsec lane used to do exactly that.

---

## 2. RFC 8784 — the mechanism that does work

RFC 8784 mixes a Post-quantum Preshared Key into the key schedule itself:

$$
\begin{aligned}
\mathrm{SK\_d}  &= \mathrm{prf}^{+}(\text{PPK},\ \mathrm{SK\_d}')\\
\mathrm{SK\_pi} &= \mathrm{prf}^{+}(\text{PPK},\ \mathrm{SK\_pi}')\\
\mathrm{SK\_pr} &= \mathrm{prf}^{+}(\text{PPK},\ \mathrm{SK\_pr}')
\end{aligned}
$$

`SK_d` is the root of every Child SA's `KEYMAT` and of all subsequent rekeys, so
an attacker now needs **both** the DH secret **and** the QKD key. That is the
property QKD material is supposed to provide.

RFC 8784 requires the PPK to carry **at least 256 bits of entropy** for 128-bit
post-quantum security; the adapter enforces this and refuses shorter keys.

This is the same mechanism MikroTik RouterOS, Palo Alto PAN-OS and Cisco SKIP
use for QKD integration — no invention here, just the standard construction.

### What it does not protect

Stated plainly, because it is easy to overclaim:

- The PPK is **not** mixed into `SKEYSEED`. The initial IKE SA's `SK_ei`/`SK_er`
  are therefore **not** PPK-protected — only `SK_d` (hence all Child SA traffic)
  and the authentication keys. This is deliberate in the RFC: the responder must
  be able to decrypt the first exchange before it can select a PPK.
- RFC 8784 applies to the **initial IKE SA only**. The RFC forbids reapplying
  the PPK on rekey, resumption or similar. Fresh QKD material therefore requires
  a full reauthentication, not a rekey (§4).
- **RFC 9867** (November 2025) lifts both limits — PPKs in `IKE_INTERMEDIATE`
  and `CREATE_CHILD_SA`, so every rekey can consume fresh material, plus
  `PPK_IDENTITY_KEY` for offering several PPK candidates. The RFC names QKD as
  the motivating source of dynamic PPKs, and states the limitation this project
  works around directly: *"If a fresh PPK becomes available before the IKE SA is
  expired, there is no way to use it except for deleting the IKE SA and
  recreating a new one from scratch."*

  **strongSwan 6.0.7 does not implement it.** Verified 2026-08-20 against
  `src/libcharon/encoding/payloads/notify_payload.h` on `master`, which defines
  only `USE_PPK = 16435`, `PPK_IDENTITY = 16436` and `NO_PPK_AUTH = 16437`.
  Neither `USE_PPK_INT` (16445) nor `PPK_IDENTITY_KEY` (16446) appears anywhere
  in the tree, and no branch implements them. Until it lands, a reauthentication
  per rotation is not a design choice here — it is the only mechanism available.

---

## 3. The complementary half: RFC 9370

RFC 8784 and RFC 9370 solve different problems and this project uses both.

| | RFC 8784 (PPK) | RFC 9370 (multiple KE) |
|---|---|---|
| Secret origin | out-of-band, never on the wire | negotiated on the wire |
| Where mixed | `SK_d`, `SK_pi`, `SK_pr` | `SKEYSEED`, chained per round |
| Protects | against a broken DH, given the PPK stays secret | against a broken DH, given the KEM holds |
| Scope | initial IKE SA only | every SA, including rekeys |

The connection proposes `ecp256-ke1_mlkem768`: classical ECP-256 in
`IKE_SA_INIT`, then ML-KEM-768 as Additional Key Exchange 1 carried in an
`IKE_INTERMEDIATE` exchange (RFC 9242). Round $n$ chains forward:

$$\mathrm{SKEYSEED}(n) \;=\; \mathrm{prf}\big(\mathrm{SK\_d}(n-1),\ \mathrm{SK}(n)\ |\ N_i\ |\ N_r\big)$$

so the result is secure if **any single** round is secure.

Why `IKE_INTERMEDIATE` matters: ML-KEM-768 public keys and ciphertexts are 1184
and 1088 bytes. `IKE_SA_INIT` is unencrypted, and IKEv2 fragmentation (RFC 7383)
only applies to encrypted messages — so putting ML-KEM there invites IP
fragmentation and PMTU blackholes. RFC 9242 runs the exchange after `IKE_SA_INIT`
where it can be encrypted and therefore fragmented.

### Syntax that actually parses

The only spelling strongSwan accepts is **`mlkem768`**
(`src/libstrongswan/crypto/proposal/proposal_keywords_static.txt`):

```
proposals     = aes256gcm16-prfsha384-ecp256-ke1_mlkem768
esp_proposals = aes256gcm16-ecp256-ke1_mlkem768
```

- ❌ `ml_kem_768` — the long name used in log output; it does not parse.
- ❌ `kyber768` — never existed upstream. `kyber1/3/5` were fork-only keywords
  in the pre-6.0 out-of-tree "PQ strongSwan" work.
- Both peers must use the **same `keN_` slot number**; `ke1_` on one side and
  `ke2_` on the other will not match.
- ML-KEM is **not** in `proposals = default`. It must be configured explicitly.

### Making ML-KEM actually available

Two independent things must both be true, and only the first is obvious:

1. A provider must be **built** — either the `ml` plugin (`--enable-ml`, which
   is *not* on by default) or the `openssl` plugin against **OpenSSL ≥ 3.5**.
2. The plugin must be **named in charon's `load` line**. Building it is not
   enough; this is upstream issue #2690.

Verify at runtime, never assume:

```console
$ swanctl --list-algs | grep ML_KEM
  ML_KEM_512[openssl]
  ML_KEM_768[openssl]
  ML_KEM_1024[openssl]
```

The node's entrypoint asserts this at startup and refuses to continue without it.

---

## 4. Rotation

### Why rotation needs a reauthentication

Two facts compose badly, and missing either produces a system that looks like it
rotates keys but does not:

1. VICI `load-shared` only writes into charon's in-memory credential set. It
   touches no SA, schedules no job, raises no event.
2. An IKEv2 **rekey** is a `CREATE_CHILD_SA` exchange. It carries no `AUTH`
   payload and does not re-read credentials — strongSwan's own documentation
   says rekeying "does not re-check associated credentials".

So only a **reauthentication**, which re-runs `IKE_SA_INIT` + `IKE_AUTH`,
consumes a newly loaded PPK.

`charon.make_before_break` has been on by default since strongSwan 6.0.0, so
reauth creates the replacement SAs before tearing down the old ones and does not
interrupt traffic.

### The sequence

Implemented in
[`services/arnika-vici/repositories/strongswan-vici.go`](../services/arnika-vici/repositories/strongswan-vici.go):

```
1. load-shared   { id: "qkd-<peer>-<n+1>", type: "ppk", data: <32 B>, owners: [<ppk_id>] }
2. get-shared    -> assert the new id is present
3. rekey         { ike: <conn>, reauth: "yes" }
   -> assert success == "yes" AND matches >= 1
4. unload-shared { id: "qkd-<peer>-<n>" }      # only now
```

Three details that are not optional:

- **`matches >= 1` must be asserted.** `success = yes` with `matches = 0` is
  charon's normal answer when the selector matched nothing — success alone
  proves nothing happened.
- **The old generation is unloaded last.** Unloading the in-use credential does
  not tear down the current SA; it breaks the *next* reauthentication, possibly
  hours later. Guard it behind confirmation that the new one landed.
- **Every `load-shared` carries an `id`.** Without one, charon accumulates a new
  entry per rotation forever, the entries are invisible to `get-shared`, and
  they can never be removed except by `clear-creds`. For a loop rotating every
  30 s that is an unbounded leak *and* an ever-growing set of keys any peer can
  authenticate with.

### Never run `swanctl --load-creds` on these nodes

`swanctl --load-creds` is a **destructive sync**, not an additive load. It calls
`get-shared`, then issues `unload-shared` for every vici-injected id that is not
also a `secrets.*` section in `swanctl.conf`. On a node using dynamic injection
it deletes the rotating QKD PPK.

`swanctl --load-all` and a `systemctl reload` take the same path. Load
connections with `swanctl --load-conns` instead. The entrypoint uses
`--load-creds` exactly once, at boot, before arnika starts.

---

## 5. Where the key comes from

The adapter changes only *where* a key is delivered. Agreement remains arnika's
job, unchanged:

```
KME-A  --ETSI 014 enc_keys-->  arnika (master)  --key_ID over UDP-->  arnika (backup)
                                     |                                      |
                                     |                        ETSI 014 dec_keys --> KME-B
                                     v                                      v
                            HKDF-SHA3-256(QKD ‖ PQC)            HKDF-SHA3-256(QKD ‖ PQC)
                                     |                                      |
                                     +--------- same 32-byte key -----------+
                                     |
                       VICI load-shared type=ppk + reauth
```

Note the SAE direction, which is easy to get backwards: per ETSI GS QKD 014
clause 5.1, `enc_keys` names the **slave** SAE in the path and `dec_keys` names
the **master**. From either node that is always the *peer's* SAE ID, which is
why one base `KMS_URL` serves both directions.

### Why the PPK_ID is stable rather than the ETSI key_ID

Binding `PPK_ID = key_ID` looks attractive — the identifier would travel on the
wire in the `PPK_IDENTITY` notify, tying the IKE exchange to a specific QKD key.
It does not work, for a concrete reason:

The responder resolves `PPK_IDENTITY` with a **synchronous credential lookup**
during `IKE_AUTH` (`ike_auth.c`, `get_ppk_r` → `credmgr->get_shared(SHARED_PPK, …)`).
The key must already be loaded when the exchange arrives. The notify therefore
*selects* a key; it cannot *deliver* one. A per-rotation PPK_ID would also mean
reloading the connection before every reauth, since `ppk_id` lives in
`peer_cfg_t` rather than in the credential set.

So the identity is stable and the material behind it rotates.

---

## 6. Upstreaming

The adapter is written against upstream arnika's key-writer port
(`services/keywriter.go`):

```go
type keyWriterRepository interface {
	InvalidateTunnel() error
	SetPSK(psk string) error
}
```

Two methods, structurally satisfiable from outside the package. Adapter
selection is by build tag in a root file, mirroring `wireguardnetlink.go`.

`wireguardmikrotik.go` is currently a three-line stub with no implementation, so
a VICI backend would be arnika's **second working key-writer**.

The one upstream change required is a build-tag narrowing so the adapters are
mutually exclusive — see
[`0001-make-key-writer-adapters-mutually-exclusive.patch`](../services/arnika-vici/0001-make-key-writer-adapters-mutually-exclusive.patch).

Known rough edge to raise upstream: `config.Parse` requires
`WIREGUARD_INTERFACE` and `WIREGUARD_PEER_PUBLIC_KEY` unconditionally, even for
a non-WireGuard key writer. They should be conditional on the selected adapter.

---

## 7. Open questions

Recorded rather than resolved, so the next revision has somewhere to start.

**Role binding on the key-ID channel.** arXiv:2608.07626 (Tamarin analysis of
23 ETSI/ITU-T QKD documents, 2026-08-07) reports vulnerability **V3, message
reflection**: MAC inputs that omit role binding allow a reflected message to be
accepted as peer authentication. Its countermeasure **CM2** is an
identity-bound MAC, `mac_psk(sender_id, receiver_id, session, data)`.

arnika's UDP key-ID channel signs `[type][timestamp][payload]`
(`auth/auth.go`, `signedPayload`) with a PSK **shared by both peers**, and no
sender or receiver identity is covered. Its `ARNIKA_ID` — which already exists
and already differs per node — is not part of the signed input.

What that does and does not mean, stated carefully: the server accepts only
`PacketData`, so a `D`→`A` type confusion is not possible, and the timestamp
window bounds replay. But a node would accept **its own outbound packet
reflected back** inside that window. Whether that is exploitable in arnika's
specific flow has **not** been demonstrated here — verifying it needs two live
nodes and packet injection, which is out of scope for this testbed. It is
raised as a question for upstream, not asserted as a vulnerability.

**Key-ID binding to the ciphertext.** arXiv:2607.06602 binds the ETSI `key_ID`
into the AES-GCM AAD, so the identifier cannot be swapped independently of the
data it selected. Neither arnika nor this project's lanes do that today.

**Rotation cadence versus link capacity.** See the measured field rates in
[`references.md`](references.md): at 12–22 bit/s a 256-bit key needs 12–20 s to
accumulate. The 30 s default here is defensible only for a simulator; on a real
link the paper's 120 s is the honest figure, and `REAUTH_TIME` should be
derived from measured SKR rather than configured independently of it.

---

## 8. References

Full citations in [`references.md`](references.md). Primary: RFC 8784, RFC 9370,
RFC 9242, RFC 9867, RFC 7296 §2.15, ETSI GS QKD 014 V1.1.1, and the strongSwan
VICI protocol README.

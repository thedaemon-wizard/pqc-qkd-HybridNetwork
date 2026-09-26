# Delivering a QKD key to strongSwan

How the IPsec lane injects arnika's `HKDF-SHA3-256(QKD ‖ PQC-HPKE)` output
into IKEv2, why it uses RFC 8784 rather than a preshared key, and what the
construction does *not* give you. The PQC half is arnika's own key agreement
with its peer (HPKE in Base mode, RFC 9180, with the hybrid KEM
MLKEM1024-P384 from draft-ietf-hpke-pq); no Rosenpass runs on this lane.

---

## 1. Why a plain PSK is the wrong mechanism

An IKEv2 preshared key is consumed in exactly one place: computing the `AUTH`
payload of `IKE_AUTH` (RFC 7296 §2.15).

```math
\mathrm{AUTH} \;=\; \mathrm{prf}\Big(\mathrm{prf}\big(\text{PSK},\ \texttt{"Key Pad for IKEv2"}\big),\ \text{SignedOctets}\Big)
```

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

```math
\mathrm{SK\_d} = \mathrm{prf}^{+}(\text{PPK},\ \mathrm{SK\_d}')
```

```math
\mathrm{SK\_pi} = \mathrm{prf}^{+}(\text{PPK},\ \mathrm{SK\_pi}')
```

```math
\mathrm{SK\_pr} = \mathrm{prf}^{+}(\text{PPK},\ \mathrm{SK\_pr}')
```

`SK_d` is the root of every Child SA's `KEYMAT` and of all subsequent rekeys, so
an attacker now needs **both** the DH secret **and** the QKD key. That is the
property QKD material is supposed to provide.

RFC 8784 sets **no** PPK length requirement — it uses no MUST, SHOULD or
RECOMMENDED for PPK length anywhere. Its Sec. 6 says only that *"the strongest
practice is to ensure that any post-quantum preshared key contains at least 256
bits of entropy; this will provide 128 bits of post-quantum security, while
providing security against conventional dictionary attacks."* Descriptive, not
normative.

The adapter nevertheless refuses anything shorter than 32 bytes, for a reason
specific to this deployment rather than to the RFC: every PPK it installs is a
32-byte HKDF-SHA3-256 output from arnika, so a shorter one means the key path is
broken upstream, not that an operator chose weaker material. That floor is this
project's — see `minPPKBytes` in
`services/arnika-vici/repositories/swanvici/vici.go`.

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
- `ppk_required = yes` is a statement of configuration, and whether it is
  *enforced* has depended on the strongSwan version and on which role the node
  plays. Two different failures get conflated here, so separate them:

  - **The two peers hold different PPKs.** Authentication fails on its own —
    the MAC does not verify — and no `ppk_required` check is involved. That is
    the case traced under "the rotation race" below.
  - **The peer used no PPK at all.** This is the one that needed the flag. In
    `process_i()`, the initiator handling of the IKE_AUTH response checked
    `OPT_PPK_REQUIRED` when *building* its request and on the responder side,
    but not here: it logged `peer didn't use PPK for PPK_ID`, called
    `clear_ppk()` and continued. The tunnel came up, reported success, and the
    QKD key was simply absent. Upstream closed it in **6.1.0** with
    [`50177b40`](https://github.com/strongswan/strongswan/commit/50177b4004d1fec4299cd7bed4a3c7fb0f4208d7),
    whose `Fixes:` trailer names the commit that first added PPK support — so
    every release before 6.1.0 carried it.

  This node is the initiator (`VICI_IKE_ROLE`), so it sat on the affected side,
  and the composition is what makes it worth recording: a responder stops
  supplying a PPK exactly when its arnika fails to install one, which is the
  same fail-open shape as the peer-lookup and KMS-retry bugs fixed upstream in
  arnika. Two fail-open paths in series produce a tunnel that looks healthy from
  both ends. The pin is 6.1.0 for this reason (it is also this lane's
  security floor: 6.1.0 fixes CVE-2026-78133, which affects every release
  since 6.0.0 on servers that accept multiple key exchanges, as this one does;
  see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md#strongswan)), and
  `tests/test_claims_about_the_pinned_strongswan_hold.py` asserts the fix is in
  the tree that actually gets built -- anchored on `process_i()`, because the
  affected tree already carried five `OPT_PPK_REQUIRED` checks elsewhere in the
  same file and a weaker assertion would have passed against it.

- **RFC 9867** (November 2025) lifts both limits — PPKs in `IKE_INTERMEDIATE`
  and `CREATE_CHILD_SA`, so every rekey can consume fresh material, plus
  `PPK_IDENTITY_KEY` for offering several PPK candidates. The RFC names QKD as
  the motivating source of dynamic PPKs, and states the limitation this project
  works around directly: *"If a fresh PPK becomes available before the IKE SA is
  expired, there is no way to use it except for deleting the IKE SA and
  recreating a new one from scratch."*

  **Two reproducible observations, not a flat claim.** The previous wording
  said the pinned tree "defines only `USE_PPK = 16435`, `PPK_IDENTITY = 16436`
  and `NO_PPK_AUTH = 16437`", and that "no branch implements them". The first
  is false and the second is not checkable. `notify_payload.h` also defines
  `INTERMEDIATE_EXCHANGE_SUPPORTED = 16438`, `ADDITIONAL_KEY_EXCHANGE = 16441`,
  `USE_AGGFRAG = 16442` and `SA_RESOURCE_INFO = 16444` — and dropping 16444
  discarded the strongest part of the argument. What can actually be
  established, in a minute each:

  1. RFC 9867 needs `USE_PPK_INT` (16445) and `PPK_IDENTITY_KEY` (16446).
     Neither appears anywhere under `submodules/strongswan/src/`, so neither
     can be sent or parsed. Note *where* they would sit: **16444 is the highest
     Status Type in the enum**, and the next entry is
     `INITIAL_CONTACT_IKEV1 = 24578`. So 16445 and 16446 are the two values
     immediately above the top of the range, not a gap in the middle.
  2. The `IKE_SA_INIT` response on this lane carries `N(USE_PPK)`. RFC 9867
     §3.1 has a responder return either `USE_PPK_INT` or `USE_PPK` and never
     both, so that single notify settles which specification is running.

  `N(IKE_INT_SUP)` also appears on this lane; that is RFC 9242's intermediate
  exchange, present for RFC 9370's ML-KEM key exchange, and is **not** an
  RFC 9867 indicator.

  Until 9867 lands, a reauthentication per rotation is not a design choice
  here — it is the only mechanism available.

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
`IKE_INTERMEDIATE` exchange (RFC 9242). Round $`n`$ chains forward:

```math
\mathrm{SKEYSEED}(n) \;=\; \mathrm{prf}\big(\mathrm{SK\_d}(n-1),\ \mathrm{SK}(n)\ |\ N_i\ |\ N_r\big)
```

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

- `ml_kem_768` is **rejected** — that is the long name used in log output.
- `kyber768` is **rejected** — it never existed upstream. `kyber1/3/5` were fork-only keywords
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
[`services/arnika-vici/repositories/swanvici/vici.go`](../services/arnika-vici/repositories/swanvici/vici.go)
and set out step by step, with the reasons for each, in the adapter's
[README](../services/arnika-vici/README.md) ("Rotation sequence"). In short:

```
1. load-shared   { id: "qkd-<peer>-<n+1>", type: "ppk", data: <32 B>, owners: [<ppk_id>] }
2. get-shared    -> assert the new id is present
3. list-sas      -> pick the newest IKE_SA of the connection
   rekey         { ike-id: <unique id>, reauth: "yes" }   (initiate, if no SA exists yet)
   -> assert success == "yes" AND matches >= 1
4. unload-shared { id: "qkd-<peer>-<n>" }      # only now
5. unload-shared { id: <bootstrap id> }        # once
```

Only the node configured as the IKE initiator drives step 3; both nodes load
every generation. Step 3 selects one SA by `ike-id`, not by connection name:
selecting by name reauthenticates every SA on the connection, and since
make-before-break builds each replacement before dropping the original, N SAs
become 2N.

Four details that are not optional:

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
- **The bootstrap credential is unloaded once the first rotation lands.** It
  answers the same `PPK_ID` as every rotated credential and carries no QKD
  material, so while it stays loaded two keys answer one lookup and charon's
  choice between them is unspecified.

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
job; the adapter sees 32 bytes and nothing else:

```
KME-A  --ETSI 014 enc_keys-->  arnika (PRIMARY) --key_ID over UDP-->  arnika (BACKUP)
                                     |                                  |
                                     |              ETSI 014 dec_keys --> KME-B
                                     v                                  v
                      HKDF-SHA3-256(QKD ‖ PQC-HPKE)      HKDF-SHA3-256(QKD ‖ PQC-HPKE)
                                     |                                  |
                                     |                  1. VICI load-shared type=ppk
                                     |<------------- 2. ACK ------------+
                                     v
                  3. VICI load-shared type=ppk
```

Beside this exchange, the two arnika instances run one PQC-HPKE round per
interval over the same UDP socket, with a fresh MLKEM1024-P384 key pair each
round, and each HKDF takes the key of the latest round it has published. On
whichever node is the IKE initiator, its `load-shared` is followed by the
queued reauthentication.

The order is new with the `f4cf9ba` pin (arnika#51, commit `3e02741`): the
BACKUP installs its key before it ACKs the `key_id`
(`transport/server.go`, `RunKeyIDWorker`), and the PRIMARY installs only after
the ACK arrives (`main.go`, the `SendKeyID` call and the `writePSK` after it).
At the previous pin `3a8cc13` the BACKUP ACKed on receipt, before its
`dec_keys` request, so the PRIMARY installed first and the BACKUP one KME round
trip later -- the order behind the race measured below. Without an ACK, under
`QkdAndPqcRequired`, the PRIMARY now installs a random key instead.

Which node is PRIMARY is drawn afresh every interval: the pinned arnika takes
an HMAC-SHA256 of the interval number, keyed with `ARNIKA_PSK`, and XORs it
with `ARNIKA_ID` (`IsPrimary` in `submodules/arnika/config/config.go`), so the
two nodes' IDs must differ in parity. The interval number is each process's
own count since it started, so the two elections are complementary only
while the two counts agree, which is why a pair is recreated together. This
lane's entrypoint deliberately starts arnika without waiting for an interval
boundary, as at v0.1.0; only the WireGuard lane's does
([`BUILD.md` 7.3](BUILD.md#73-starting-arnika-on-the-interval-boundary)).
arnika v1.x instead made whichever peer
received a `key_id` first the backup; the QCI-CAT design document describes
that older rule (see [`references.md`](references.md) section 3).

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
(`services/keywriter.go` at the `f4cf9ba` pin):

```go
type keyWriterRepository interface {
	SetPSK(psk []byte) error
}
```

One method, structurally satisfiable from outside the package, and it takes
raw bytes rather than a base64 string. Invalidation (a fresh random 32-byte
key) and the lock that serialises writes moved into arnika's
`KeyWriterService`, so the adapter no longer implements `InvalidateTunnel`.
Following upstream's `KEYCONTROL.md` layout, the adapter is its own package,
`repositories/swanvici`, and is selected by the build tag in the root wiring
file `wire_strongswan_vici.go`, mirroring `wire_wireguard_netlink.go`. Until
#51, the port had two methods and took a base64 string, and the wiring file
mirrored `wireguardnetlink.go`.

One naming question is left for the maintainers rather than settled here:
`KEYCONTROL.md` names writer tags `wireguard_<backend>`, and `strongswan_vici`
does not follow that form because this writer does not write to WireGuard.

Upstream has since implemented the MikroTik writer (2026-08-29) and a netns
netlink writer, so a VICI backend would be arnika's **fourth** key writer.
This paragraph used to call `wireguardmikrotik.go` a three-line stub and the
VICI adapter the second.

The one upstream change it needs is the build-tag conjunct described in
[`services/arnika-vici/README.md`](../services/arnika-vici/README.md). A
standalone patch for it was withdrawn on 2026-09-25: upstream's
`KEYCONTROL.md` now makes that edit part of adding any writer.

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
(`auth/auth.go`, `signedPayload`), and no sender or receiver identity is in
that input. At the previous pin `3a8cc13` the HMAC key was the same for both
peers, so a node would have accepted **its own outbound packet reflected back**
inside the timestamp window; this section raised that as a question for
upstream.

**The `f4cf9ba` pin answers the reflection half of it.** `auth/auth.go` now
derives a separate HMAC key per direction, labelled by the sender's
`ARNIKA_ID` parity (`DirectionFor`, `deriveHMACKey`), so a packet reflected to
its sender fails verification there. That binds the direction, not the
parties or the session: any node holding the same `ARNIKA_PSK` with an
`ARNIKA_ID` of the opposite parity is accepted, which CM2's identity-bound MAC
would not allow. The server accepts `PacketData` and, since #51, `PacketPQC`;
a `D`→`A` type confusion is still not possible, and the timestamp window still
bounds replay. None of this has been exercised against live nodes with packet
injection here.

**Key-ID binding to the ciphertext.** arXiv:2607.06602 binds the ETSI `key_ID`
into the AES-GCM AAD, so the identifier cannot be swapped independently of the
data it selected. Neither arnika nor this project's lanes do that today.

**Rotation cadence versus link capacity.** See the measured field rates in
[`references.md`](references.md): at 12–22 bit/s a 256-bit key needs 12–20 s to
accumulate. The 30 s default here is defensible only for a simulator; on a real
link the interval, and `REAUTH_TIME`, should be derived from the measured SKR
rather than configured independently of it. (arXiv:2608.18869's 120 s is its
PQC renegotiation interval, not a QKD rotation, so it is not evidence for a
QKD figure. arnika's recommendation to align with WireGuard's 120 s rekey is,
though that is a WireGuard-lane argument, and the 120 s "default" in its v1.x
design document is not the pinned code's default of 10 s.)

---

## 8. References

Full citations in [`references.md`](references.md). Primary: RFC 8784, RFC 9370,
RFC 9242, RFC 9867, RFC 7296 §2.15, ETSI GS QKD 014 V1.1.1, and the strongSwan
VICI protocol README.

## "PSK" means two different things in this repository

Everything above is about the **IKEv2** preshared key, and the conclusion --
that it cannot carry post-quantum confidentiality -- applies only to that. It
does not apply to WireGuard's preshared key, which is a different mechanism
with the opposite property.

| | enters the key schedule? | what it can provide |
|---|---|---|
| IKEv2 PSK (RFC 7296 §2.15) | **No.** Only the `AUTH` payload | authentication only |
| RFC 8784 PPK | **Yes.** `SK_d = prf+(PPK, SK_d')` | post-quantum confidentiality |
| WireGuard `PresharedKey` | **Yes.** Mixed into the Noise_IKpsk2 chaining key | post-quantum confidentiality |

So WireGuard's PSK is mechanically the analogue of the **PPK**, not of the
IKEv2 PSK. Rosenpass states the consequence directly in its own README, which
is vendored at `submodules/rosenpass/readme.md`:

> Since it supplies WireGuard with key through the PSK feature using
> Rosenpass+WireGuard is cryptographically no less secure than using WireGuard
> on its own ("hybrid security").

This matters for reading the rest of the project. `/e2e` and `/paper-flow`
model the **WireGuard** lane (`alice`/`bob`: the `wg0` hop tunnel keyed by
arnika, and the `wg1` data tunnel keyed by Rosenpass through that same
preshared-key feature), so where they say a QKD-derived PSK is mixed in, that
is the Noise chaining-key mixing above and it is doing real work. They are not modelling the construction
this document argues against. This page is about the **IPsec/strongSwan** lane
(`docker-compose.strongswan.yml`), where the move from PSK to PPK was necessary.

Written down because the ambiguity is genuinely misleading: this document says
"PSK does not contribute to the session keys, so we moved to PPK", and a reader
who then sees `psk_prefix` on `/e2e` will reasonably conclude that page
demonstrates the weaker construction. The implementation was always correct;
the vocabulary was not.

## Known limitation: the rotation race

Rotating a PPK under a **stable** `PPK_ID` requires the two peers to switch
generations atomically. They cannot, and the residual race is observable.

Measured on a two-node run, 1 failure in 45 rotations:

```
14:12:59.004028  alice  loaded PPK shared key with id 'qkd-bob-26'
14:12:59.004040  alice  reauthenticating IKE_SA pqcqkd-vpn[26]      (+12 us)
14:12:59.003979  bob    generating IKE_AUTH response 2 [ N(AUTH_FAILED) ]
14:12:59.004850  bob    loaded PPK shared key with id 'qkd-alice-26' (+871 us)
```

Both peers derive generation 26 from the same ETSI 014 `key_ID` exchange, so
they are within a millisecond of each other -- but the initiator reauthenticates
12 microseconds after its own load, and the responder's load lands 871
microseconds later. In that window the responder answers the `PPK_ID` lookup
with generation 25 and, under `ppk_required = yes`, a mismatch is
`AUTHENTICATION_FAILED`.

It is self-correcting but **not retried**. Under make-before-break the failed
reauthentication is dropped and the previous SA stays established; the next
rotation, one interval later, reauthenticates it. The cost is one interval in
which the SA keeps the previous PPK generation. No SA is lost and no tunnel
sticks. (This paragraph said "charon retries" until 2026-09-25; the live 6.1.0
logs below show no retry.)

> **What this means for the CI ceiling, which is tighter than it reads.**
> The 45-rotation figure above comes from a long two-node run (the trace
> reaches generation 26). The `ipsec` CI job (displayed as "strongSwan lane")
> does **not** run that long:
> its window is `sleep 240`, and both nodes report **6 rotations**, measured
> repeatedly on 2026-08-22. So `authfail * 5 <= rotations` tolerates
> `floor(6/5) = 1` failure per run, not the nine that "20 %" suggests to a
> reader who assumes the 45-rotation baseline is what CI measures.
>
> At the observed race rate of 1-in-45 that is still comfortable -- roughly
> 0.13 expected failures per run -- so the ceiling is not the reason a run
> fails. One run on 2026-08-22 nonetheless reported **4 failures in 6
> rotations** on both nodes and passed cleanly with **0 in 6** on an immediate
> re-run of the same commit, with no lane file touched between them. That is
> well outside race territory and is unexplained.
>
> Treat a repeat as a real signal, not a flake to re-run: two failures in one
> window already exceeds the ceiling, so the guard has almost no headroom at
> this operating point, and a systematic mismatch would show as 3 of 6.

### 2026-09-25: strongSwan 6.1.0 on the live demo, 8.8 days

The race is still there, far less often, and it is milliseconds rather than
microseconds. Read from the `docker logs -t` of both IPsec nodes on the public
demo from 2026-09-16 12:21 to 2026-09-25 06:48 UTC -- strongSwan 6.1.0, arnika
`3a8cc13`, one IKE_SA per node throughout:

| window | PPK rotated (each node) | `using PPK for` (alice) | `AUTH_FAILED` | MAC mismatched (bob) |
|---|---|---|---|---|
| all, 8 d 18 h | 25,249 | 25,234 | 16 | 16 |
| last 7 days | 20,155 | -- | 9 | -- |
| last 24 hours | 2,879 | -- | 1 | -- |
| last hour | 120 | -- | 0 | -- |

**16 in 25,249 is 1 in 1,578**, against 1 in 45 on the two-node run above.
Failures per UTC day: 4 on the partial first day, then 1, **7**, 1, 1, 0, 1, 0,
1, 0. Seven fell on 2026-09-18 between 05:55 and 12:00 UTC, and one of those
shows a 12.7 ms gap between alice's `[SND]` and bob's `[RCV]` against about
1.5 ms normally, which suggests host scheduling delay; the cause is not
established.

**Every one of the 16 is the race described above.** Alice was PRIMARY for the
interval in all 16, bob received the `key_id` in all 16, and bob loaded its PPK
*after* answering with the MAC failure in all 16 -- a median of 1.7 ms after,
15.3 ms at worst. So the responder (BACKUP), which must fetch its key with
`dec_keys` after `[RCV]`, loses to the initiator (PRIMARY), which already holds
it. The example of 2026-09-24: alice loads at 15:15:05.002901, bob fails the
MAC at .011183 and loads at .012136.

**Do not attribute the drop to 6.1.0 alone.** The baseline came from a short
two-node run on a different host; this is a long run on the public demo, and the
race depends on scheduling. What 6.1.0 did change is recorded in section 2:
the initiator now enforces `ppk_required`. The CI ceiling `authfail*5 <=
rotations` held in every window above; at six rotations per CI run the expected
number of race failures is about 0.004.

`/api/vpn/ppk-rotations` counted these as 25,249 successes until the same day,
because arnika-vici logs `PPK rotated` when it queues the reauthentication. It
now also reports `auth_failed` and `ppk_applied`, and says when it shortened
the requested window.

### 2026-09-26: arnika #51 head, what changes for the rotation race

The arnika pin moved from `3a8cc13` to `f4cf9ba`, the head of the open PR #51.
Its commit `3e02741` (2026-09-24) makes the BACKUP install before it ACKs and
the PRIMARY install only after the ACK (section 5). Read against this lane,
that **moves** the exposed intervals; it does not remove them. This is from
reading the code, and nothing below has been measured yet:

- `alice-ipsec` is always the IKE initiator (`VICI_IKE_ROLE: initiator` in
  `docker-compose.strongswan.yml`), and the adapter queues the
  reauthentication inside `SetPSK`, straight after its own load.
- **Intervals where alice is PRIMARY are expected, reading the code, to be
  safe from this race.** bob loads and ACKs first, and alice loads and
  reauthenticates only after that ACK, so bob should already hold the new
  generation. All 16 failures of the 8.8-day run above were intervals of this
  kind. They can still fail in the other ways listed below.
- **Intervals where alice is BACKUP are expected to become the exposed
  ones.** alice loads, queues the reauthentication and ACKs; bob loads only
  once that ACK reaches it. alice's `IKE_AUTH` can therefore reach bob before
  bob's load, which is the same race with the roles swapped.

So `3e02741` is expected to move the window from alice-PRIMARY to alice-BACKUP
intervals, at a rate not yet known. Describing it as a fix for the mismatch
would get ahead of the evidence.

The new pin brings three further sources of `AUTH_FAILED` on this lane, each
visible in the logs:

- **New fail-closed paths.** Under `QkdAndPqcRequired`, arnika now installs a
  random key when a BACKUP interval ends with no `key_id`, when the PRIMARY
  gets no ACK, and when no PQC-HPKE key is available yet, as at start-up. Over
  VICI that is a random PPK, so the next reauthentication fails, and the adapter
  logs `PPK rotated` for it as for any write. arnika logs each one as
  `msg="configuring a random PSK to invalidate the WireGuard session"` (the
  wording is upstream's, whatever the writer).
- **Start offsets, drift and single-node restarts.** Each arnika process
  counts its intervals from its own start (`main.go:327-333`), the election
  is an HMAC of that count, and a BACKUP interval that ends without a
  `key_id` now fails closed (`main.go:409-418`). Two processes started at
  different moments therefore disagree about which interval a `key_id`
  belongs to. From reading the code: for each tick, let $`d`$ be the
  BACKUP's boundary minus the PRIMARY's and $`t_{\mathrm{KMS}}`$ the
  PRIMARY's KMS fetch time. For $`d`$ below about a second, the chance that
  the PRIMARY's `key_id` reaches the BACKUP before the BACKUP's own boundary
  ("early") is roughly $`\min(1, \max(0, d - t_{\mathrm{KMS}}) / 1\,\mathrm{s})`$,
  since the PRIMARY sends at the next whole second after its fetch; the send
  also waits for the PSK build. An early `key_id` is counted in the BACKUP's
  previous interval, and the BACKUP fails closed at the end of the current
  interval only if the next interval's `key_id` is not early too, which in
  practice means at its BACKUP-to-PRIMARY transitions. That is an inference,
  not a measurement
  ([`BUILD.md` 7.3](BUILD.md#73-starting-arnika-on-the-interval-boundary)).
  Observed in one unaligned local two-node run of this lane on 2026-09-26,
  about 6 minutes long, with bob's arnika started about 0.25 s after
  alice's: the offset went from about 255 ms to about 217 ms over 12
  intervals, bob received early `key_id`s in intervals 2 to 8, 10 and 11, and
  it invalidated only at the end of intervals 8 and 11, each followed by an
  interval in which bob was PRIMARY. Each time bob logged `no key_id from the
  peer`, then the invalidation line above, and held a random PPK for about
  0.85 s. No reauthentication fell inside those windows, so no `AUTH_FAILED`
  followed. That is an observation from one short run, not a measurement.
  This lane's entrypoint is **deliberately not aligned** to an interval
  boundary: it starts arnika as at v0.1.0, when compose also started the two
  nodes together, about 30 ms apart on the live demo, so both arms below run
  the same entrypoint start behaviour, and whatever this path does under the
  start offset is measured rather than hidden. The offset itself is measured
  in each arm, not assumed equal (see the measurement below). The WireGuard
  lane's entrypoint does align, which restores the start synchronisation
  that lane had before 0.2.0, but alignment fixes the offset only at the
  start: each ticker re-bases after its own processing, so the offset wanders
  by milliseconds per interval, as in the run above. A node restarted alone
  starts its count again at 0 while its peer's does not, the two elections
  stop being complementary, and in each interval where both come out BACKUP
  both ends fail closed. That residual is #51's behaviour and is to be raised
  there with a measurement; the operating rule meanwhile is to recreate both
  nodes of a pair together. Neither the WireGuard lane's alignment nor the
  rule is a mitigation of the race above, and neither is claimed to change
  it.
- **The PQC-HPKE read gap.** Each peer reads the latest published PQC-HPKE key
  when it builds its PSK: the PRIMARY before it sends the `key_id`
  (`main.go:369`), the BACKUP after its `dec_keys` request (`main.go:316-324`).
  The two reads are therefore apart by the `key_id` delivery plus a KME round
  trip, and a round that publishes between them gives the peers different
  keys until the next rotation. Upstream's `docs/pqc-hpke.md` puts the
  probability at the read gap over the round interval and calls closing it an
  open design question. The symptom is the same `MAC mismatched`; comparing
  the two nodes' `msg="round agreed a fresh PQC key" round=N` lines is what
  separates it from the race.

**The before/after measurement is planned, not done.** Two arms of 168 hours
each on the same host: arm A at `3a8cc13` under the configuration that
preceded this change, arm B at `f4cf9ba`, each with both IPsec nodes recreated
in one step. Held constant: strongSwan 6.1.0, `IKE_PROPOSALS` and
`ESP_PROPOSALS`, `REAUTH_TIME`, `VICI_REAUTH_TIMEOUT`, `MODE`,
`ARNIKA_INTERVAL`, the two `ARNIKA_ID`s, alice as initiator, the health-check
ping, the KME backend, and the entrypoint's start behaviour: in both arms it
starts arnika as soon as the connection is loaded, with no wait for an
interval boundary. The start offset between the two nodes is not held
constant: arm B also drops the IPsec nodes' `depends_on` on the WireGuard
nodes, which changes the order in which compose starts them, so the report
measures the offset in each arm. What differs otherwise is the pin, with the
configuration it needs, which is what is measured: arm B's arnika fails a
BACKUP interval without a `key_id` closed and arm A's does not, so
invalidations from the start offset and its drift can occur in arm B only.
They are counted as invalidations, not as the race, and they are a result of
the comparison, not a difference to remove from it. The counting rules are
fixed before either run, and `scripts/ppk_race_report.py` applies them to both
arms' logs:

- rotations are alice's `PPK rotated (id=` lines, less the invalidations;
- failures are alice's `N(AUTH_FAILED)`, with bob's `MAC mismatched` as
  corroboration;
- each failure belongs to the interval of alice's last rotation before it, and
  is split by alice's role in that interval (`PRIMARY[11]` or `BACKUP[11]` at
  the old pin, `role=primary` or `role=backup` on the `key_id` lines at the
  new one);
- each is classed as an invalidation, a start-up failure, the race (bob's
  `MAC mismatched` before bob's own `PPK qkd-alice-N loaded`, compared within
  bob's log only), an input divergence, or a lag (bob never loads that
  generation);
- any window in which either node restarted is excluded;
- beside the counts, the report prints the offset between the two nodes'
  interval boundaries over time, each PRIMARY's KMS fetch time, how many
  `key_id`s arrived before the receiver's own boundary, and any tick in which
  their interval numbers differ or both hold the same role, and its JSON
  output keeps these tick by tick, so that the invalidations can be read
  against the offset, the fetch time and the counters rather than against an
  expectation. At the previous pin a BACKUP logs its boundary only when no
  `key_id` has reached it first, so arm A's offsets are a biased sample.

The 8.8-day figure above predates the 2026-09-25 health-check ping, so it is
context for arm A, not a substitute for it. The results, with their windows
and pins, belong in this section.

### 2026-08-27: the CI failures are a DIFFERENT fault from the race above

The unconditional timeline dump added to the `ipsec` CI job finally produced the
discriminating observation, and it rules out both standing hypotheses. CI run
`33071519309`, 2 failures on each node, aligned by container timestamp:

| time | `alice-ipsec` (drives reauth) | `bob-ipsec` (responder) |
|---|---|---|
| 12:28:01 | loaded ppk#2, rotate#2 -> SA[3] | loaded ppk#2, rotate#2 -> SA[3] |
| **12:28:31** | loaded ppk#3, rotate#3 | **nothing** -> MAC mismatched, AUTH_FAILED |
| **12:29:01** | loaded ppk#4, rotate#4 | **nothing** -> MAC mismatched, AUTH_FAILED |
| 12:29:31 | loaded ppk#5, rotate#5 -> SA[6] | loaded ppk#**3**, rotate#**3** -> SA[6] |

Bob logged **no load, no rotation and no invalidation for two whole intervals**.
Its own generation counter advanced 2 -> 3 across 90 s while alice's advanced
2 -> 5, so bob was running roughly two intervals behind. The MAC mismatch is the
**consequence** -- alice authenticating with generation 3 against a responder
still holding generation 2 -- not the fault.

That is neither hypothesis:

* **Not the rotation race** documented above. The gap is 60 s, not
  milliseconds, and it resolves by bob catching up.
* **Not a systematic mismatch.** Rotations 5-8 succeed with no intervention.

The remaining shape is that bob was **BACKUP** for those intervals and never
received the `key_id` from alice, so it produced no key and logged only
`[REQ] BACKUP for interval N, waiting for key_id from peer` -- a line the CI
alternation did not match, which is precisely why nine previous dumps showed a
hole where a cause should be. **This is not yet proven.** The alternation now
covers arnika's own key-acquisition path (`[SND]`/`[RCV]`/`[REQ]`/`[STOP]`,
`no ACK after`, `failed to retrieve QKD key`, `failed to send key_id`,
`waiting for key_id`, `psk mismatch`), so the next failing run should name it.

One line is worth watching in particular. On failure `setPSK` calls
`InvalidateTunnel()`, which installs a **random** PPK the peer cannot match and
logs `[STOP] configure random PSK to invalidate WireGuard session`. That would
produce an identical `AUTH_FAILED`, so its presence or absence separates
"arnika gave up loudly" from "arnika never ran the interval at all". It is
absent from the lines captured above -- but the old alternation would not have
matched it either, so that absence is not evidence yet. It will be on the next
failing run.

**Still CI-only on 2026-09-25.** The 8.8-day live run above shows no interval in
which BACKUP waited without a `key_id` (bob's `PRIMARY` 12,536 plus `[RCV]`
12,713 is exactly its 25,249 rotations) and no `[STOP]`, `no ACK`, `failed to
retrieve`, `psk mismatch` or `random PSK` line in any of the four containers.
So this fault has not been seen outside CI, and its cause is still open --
narrowed on the same day, below: the QKD half, the generation numbering and
the bootstrap credential are ruled out for the latest failing run.

**2026-09-25: the next failing run named it, and it is not the `key_id`
handover.** The `ipsec` job failed on a pull request that touched
only frontend code and documentation, with **8 authentication failures in 17
rotations on both nodes -- intervals 0 to 7, every one, then 9 clean.** With
the widened alternation, both nodes' dumps show every failing interval
complete:

| interval | sender (`[SND]`) | receiver (`[RCV]`, same `key_id`) | both load generation |
|---|---|---|---|
| 0 | bob | alice, +1 ms | `qkd-alice-1` / `qkd-bob-1` |
| 1, 2, 4, 7 | alice | bob, +1 ms | $`n+1`$ within 2-5 ms |
| 3, 5, 6 | bob | alice, +1 ms | $`n+1`$ within 2-5 ms |

No `[STOP]`, `no ACK`, `failed to retrieve`, `failed to send key_id`, `psk
mismatch` or `random PSK` line appears on either node, and no BACKUP interval
waits without its `[RCV]`. So both sides fed HKDF the **same QKD half** in every
failing interval -- the same `key_id` resolved through the same pair of KMEs --
and the static IKE PSK is the one that authenticates cleanly from interval 8
onward. The bootstrap credential is not it either: both nodes unloaded it at
11:26:49, before the first failure, and every rotation unloads the previous
generation, so one credential answered the `PPK_ID` throughout.

This is also a **different signature** from the runs of 2026-08-28, which
carried `failed to retrieve QKD key` (the empty-pool gate since fixed in
`keypool.py`); there is no retrieval failure here. **The one HKDF input this
dump cannot see is the PQC half written by the Rosenpass sidecar.** The
2026-08-23 failing run (4 failures in 10 rotations) found the two PQC halves
byte-identical and excluded them for that run; the evidence is in
[`VERIFICATION_CHECKLIST.md`](../VERIFICATION_CHECKLIST.md) row 2.13. It does
not exclude them for this one, whose failures stop about four minutes after
start. So the PQC half is the input not yet ruled out, not a finding.
Capturing a per-write fingerprint of `pqc.psk` on both nodes would decide it.
It is not done yet: written to the container logs, the fingerprint would be
served by the WebUI, so it has to go to a channel nothing serves, such as a CI
artifact.

**2026-09-26: that suspect no longer exists in this form.** From the `f4cf9ba`
pin on, this lane runs no Rosenpass and keeps no PQC key on disk: the PQC half
is agreed by the two arnika instances themselves, round by round, and held in
memory. So there is no `pqc.psk` to fingerprint. The PQC half is still not
ruled out for the 2026-09-25 run, which was at the old pin; for new failing
runs, the candidate on that side is the PQC-HPKE read gap described in the
2026-09-26 section above, and each node's list of
`msg="round agreed a fresh PQC key" round=N` lines is what to compare.

Widening the overlap does **not** fix it. Keeping both generations loaded makes
two credentials answer one `PPK_ID`, and charon's `get_ppk_r` resolves that to
exactly one key with no way to try the other -- so the ambiguity replaces the
race with a coin flip. That is not hypothetical: it is what the un-retired
bootstrap credential did, and it produced 4 authentication failures in 9
rotations until the bootstrap was unloaded.

### The actual fix

**Not implemented as of 2026-09-26**: the lane still uses one static
`PPK_ID`, `ppk-qkd@pqcqkd.local`, on both nodes. It is one of two candidate
mitigations for the alice-BACKUP exposure the new pin is expected to create;
the other is delaying the initiator's reauthentication. Neither is taken
before the measurement above shows that exposure, and neither can use the
interval's role or `key_id`: the adapter sees only the 32 bytes `SetPSK`
hands it.

Scope the `PPK_ID` to the generation, e.g. `ppk-qkd-26@pqcqkd.local`. RFC 8784
has the initiator send `PPK_ID` in IKE_AUTH and the responder look it up, so the
responder can hold several generations under distinct ids and resolve exactly
the one the initiator used. The overlap then becomes unambiguous rather than a
coin flip, and the race disappears.

The obstacle is that `ppk_id` is connection configuration, so each rotation
would need a `load-conn` carrying the new id in addition to `load-shared`. That
is available over VICI and is the natural next change; it is not made here
because it alters the connection on every rotation and wants its own two-node
soak test, with a CI assertion that each rotation uses a new id.


## Appendix: SP 800-227 and this project's key combiner

This appendix is the one place the combiner analysis lives; `references.md`,
`threat-model.md` and the adapter README point here.

SP 800-227 (Final, September 2025) mentions QKD exactly once, in the *General
multi-algorithm schemes* discussion of **§4.6.1**:

> "such schemes could potentially include pre-shared keys or shared secrets
> established via quantum key distribution. Still, most multi-algorithm schemes
> will likely include a step in which a series of shared secrets are combined
> via a key combiner algorithm of a form similar to KeyCombine above. In those
> cases, an approved key combiner discussed in Sec. 4.6.2 **shall** be used."

So the requirement ("shall") is stated in §4.6.1, and §4.6.2 describes the
approved combiners it points to, drawn from SP 800-56C and SP 800-133. Neither
section *permits* the construction so much as sets a bar for it: including a
QKD secret is acknowledged as possible, and doing so obliges the design to use
an approved combiner. Both source documents are moving -- NIST announced a
revision of SP 800-56C on 2026-01-06 to admit KEM shared secrets in $`Z`$ and
more flexible hybrid formatting, and SP 800-133 Rev. 3 is in draft -- so this
analysis is against the current revisions ([`references.md`](references.md),
NIST table).

**What arnika does**, from `submodules/arnika/kdf/kdf.go` (byte-identical at
the `f4cf9ba` pin and at the previous `3a8cc13`; arnika#51 did not touch it):

```go
hkdf := hkdf.New(sha3.New256, combined, nil, nil)
```

i.e. `HKDF-SHA3-256(QKD ‖ PQC)` with a nil salt and no info string. What
changed with #51 is the second input, not the combiner: `PQC` is now the
32-byte export of arnika's own PQC-HPKE round, not the Rosenpass output file.

**Where that stands against the requirement, precisely:**

- The **two-step shape is right**. SP 800-56C's form is
  $`K \leftarrow \mathrm{Expand}(\mathrm{Extract}(\text{salt}, Z), \text{FixedInfo})`$,
  and HKDF is exactly Extract-then-Expand. A nil HKDF salt is not a missing
  salt: RFC 5869 §2.2 defines it as HashLen zero bytes, which is the default
  salt SP 800-56C permits. An earlier version of this analysis said arnika "supplies neither
  salt nor FixedInfo" — the salt half of that carries no weight.
- **FixedInfo is genuinely absent.** No domain separator, no protocol or party
  binding. That is a real gap against the approved forms §4.6.2 describes, and
  it is the one to state. It is unchanged by #51, because `kdf/kdf.go` is. (The
  PQC-HPKE round binds a context string and the round number into its own
  HPKE key schedule, but that is inside the PQC input, not FixedInfo in the
  combiner.)
- **The inputs are still not shown to be approved-KEM-derived; the reason
  changed.** Until 2026-09-26 the PQC input came from Rosenpass v0.2.3, whose
  Classic McEliece 460896 + Kyber512 is not an approved KEM (Kyber512 is the
  pre-standardisation parameter set, not FIPS 203). That objection no longer
  applies to this combiner. The input is now a 32-byte HPKE export: HPKE in
  Base mode (RFC 9180) with the KEM MLKEM1024-P384 (codepoint 0x0051 of
  draft-ietf-hpke-pq, not yet an RFC), the KDF HKDF-SHA384 and an export-only
  AEAD. ML-KEM-1024 is FIPS 203 and P-384 ECDH is an approved scheme, but
  arnika does not receive either shared secret. The hybrid KEM first hashes the
  two together with SHA3-256, along with the P-384 ciphertext, the P-384 public
  key and a label (Go's `crypto/hpke`, following that draft), and HPKE's key
  schedule and `Export` then derive the 32 bytes through HKDF-SHA384 with their
  own labels. Neither step is one of the SP 800-56C or SP 800-133 forms §4.6.2
  names, the KEM identifier comes from an unfinished draft, and SP 800-227 does
  not say whether a value several derivations downstream of an approved KEM
  counts as a shared secret "generated from ... an approved KEM" for combiner
  (14). So this document does **not** call the input approved. What can be
  said is narrower: the PQC input now rests on FIPS 203 ML-KEM-1024 rather
  than on Kyber512, and whether the construction around it qualifies is open.
  The QKD input is not a KEM output at all, as before.
- **Concatenation itself is fine here.** §4.6.2 warns that concatenating inputs
  is unsafe when the lengths can vary; both inputs here are fixed at 32 bytes,
  so the ambiguity it warns about cannot arise.

Adding a FixedInfo string is a wire-format change affecting both ends, so it is
an upstream decision for arnika rather than something to patch locally.

# arnika strongSwan/VICI key-writer adapter

An [arnika](https://github.com/arnika-project/arnika) key-writer that delivers
arnika's HKDF-SHA3-256(QKD || PQC-HPKE) secret to strongSwan as an **RFC 8784
Post-quantum Preshared Key**, over charon's VICI socket.

Upstream arnika writes keys to a WireGuard interface via netlink. This adapter
implements the same key-writer port against strongSwan instead, so the same
key-agreement machinery drives an IKEv2 lane.

The PQC half is arnika's own key agreement with the peer: HPKE Base mode
(RFC 9180) with KEM MLKEM1024-P384 (codepoint 0x0051, from
draft-ietf-hpke-pq, not yet an RFC), KDF HKDF-SHA384 and the export-only AEAD.
ML-KEM-1024 + P-384 is a hybrid KEM. No Rosenpass runs on this lane, and no
key file is mounted.

## The pinned arnika is an open PR

`submodules/arnika` is pinned to `f4cf9ba`, the head of upstream PR #51, which
is **open and not merged** (dated 2026-09-24). It is re-pinned to the merge
commit once #51 merges. Until then, "upstream" in this file means that PR head,
not arnika's `main`.

## The port: one method

```go
type keyWriterRepository interface {
    SetPSK(psk []byte) error
}
```

That is the whole contract at `f4cf9ba` (`services/keywriter.go`). Three things
moved out of the adapter with it:

- **Invalidation.** `KeyWriterService.InvalidateTunnel` generates 32 random
  bytes and calls `SetPSK` with them. Over VICI that is exactly what this
  adapter's own `InvalidateTunnel` used to do: load a PPK the peer cannot match
  and reauthenticate, so the next IKE_AUTH fails visibly instead of traffic
  continuing under the superseded key. The adapter no longer has the method,
  and a test fails if it grows one again.
- **The mutex.** `KeyWriterService.mu` serialises every write, including the
  ones invalidation makes, so the adapter's own lock is gone.
- **Base64.** The key arrives as raw bytes, which arnika clears as soon as
  `SetPSK` returns. The adapter copies it into the VICI message and keeps no
  reference. The one `string(raw)` copy it makes is forced by govici v0.8.2,
  whose `Message.Set` stores only `string`, `[]string` or `*Message`.

The behaviour is otherwise unchanged by the port, and so is every log line but
one. The adapter's own `[WARN] [VICI] invalidating tunnel: ...` line went with
its `InvalidateTunnel`; arnika now logs the invalidation itself, as
`configuring a random PSK to invalidate the WireGuard session` (the wording is
arnika's and names WireGuard whatever the writer), followed by the adapter's
ordinary `PPK rotated` line for the random key. Nothing in this repository
matched the removed line.

## Why a PPK and not an IKEv2 PSK

An IKEv2 PSK is consumed only when computing the IKE_AUTH AUTH payload
(RFC 7296 section 2.15). It never enters `SKEYSEED`, so a QKD key delivered as a
PSK contributes nothing against a harvest-now-decrypt-later adversary.

RFC 8784 instead mixes the PPK into the key schedule, deriving `SK_d`, `SK_pi`
and `SK_pr` through `prf+` keyed by the PPK. `SK_d` is the root of every Child
SA KEYMAT and of all later rekeys, so an attacker must break **both** the
(EC)DH/KEM exchange and obtain the QKD key.

The derivation is written out, in LaTeX, in
[`docs/vici-ppk.md`](../../docs/vici-ppk.md) -- along with the full argument and
the known limitations. It is deliberately not repeated here: it was previously
duplicated as ASCII art in this file, which is both the last un-converted
formula in the repository and a second copy free to drift from the first.

## Why rotation needs a reauthentication

`load-shared` writes into charon's in-memory credential set and touches no SA.
An IKEv2 rekey is a CREATE_CHILD_SA exchange carrying no AUTH payload, so it
never re-reads credentials. Only a full reauthentication re-runs
IKE_SA_INIT + IKE_AUTH and therefore consumes the new PPK.

RFC 8784 reinforces this: the PPK applies to the initial IKE SA only and
"MUST NOT be used when these subkeys are calculated as a result of IKE SA
rekey". So `rekey_time = 0` and reauthentication is the rotation mechanism.
`charon.make_before_break` has been on by default since 6.0.0, so this does not
interrupt traffic.

## Building

The package and file layout follow upstream's `KEYCONTROL.md` ("Naming and
File Layout Conventions"):

| Path in this directory | Path in the assembled arnika tree | Build tag |
|---|---|---|
| `repositories/swanvici/vici.go` | `repositories/swanvici/vici.go` | none: always compiled, vetted and tested |
| `repositories/swanvici/vici_test.go` | `repositories/swanvici/vici_test.go` | none |
| `wire_strongswan_vici.go` | `wire_strongswan_vici.go` (root, `package main`) | `strongswan_vici` |

The build tag does not follow them. `KEYCONTROL.md` names writer tags in the
`wireguard_<backend>` form, and this adapter keeps its existing tag
`strongswan_vici`. The wiring file is still `wire_` plus the tag verbatim.
Renaming the tag is left to the upstream adapter PR, where it would change
together with the default writer's negation described below.

The package is `swanvici`, one package per adapter like upstream's `wgnetlink`
and `wgmikrotik`, and not `vici`, which is govici's own package name.
`Repository` and `NewRepository` match `wgmikrotik` and `wgnetlink`. `Config`
is this adapter's own: upstream's constructors take positional arguments, and
this one takes a struct because it has eight settings.

```sh
sh services/arnika-vici/build.sh <arnika-src> <adapter-src> <output-binary>
```

`build.sh` overlays this directory onto a copy of the arnika tree, narrows
`wire_wireguard_netlink.go`'s build tag (see below), pins
`github.com/strongswan/govici@v0.8.2`, and builds with
`CGO_ENABLED=0 GOEXPERIMENT=runtimesecret`. arnika hardens key material with
`runtime/secret`, which needs Go >= 1.26.

It refuses to run, before copying anything, if the arnika tree already contains
`repositories/swanvici` or `wire_strongswan_vici.go`: an upstream file of the
same name is something to compare, not to overwrite.

Set `ARNIKA_VICI_VET_AND_TEST=1` to also run, inside the same prepared tree:

- `go vet -tags strongswan_vici ./...`
- `go test -tags strongswan_vici ./repositories/swanvici/... -v` (no `-race`:
  it needs cgo, and `CGO_ENABLED=0` is upstream's setting)
- `go build .` with no tag, which must still build the default netlink writer
- `go build -tags "<writer> strongswan_vici"` for each of upstream's writer
  tags (`wireguard_netlink`, `wireguard_mikrotik`, `wireguard_netlink_netns`),
  which must each FAIL, and fail on `getKeyWriterService redeclared` rather
  than on some unrelated error. This mirrors upstream's own "Two writer tags
  must never compile together" CI check.

That is how CI runs it: all of it depends on the build-tag change, so none of
it can be done against an unmodified checkout.

### The upstream build-tag change

Upstream selects the netlink writer, at the pinned commit, in
`wire_wireguard_netlink.go` with:

```go
//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)
```

The line is unchanged from the previous pin (`3a8cc13`); PR #51 only renamed the
file from `wireguardnetlink.go`.

The trailing negation means the file is compiled in for any adapter tag it
does not name, so `-tags strongswan_vici` yields two definitions of
`getKeyWriterService`. `build.sh` adds the missing conjunct in its temporary
tree:

```go
//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns && !strongswan_vici)
```

`build.sh` asserts on the exact upstream line, and on the file existing at
all, and fails loudly if either changes, so a submodule bump cannot silently
produce a binary with the wrong adapter.
`tests/test_the_build_tag_narrowing_is_exhaustive.py` derives the set of
writers from the pinned tree, so a writer upstream adds later fails there even
though `build.sh`'s pairwise list above does not name it.

A standalone patch proposing this narrowing upstream was carried here until
2026-09-25 and was never submitted. It is withdrawn: upstream's `KEYCONTROL.md`
now tells whoever adds a writer to extend the default's negation themselves
("Update the default constraint", step 3 of "Adding a new key writer"), so the
change belongs in an adapter PR, not on its own.

## Configuration

All variables are mandatory **in the adapter**: `getKeyWriterService` returns an
error for an unset `VICI_REAUTH_TIMEOUT` or `VICI_IKE_ROLE`, and `swanvici.Config`
documents every field as required. The reasoning is that every plausible default
silently masks a misconfiguration that still looks like a working tunnel.

Note what that does and does not guarantee. The layers above the adapter supply
values anyway, so in the shipped configuration the adapter never sees three of
these unset:

| Where | Default |
|---|---|
| `nodes/strongswan/entrypoint.sh:26` | `VICI_SOCKET=/var/run/charon.vici` |
| `docker-compose.strongswan.yml:52` | `VICI_REAUTH_TIMEOUT=10s` |
| `docker-compose.strongswan.yml:40` | `REAUTH_TIME=300s` |

Those are deployment conveniences rather than adapter behaviour, but the
distinction matters: an operator reading "there are no defaults" and then
omitting `VICI_REAUTH_TIMEOUT` from their own compose file gets 10 s, not an
error. `WIREGUARD_INTERFACE` and `WIREGUARD_PEER_PUBLIC_KEY` are also defaulted
to the placeholder `unused-by-vici-writer` in `nodes/strongswan/entrypoint.sh`,
for the separate reason recorded under Known gaps below.

| Variable | Meaning |
|---|---|
| `VICI_SOCKET` | charon's VICI unix socket |
| `VICI_CONNECTION` | swanctl connection name to reauthenticate |
| `VICI_CHILD` | CHILD_SA name to initiate when no IKE_SA exists |
| `VICI_PPK_ID` | RFC 8784 PPK identity; stable, the material behind it rotates |
| `VICI_CREDENTIAL_PREFIX` | namespaces the `load-shared` ids this adapter owns |
| `VICI_BOOTSTRAP_ID` | the pre-QKD credential, unloaded after the first rotation |
| `VICI_REAUTH_TIMEOUT` | bounds one rotation; must be shorter than `INTERVAL` |
| `VICI_IKE_ROLE` | `initiator` or `responder`; the two peers must differ |

### arnika settings the node entrypoint enforces

These are arnika's, not the adapter's, but the node checks them before arnika
starts because arnika's own checks are either later or looser:

| Variable | Rule in `nodes/strongswan/entrypoint.sh` | Why |
|---|---|---|
| `ARNIKA_PSK` | at least 32 bytes, and not the `.env.example` placeholder | the bootstrap PSK and PPK are derived from it before arnika runs; the placeholder is 37 bytes and passes arnika's own length check |
| `PQC_ENABLED` | exactly `true` or `false` | arnika treats every value but `true` as off; the compose file sets it once, in the shared anchor, so both peers agree |
| `LOG_LEVEL` | unset or `info`; exported as `info` | see below |

The adapter logs through the standard `log` package. arnika installs a
`log/slog` text handler with `slog.SetDefault`, which routes those lines into
the handler at INFO. A rotation line then has the form
`time=<RFC 3339> level=INFO msg="[INFO] [VICI] PPK rotated (id=... ppk_id=... bytes=32)" arnika_id=<ARNIKA_ID>`,
where `arnika_id` is the attribute arnika adds to every record once its
identity is set (`setLogIdentity`, `logging.go`). The format strings are
unchanged, so the WebUI's rotation counter and the CI `ipsec` job's greps still
match. Two consequences:

- `LOG_LEVEL=warn` or `error` would drop every adapter line, including every
  `PPK rotated`, while the tunnel kept rotating.
- The adapter's `[WARN]` and `[ERROR]` lines are emitted at slog level INFO;
  only the text prefix says otherwise. Moving the adapter to an injected
  `*slog.Logger` is deferred until the before/after measurement of the
  intermittent PPK mismatch is done, so that measurement compares like with
  like.

### `VICI_IKE_ROLE`

The two peers share **one** IKE_SA, so exactly one of them owns it: initiates
it, reauthenticates it after a rotation, and restarts a closed child. The
responder does none of those and only answers.

Both peers still *load* every rotated PPK — that is what lets the responder
answer the initiator's IKE_AUTH. Loading happens on both sides; driving happens
on exactly one.

This is independent of arnika's PRIMARY/BACKUP election, which alternates every
interval and decides who *generates* the key, not who owns the SA.

Getting this wrong does not produce an obvious failure. With two drivers, each
rotation triggers two make-before-break reauthentications that each create a
replacement SA, and the SA count climbs by roughly one per rotation while the
tunnel keeps passing traffic. A two-node run reached 140 concurrent IKE_SAs in
nine minutes before this was found.

## Rotation sequence

1. `load-shared` the new generation (`type=ppk`, both generations now loaded)
2. `get-shared` to confirm it landed — `unload-shared` reports success for ids
   that never existed, so this is the only reliable existence check
3. `list-sas`, then `rekey` **that one SA by unique id** with `reauth=yes`
   (or `initiate`, if no SA exists yet)
4. `unload-shared` the previous generation
5. `unload-shared` the bootstrap credential, once

Step 3 selects by `ike-id`, not by connection name. Selecting by connection name
makes charon reauthenticate *every* SA on the connection, and since
make-before-break builds each replacement before dropping the original, N SAs
become 2N.

Step 5 matters more than it looks: the bootstrap credential answers the **same**
`PPK_ID` as every rotated credential, so leaving it loaded means two keys answer
one IKE_AUTH lookup and charon's choice is unspecified. It is derived from
`ARNIKA_PSK` and contains no QKD material, so a lane that silently selected it
would present as PPK-protected while carrying none of the quantum contribution.

### Restart reconciliation

`generation` and `loadedID` are process-local. Without reconciliation a restart
begins again at `<prefix>-1` while every `<prefix>-N` from the previous run stays
registered forever, since `SetPSK` only unloads what *this* process installed.

At construction the adapter calls `get-shared`, adopts the highest surviving
generation, and unloads the older ones. Adopt rather than clear: that key
material came from a QKD exchange that already happened and cannot be re-derived
here, and it is what the peer most likely still holds. Credentials that do not
match the prefix are left strictly alone.

## Operational note

**Never run `swanctl --load-creds` against a daemon using this adapter.** It
performs a destructive sync — `get-shared` followed by `unload-shared` for every
vici-injected id absent from `swanctl.conf` — which silently deletes the
rotating QKD PPK. The node entrypoint runs it exactly once, before
`--load-conns`, to install the bootstrap credentials.

## Known gaps

- The rotation does not block until the reauthenticated IKE_SA reaches
  ESTABLISHED. `rekey` returns once charon has queued the reauthentication.
  This is tolerable because both generations stay loaded across the gap, but
  closing it properly means subscribing to the `ike-updown` event stream.
- **arnika's KDF is not shown to meet the SP 800-227 combiner requirement.**
  SP 800-227 §4.6.1 requires ("shall") an approved key combiner of the kinds
  described in §4.6.2 (SP 800-56C or SP 800-133). The gaps are analysed in one
  place,
  [`docs/vici-ppk.md`, "Appendix: SP 800-227"](../../docs/vici-ppk.md#appendix-sp-800-227-and-this-projects-key-combiner),
  rather than in a second copy here that could drift from it. At `f4cf9ba` the
  first gap is unchanged: `kdf/kdf.go` still calls HKDF with no FixedInfo. The
  second gap's premise has changed: the PQC input is no longer a Rosenpass
  key (Classic McEliece 460896 + Kyber512) but an HPKE export from the
  MLKEM1024-P384 hybrid KEM. Whether that export satisfies §4.6.2's
  approved-KEM premise has not been re-analysed yet, so nothing here claims
  that it does. The adapter stays bit-compatible with upstream's KDF; changing
  it is a wire-format break for upstream to decide on.
- **The intermittent PPK mismatch is not resolved by this pin.** At `f4cf9ba`
  the PRIMARY writes its key only after the BACKUP acknowledges the key_id.
  Reading the code suggests that moves the exposed intervals from those where
  alice (the IKE initiator) is PRIMARY to those where she is BACKUP, rather than
  removing them. That is an inference from the code, not a measurement; a
  168-hour before/after measurement is planned. The adapter cannot see the
  arnika role or the key_id through `SetPSK([]byte)`, so any mitigation on this
  side would need a different port.
- **Observation (2026-09-26): fail-closed writes at role changes.** This comes
  from one unaligned local two-node run of the IPsec lane, about 6 minutes
  long, and is not a measurement. alice's arnika started about 0.25 s before
  bob's, because this lane's entrypoint does not align the start (below); that
  start gap is where the run's offset came from. At `f4cf9ba` each process
  counts intervals from its own start (`main.go` about :327-333), and a BACKUP
  interval that ends without a key_id fails closed (about :409-418). In that
  run every key_id alice sent as PRIMARY reached bob 0.13 to 0.15 s before
  bob's own boundary of that tick and was counted in bob's previous interval:
  bob received such early key_ids in intervals 2-8, 10 and 11. bob
  invalidated only at the ends of intervals 8 and 11, each followed by a
  bob-PRIMARY interval, so no next key_id came to fill the gap. Each time bob
  logged `no key_id from the peer`, then `configuring a random PSK to
  invalidate the WireGuard session`, and held a random PPK for about 0.85 s,
  until its own PRIMARY interval's key arrived.

  The IPsec lane does not align the arnika start to the wall clock, on
  purpose. `nodes/strongswan/entrypoint.sh` starts arnika as v0.1.0 did,
  without waiting for an interval boundary; compose starts the two nodes
  together, about 30 ms apart on the live demo host. The 168-hour
  before/after measurement compares this lane, so both arms keep that start
  timing, and whatever #51's fail-closed path does under it is part of what
  the measurement records. Only the WireGuard lane's entrypoint aligns its
  start, which restores the synchronisation that lane got from waiting for
  the first Rosenpass key; that lane is not the measured one. The reasons,
  the WireGuard lane's own unaligned runs and the operating rule are in
  [`docs/BUILD.md` 7.3](../../docs/BUILD.md#73-starting-arnika-on-the-interval-boundary).
  Neither lane's start timing is a mitigation of the rotation race above.

  The mechanism below is an inference from the code and that one run, not a
  measurement. The offset of a tick is bob's boundary minus alice's, as
  `scripts/ppk_race_report.py` prints it. Per tick, let $`d`$ be the BACKUP's
  boundary minus the PRIMARY's boundary: the offset itself when alice is
  PRIMARY, and the offset with its sign flipped when bob is. The PRIMARY sends
  its key_id at the next whole second after its own KMS fetch (about :349),
  and the send also waits for the PSK build. For $`d`$ below about a second,
  the chance that the PRIMARY's key_id arrives before the BACKUP's boundary
  ("early") is roughly
  $`\min(1, \max(0, d - t_{\mathrm{KMS}}) / 1\,\mathrm{s})`$, with
  $`t_{\mathrm{KMS}}`$ the PRIMARY's KMS fetch time, if over a long run the
  fraction of a second at which the fetch ends is spread evenly. An early
  key_id is counted in the BACKUP's previous interval. The BACKUP fails closed
  at the end of the current interval only if the next interval's key_id is not
  early too, which in practice means at its BACKUP-to-PRIMARY transitions. An
  aligned start would fix the offset at the start only: each ticker re-bases
  after its own processing (`ticker.Reset` at the top of the loop, about
  :327-333), so the offset wanders by milliseconds per interval. In the run
  above it went from about 255 ms to about 217 ms over 12 intervals and
  reached about 265 ms in between.

  `scripts/ppk_race_report.py` prints, for the two ends over the whole
  window, the boundary offset and its trend, each PRIMARY's KMS fetch time,
  how many key_ids reached the receiver before its own boundary, every tick
  whose interval numbers differ between the ends, and, per segment of the
  window, the early key_ids beside the `no key_id from the peer`
  invalidations. With `--json` it also lists every paired tick: its offset,
  $`d`$, both ends' interval numbers and roles, the PRIMARY's fetch time,
  whether its key_id was early, and how each BACKUP interval ended.

  The interval numbers differ after only one node of a pair restarts, or
  after two starts more than half an interval apart. The per-interval roles
  then stop being complementary, and in an interval where both ends are
  BACKUP both fail closed. That is upstream #51 behaviour, to be raised there
  with a measurement; both nodes of a pair are recreated together. None of
  this addresses the intermittent mismatch above, and nothing here says these
  writes caused it. Each of these writes logs `PPK rotated` like a rotation.
  `scripts/ppk_race_report.py` counts it as an invalidation write and not as a
  rotation, and files an authentication failure against it under C1
  (invalidation).
- `WIREGUARD_INTERFACE` and `WIREGUARD_PEER_PUBLIC_KEY` must still be set even
  though this adapter ignores them; upstream's config parser requires them
  unconditionally. Making them conditional on the selected adapter is a
  follow-up for the adapter PR.

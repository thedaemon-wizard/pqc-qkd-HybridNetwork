# arnika strongSwan/VICI key-writer adapter

An [arnika](https://github.com/arnika-project/arnika) key-writer that delivers
the HKDF(QKD || PQC) secret to strongSwan as an **RFC 8784 Post-quantum
Preshared Key**, over charon's VICI socket.

Upstream arnika writes keys to a WireGuard interface via netlink. This adapter
implements the same `keyWriterRepository` port against strongSwan instead, so
the same key-agreement machinery drives an IKEv2 lane.

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

`strongswanvici.go` carries `//go:build strongswan_vici`, mirroring upstream's
one-build-tagged-file-per-adapter layout.

```sh
sh services/arnika-vici/build.sh <arnika-src> <adapter-src> <output-binary>
```

`build.sh` overlays this directory onto a copy of the arnika tree, narrows
`wireguardnetlink.go`'s build tag (see below), pins
`github.com/strongswan/govici@v0.8.2`, and builds with
`CGO_ENABLED=0 GOEXPERIMENT=runtimesecret` — arnika hardens key material with
`runtime/secret`, which needs Go >= 1.26.

Set `ARNIKA_VICI_VET_AND_TEST=1` to also run `go vet` and `go test` with the
tag, inside the same prepared tree. That is how CI runs it: both depend on the
build-tag change, so they cannot be done against an unmodified checkout.

### The upstream build-tag change

Upstream selects the netlink writer, at the pinned commit, with:

```go
//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)
```

The trailing negation means the file is compiled in for any adapter tag it
does not name, so `-tags strongswan_vici` yields two definitions of
`getKeyWriterService`. `build.sh` adds the missing conjunct in its temporary
tree:

```go
//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns && !strongswan_vici)
```

`build.sh` asserts on the exact upstream line and fails loudly if it changes,
so a submodule bump cannot silently produce a binary with the wrong adapter;
`tests/test_the_build_tag_narrowing_is_exhaustive.py` fails too, rather than
skipping, if the writer files move -- upstream PR #51 renames them to
`wire_*.go`.

A standalone patch proposing this narrowing upstream was carried here until
2026-09-25 and was never submitted. It is withdrawn: upstream's `KEYCONTROL.md`
now tells whoever adds a writer to extend the default's negation themselves
("Update the default constraint", step 3 of "Adding a new key writer"), so the
change belongs in an adapter PR, not on its own.

## Configuration

All variables are mandatory **in the adapter**: `getKeyWriterService` returns an
error for an unset `VICI_REAUTH_TIMEOUT` or `VICI_IKE_ROLE`, and `ViciConfig`
documents every field as required. The reasoning is that every plausible default
silently masks a misconfiguration that still looks like a working tunnel.

Note what that does and does not guarantee. The layers above the adapter supply
values anyway, so in the shipped configuration the adapter never sees three of
these unset:

| Where | Default |
|---|---|
| `nodes/strongswan/entrypoint.sh:26` | `VICI_SOCKET=/var/run/charon.vici` |
| `docker-compose.strongswan.yml:44` | `VICI_REAUTH_TIMEOUT=10s` |
| `docker-compose.strongswan.yml:32` | `REAUTH_TIME=300s` |

Those are deployment conveniences rather than adapter behaviour, but the
distinction matters: an operator reading "there are no defaults" and then
omitting `VICI_REAUTH_TIMEOUT` from their own compose file gets 10 s, not an
error. `WIREGUARD_INTERFACE` and `WIREGUARD_PEER_PUBLIC_KEY` are also defaulted
to a placeholder at `entrypoint.sh:218-219`, for the separate reason recorded
under Known gaps below.

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
- **arnika's KDF does not meet the SP 800-227 combiner requirement.** SP 800-227
  §4.6.1 requires ("shall") an approved key combiner of the kinds described in
  §4.6.2 (SP 800-56C or SP 800-133). The gaps -- no FixedInfo, and a PQC input
  that does not come from an approved KEM -- are analysed in one place,
  [`docs/vici-ppk.md`, "Appendix: SP 800-227"](../../docs/vici-ppk.md#appendix-sp-800-227-and-this-projects-key-combiner),
  rather than in a second copy here that could drift from it. The adapter
  stays bit-compatible with upstream's KDF; changing it is a wire-format break
  for upstream to decide on.
- `WIREGUARD_INTERFACE` and `WIREGUARD_PEER_PUBLIC_KEY` must still be set even
  though this adapter ignores them; upstream's config parser requires them
  unconditionally. Making them conditional on the selected adapter is a
  follow-up for the adapter PR.

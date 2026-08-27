// Package repositories provides arnika key-writer adapters.
//
// This file implements a strongSwan key-writer that speaks the VICI protocol
// natively over its unix socket, delivering the arnika-derived HKDF(QKD || PQC)
// secret as an RFC 8784 Post-quantum Preshared Key (PPK).
//
// Why a PPK and not an IKEv2 PSK
//
//	An IKEv2 PSK is consumed only when computing the IKE_AUTH AUTH payload
//	(RFC 7296 section 2.15). It never enters SKEYSEED, so a QKD key delivered
//	as a PSK provides no confidentiality benefit against a harvest-now-
//	decrypt-later adversary. RFC 8784 instead mixes the PPK into the key
//	schedule -- SK_d = prf+(PPK, SK_d') and likewise for SK_pi/SK_pr -- so an
//	attacker must break both the (EC)DH/KEM exchange and obtain the QKD key.
//
// Why rotation needs a reauthentication
//
//	VICI load-shared only writes into charon's in-memory credential set; it
//	touches no SA. An IKEv2 rekey is a CREATE_CHILD_SA exchange that carries no
//	AUTH payload, so it never re-reads credentials. Only a full
//	reauthentication re-runs IKE_SA_INIT + IKE_AUTH and therefore consumes the
//	new PPK. charon.make_before_break has been on by default since strongSwan
//	6.0.0, so reauth does not interrupt traffic.
//
// Load-bearing operational note
//
//	Never run `swanctl --load-creds` against a daemon using this adapter. That
//	command performs a destructive sync: it calls get-shared and then
//	unload-shared for every vici-injected id absent from swanctl.conf, which
//	would silently delete the rotating QKD PPK.
package repositories

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/strongswan/govici/vici"
)

// minPPKBytes is this adapter's PPK floor. It is our rule, not the RFC's.
//
// RFC 8784 sets no length requirement. Its Sec. 6 says only:
//
//	"The strongest practice is to ensure that any post-quantum preshared key
//	contains at least 256 bits of entropy; this will provide 128 bits of
//	post-quantum security, while providing security against conventional
//	dictionary attacks."
//
// Descriptive, not normative -- the RFC uses no MUST, SHOULD or RECOMMENDED for
// PPK length anywhere. This comment previously read: the RFC 8784 entropy
// floor: "The PPK MUST be at least 256 bits of entropy; this will provide 128
// bits of post-quantum security." The second clause is real; the MUST was
// invented, and an invented MUST in a security citation is what a reviewer
// checks first.
//
// 32 bytes is nevertheless the right floor here, for a reason specific to this
// deployment rather than to the RFC: every PPK reaching SetPSK is a 32-byte
// HKDF-SHA3-256 output from arnika. A shorter one means the key path is broken
// upstream, not that an operator chose weaker material, so rejecting it is a
// liveness check rather than a policy knob.
const minPPKBytes = 32

// unloadTimeout bounds a single unload-shared. See unloadPPK for why it does not
// share the rotation's deadline.
const unloadTimeout = 5 * time.Second

// randRead is indirected so tests can assert InvalidateTunnel's behaviour
// deterministically. Production always reads from crypto/rand.
var randRead = func(b []byte) error {
	_, err := rand.Read(b)
	return err
}

// ViciConfig is the configuration surface of the strongSwan VICI key writer.
// Every field is required; there are no defaults that could silently mask a
// misconfiguration.
type ViciConfig struct {
	// SocketPath is charon's VICI unix socket (charon.plugins.vici.socket).
	SocketPath string
	// ConnectionName is the swanctl connection to reauthenticate, and must
	// match the section name under `connections { ... }`.
	ConnectionName string
	// ChildName is the CHILD_SA to initiate when no IKE_SA exists, and must
	// match the section name under `connections.<ConnectionName>.children`.
	// Only the peer with DriveReauth set ever initiates.
	ChildName string
	// PPKID is the RFC 8784 PPK identity. It is stable for the lifetime of the
	// process: the responder resolves PPK_IDENTITY with a synchronous
	// credential lookup during IKE_AUTH (ike_auth.c, get_ppk_r), so a
	// per-rotation identity could never be provisioned in time. The key
	// material behind this identity is what rotates.
	PPKID string
	// CredentialPrefix namespaces the load-shared ids this adapter owns, so
	// individual generations remain revocable via unload-shared. An id is
	// mandatory: charon accumulates id-less shared keys forever, and they are
	// invisible to get-shared and unremovable except by clear-creds.
	CredentialPrefix string
	// ReauthTimeout bounds the wait for a reauthenticated IKE_SA to establish.
	ReauthTimeout time.Duration
	// BootstrapCredentialID is the swanctl.conf `secrets.ppk` section name whose
	// key lets the very first IKE_AUTH complete before any QKD material exists.
	//
	// It is unloaded after the first successful rotation. Leaving it in place is
	// not cosmetic: it is registered under the SAME PPKID as every rotated
	// credential, so two keys answer one PPK_ID lookup and which one charon
	// returns during IKE_AUTH is unspecified. The bootstrap key is derived from
	// ARNIKA_PSK and contains no QKD material at all, so a lane that silently
	// selected it would present as PPK-protected while carrying none of the
	// quantum contribution the design exists to deliver.
	BootstrapCredentialID string
	// DriveReauth makes this node responsible for reauthenticating the tunnel
	// after a rotation. Exactly one of the two peers must set it.
	//
	// Both peers run arnika and both rotate their own copy of the PPK, but they
	// share ONE IKE_SA. If both also reauthenticate it, each rotation triggers
	// two make-before-break reauthentications that each create a replacement SA,
	// so the SA count grows by roughly one per rotation and never settles --
	// measured at +1 per rotation even after the ike-id fix below, and at 140
	// concurrent SAs before it.
	//
	// The peer that does not drive still loads the rotated PPK, which is what
	// lets it answer the driver's IKE_AUTH. Loading is the part that must happen
	// on both sides; driving is the part that must happen on exactly one. This
	// mirrors IKEv2's own asymmetry, where the initiator owns the SA lifecycle.
	//
	// It is deliberately independent of arnika's PRIMARY/BACKUP election, which
	// alternates per interval and decides who *generates* the key, not who owns
	// the SA.
	DriveReauth bool
}

func (c ViciConfig) validate() error {
	switch {
	case c.SocketPath == "":
		return errors.New("vici: SocketPath must be set")
	case c.ConnectionName == "":
		return errors.New("vici: ConnectionName must be set")
	case c.ChildName == "":
		return errors.New("vici: ChildName must be set")
	case c.PPKID == "":
		return errors.New("vici: PPKID must be set")
	case c.CredentialPrefix == "":
		return errors.New("vici: CredentialPrefix must be set")
	case c.BootstrapCredentialID == "":
		return errors.New("vici: BootstrapCredentialID must be set")
	case c.ReauthTimeout <= 0:
		return errors.New("vici: ReauthTimeout must be positive")
	}
	return nil
}

// StrongswanViciRepository is an arnika key-writer backed by strongSwan's VICI
// interface. It satisfies the services.KeyWriterService repository port:
//
//	InvalidateTunnel() error
//	SetPSK(psk string) error
type StrongswanViciRepository struct {
	cfg ViciConfig

	// dial is indirected so tests can supply a fake VICI server.
	dial func() (*vici.Session, error)

	mu         sync.Mutex
	generation uint64
	// loadedID is the credential id currently installed, retained so it can be
	// unloaded only after its successor is confirmed live.
	loadedID string
	// bootstrapRetired records that the pre-QKD credential is gone, so the
	// unload is not retried on every rotation forever.
	bootstrapRetired bool
}

// NewStrongswanViciRepository creates a VICI-backed key writer. It performs a
// version() round trip so that a bad socket path or a charon without the vici
// plugin fails here, at construction, rather than at the first key rotation.
func NewStrongswanViciRepository(cfg ViciConfig) (*StrongswanViciRepository, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	r := &StrongswanViciRepository{
		cfg: cfg,
		dial: func() (*vici.Session, error) {
			return vici.NewSession(vici.WithSocketPath(cfg.SocketPath))
		},
	}

	sess, err := r.dial()
	if err != nil {
		return nil, fmt.Errorf("vici: cannot connect to %s: %w", cfg.SocketPath, err)
	}
	defer sess.Close()

	ctx, cancel := context.WithTimeout(context.Background(), cfg.ReauthTimeout)
	defer cancel()

	resp, err := sess.Call(ctx, "version", vici.NewMessage())
	if err != nil {
		return nil, fmt.Errorf("vici: version handshake failed: %w", err)
	}
	log.Printf("[INFO] [VICI] connected to %v %v on %s",
		resp.Get("daemon"), resp.Get("version"), cfg.SocketPath)

	if err := r.reconcile(ctx, sess); err != nil {
		return nil, err
	}
	return r, nil
}

// reconcile adopts the credentials a previous process left behind.
//
// generation and loadedID live in this process, so a restart would otherwise
// begin again at <prefix>-1 while every <prefix>-N from the previous run is
// still registered with charon. Nothing would ever remove them: SetPSK unloads
// only the id THIS process installed. That is the unbounded accumulation
// docs/vici-ppk.md warns about, and it is invisible from swanctl --list-conns.
//
// Adopt rather than clear. The highest surviving generation is the credential
// the peer is most likely still holding, and its key material cannot be
// re-derived here -- it came from a QKD exchange that already happened. Keeping
// it loaded preserves the tunnel across a restart; unloading it would strand
// this node on the bootstrap PPK, mismatched against the peer, until the next
// rotation. Older generations are unloaded because leaving several credentials
// answering one PPK_ID makes charon's lookup ambiguous.
func (r *StrongswanViciRepository) reconcile(ctx context.Context, sess *vici.Session) error {
	ids, err := r.sharedIDs(ctx, sess)
	if err != nil {
		return fmt.Errorf("vici: cannot reconcile existing credentials: %w", err)
	}

	prefix := r.cfg.CredentialPrefix + "-"
	var newest string
	var newestGen uint64
	var stale []string
	for _, id := range ids {
		if !strings.HasPrefix(id, prefix) {
			continue
		}
		gen, err := strconv.ParseUint(strings.TrimPrefix(id, prefix), 10, 64)
		if err != nil {
			// Same prefix, not our numbering. Leave it alone rather than
			// unloading a credential this adapter did not create.
			log.Printf("[WARN] [VICI] ignoring unrecognised credential id %q", id)
			continue
		}
		if gen > newestGen {
			if newest != "" {
				stale = append(stale, newest)
			}
			newest, newestGen = id, gen
			continue
		}
		stale = append(stale, id)
	}

	if newest == "" {
		return nil
	}
	r.generation, r.loadedID = newestGen, newest
	log.Printf("[INFO] [VICI] adopted %s from a previous process; next rotation will be %s-%d",
		newest, r.cfg.CredentialPrefix, newestGen+1)

	for _, id := range stale {
		if err := r.unloadPPK(ctx, sess, id); err != nil {
			// Not fatal: the adoption above is what keeps the tunnel working.
			// Loud, because this is exactly the leak being cleaned up.
			log.Printf("[WARN] [VICI] could not unload orphaned credential %s: %v", id, err)
			continue
		}
		log.Printf("[INFO] [VICI] unloaded orphaned credential %s", id)
	}
	return nil
}

// SetPSK installs psk as the RFC 8784 PPK and reauthenticates the IKE_SA so the
// new key actually enters the key schedule.
//
// psk is standard base64 of the raw derived key, matching what arnika's main
// loop hands to every key writer.
//
// The sequence is deliberately overlap-then-swap:
//
//  1. load-shared the new generation   (both generations now loaded)
//  2. get-shared to confirm it landed
//  3. list-sas, then rekey that one SA by unique id with reauth=yes
//     (or initiate, if no SA exists yet)
//  4. unload-shared the previous generation
//  5. unload-shared the bootstrap credential, once
//
// Step 4 must come after step 3. Unloading the in-use credential before the
// replacement is driven does not tear down the current SA -- it breaks the
// *next* reauthentication, which is a far harder failure to diagnose.
//
// What this does NOT do is block until the reauthenticated IKE_SA reaches
// ESTABLISHED. The vici `rekey` command returns once charon has queued the
// reauthentication, not once it has completed, so step 4 can run while the new
// SA is still in IKE_AUTH. That is tolerable because both generations remain
// loaded across the gap and either satisfies the PPK_ID lookup, and because a
// reauthentication that ultimately fails leaves the old SA in place under
// make-before-break. An earlier version of this comment claimed a "wait for a
// new established IKE_SA" step; no such step was ever implemented, and the
// claim is recorded here as absent rather than quietly deleted because it
// changes how a reader reasons about the overlap window.
//
// Closing that gap properly means subscribing to the `ike-updown` event stream
// rather than polling, and is tracked in docs/roadmap.md.
func (r *StrongswanViciRepository) SetPSK(psk string) error {
	raw, err := base64.StdEncoding.DecodeString(psk)
	if err != nil {
		return fmt.Errorf("vici: PSK is not valid base64: %w", err)
	}
	if len(raw) < minPPKBytes {
		// "this adapter requires", not "RFC 8784 requires": the RFC requires no
		// length at all. See minPPKBytes for what its Sec. 6 actually says.
		return fmt.Errorf(
			"vici: PPK is %d bytes, this adapter requires at least %d -- the 256 bits "+
				"of entropy RFC 8784 Sec. 6 calls the strongest practice",
			len(raw), minPPKBytes)
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	sess, err := r.dial()
	if err != nil {
		return fmt.Errorf("vici: cannot connect to %s: %w", r.cfg.SocketPath, err)
	}
	defer sess.Close()

	ctx, cancel := context.WithTimeout(context.Background(), r.cfg.ReauthTimeout)
	defer cancel()

	next := fmt.Sprintf("%s-%d", r.cfg.CredentialPrefix, r.generation+1)
	previous := r.loadedID

	if err := r.loadPPK(ctx, sess, next, raw); err != nil {
		return err
	}
	if err := r.assertLoaded(ctx, sess, next); err != nil {
		return err
	}
	if r.cfg.DriveReauth {
		if err := r.reauthenticate(ctx, sess); err != nil {
			// The new credential is loaded but unused. Leave it: the next
			// rotation replaces it by id, and leaving it costs one entry rather
			// than stranding the connection with no PPK at all.
			return err
		}
	} else {
		// Loaded, not driven. The peer that owns the SA will reauthenticate and
		// this node answers that IKE_AUTH with the credential just installed.
		log.Printf("[INFO] [VICI] PPK %s loaded; not reauthenticating (the peer "+
			"drives the SA for %q)", next, r.cfg.ConnectionName)
	}

	r.generation++
	r.loadedID = next

	if previous != "" {
		if err := r.unloadPPK(ctx, sess, previous); err != nil {
			// Non-fatal: the rotation itself succeeded. Surface it loudly so a
			// slow credential leak cannot accumulate unnoticed.
			log.Printf("[WARN] [VICI] rotation succeeded but unloading %s failed: %v",
				previous, err)
		}
	}

	r.retireBootstrap(ctx, sess)

	log.Printf("[INFO] [VICI] PPK rotated (id=%s ppk_id=%s bytes=%d)",
		next, r.cfg.PPKID, len(raw))
	return nil
}

// retireBootstrap removes the pre-QKD credential once real material is loaded.
//
// Called after every rotation rather than only the first: unload-shared on an
// absent id is harmless, and a single missed attempt would otherwise leave a
// non-QKD key answering the PPK_ID for the lifetime of the process. Failure is
// logged, never returned -- the rotation itself succeeded, and reporting an
// error here would send arnika into InvalidateTunnel over a cleanup step.
func (r *StrongswanViciRepository) retireBootstrap(ctx context.Context, sess *vici.Session) {
	if r.bootstrapRetired {
		return
	}
	if err := r.unloadPPK(ctx, sess, r.cfg.BootstrapCredentialID); err != nil {
		log.Printf("[WARN] [VICI] could not unload the bootstrap credential %s: %v; "+
			"it still answers PPK_ID %s alongside the rotated key",
			r.cfg.BootstrapCredentialID, err, r.cfg.PPKID)
		return
	}
	r.bootstrapRetired = true
	log.Printf("[INFO] [VICI] unloaded the bootstrap credential %s; PPK_ID %s is now "+
		"answered only by QKD-derived material",
		r.cfg.BootstrapCredentialID, r.cfg.PPKID)
}

// InvalidateTunnel installs a locally-generated random PPK, which the peer
// cannot match, and reauthenticates. This mirrors the netlink adapter, where
// arnika deliberately breaks the session whenever no acceptable key material is
// available, so that a failure is visible as a dead tunnel rather than as
// traffic still flowing under a stale key.
func (r *StrongswanViciRepository) InvalidateTunnel() error {
	random := make([]byte, minPPKBytes)
	if err := randRead(random); err != nil {
		return fmt.Errorf("vici: cannot generate random PPK: %w", err)
	}
	log.Printf("[WARN] [VICI] invalidating tunnel: installing a random local PPK; " +
		"the peer cannot match it and the IKE_SA will fail to reauthenticate")
	return r.SetPSK(base64.StdEncoding.EncodeToString(random))
}

func (r *StrongswanViciRepository) loadPPK(ctx context.Context, sess *vici.Session, id string, raw []byte) error {
	msg := vici.NewMessage()
	if err := msg.Set("id", id); err != nil {
		return fmt.Errorf("vici: encoding id: %w", err)
	}
	// vici_cred.c maps this case-insensitively to SHARED_PPK. The VICI README
	// documents only IKE|EAP|XAUTH|NTLM, but "ppk" is accepted and is what
	// swanctl itself sends for a `secrets.ppk*` section.
	if err := msg.Set("type", "ppk"); err != nil {
		return fmt.Errorf("vici: encoding type: %w", err)
	}
	// VICI values are arbitrary blobs; the 0x/0s prefixes are a swanctl.conf
	// convention decoded client-side, not by charon. Send raw bytes.
	if err := msg.Set("data", string(raw)); err != nil {
		return fmt.Errorf("vici: encoding data: %w", err)
	}
	if err := msg.Set("owners", []string{r.cfg.PPKID}); err != nil {
		return fmt.Errorf("vici: encoding owners: %w", err)
	}

	resp, err := sess.Call(ctx, "load-shared", msg)
	if err != nil {
		return fmt.Errorf("vici: load-shared %s: %w", id, err)
	}
	return checkSuccess(resp, "load-shared "+id)
}

func (r *StrongswanViciRepository) unloadPPK(parent context.Context, sess *vici.Session, id string) error {
	msg := vici.NewMessage()
	if err := msg.Set("id", id); err != nil {
		return fmt.Errorf("vici: encoding id: %w", err)
	}

	// A deadline of its own, deliberately NOT inherited from the caller.
	//
	// The rotation path spends its budget on the reauthentication, so a reauth
	// that used most of ReauthTimeout would leave an unload sharing the same
	// context with no time left -- and the unload would fail precisely on the
	// slow rotations where credential cleanup matters most. unload-shared is a
	// single in-memory operation on charon's credential set, so it needs a small
	// fixed allowance rather than whatever happens to remain.
	//
	// context.WithoutCancel keeps the parent's values while dropping its
	// deadline and cancellation.
	ctx, cancel := context.WithTimeout(context.WithoutCancel(parent), unloadTimeout)
	defer cancel()

	resp, err := sess.Call(ctx, "unload-shared", msg)
	if err != nil {
		return fmt.Errorf("vici: unload-shared %s: %w", id, err)
	}
	return checkSuccess(resp, "unload-shared "+id)
}

// assertLoaded verifies the credential is visible to get-shared. This is not
// ceremony: unload-shared reports success for ids that never existed, so
// get-shared is the only reliable existence check, and an id-less load would
// silently not appear here at all.
func (r *StrongswanViciRepository) assertLoaded(ctx context.Context, sess *vici.Session, id string) error {
	keys, err := r.sharedIDs(ctx, sess)
	if err != nil {
		return err
	}
	for _, k := range keys {
		if k == id {
			return nil
		}
	}
	return fmt.Errorf("vici: %s was not registered by charon (loaded ids: %v)", id, keys)
}

// sharedIDs lists every shared-secret id charon currently holds.
func (r *StrongswanViciRepository) sharedIDs(ctx context.Context, sess *vici.Session) ([]string, error) {
	resp, err := sess.Call(ctx, "get-shared", vici.NewMessage())
	if err != nil {
		return nil, fmt.Errorf("vici: get-shared: %w", err)
	}
	keys, ok := resp.Get("keys").([]string)
	if !ok {
		// A charon holding exactly one shared key encodes `keys` as a bare
		// string rather than a list, and holding none omits it entirely.
		// Treating either as an error would fail reconciliation on a fresh
		// daemon, which is the common case at boot.
		switch v := resp.Get("keys").(type) {
		case string:
			return []string{v}, nil
		case nil:
			return nil, nil
		default:
			return nil, fmt.Errorf("vici: get-shared returned an unusable key list (got %T)", v)
		}
	}
	return keys, nil
}

// reauthenticate forces a full IKE_SA_INIT + IKE_AUTH so the newly loaded PPK
// enters SK_d/SK_pi/SK_pr. A plain rekey would not re-read credentials.
//
// It targets ONE IKE_SA by unique id. Selecting with `ike` (the connection
// name) instead -- as this did originally -- makes charon reauthenticate every
// SA on the connection, and because a make-before-break reauth creates the
// replacement before removing the original, N SAs become 2N. That is a
// multiplier, not a leak: a two-node run reached 140 concurrent IKE_SAs in nine
// minutes and was still climbing. `ike-id` makes one rotation cost exactly one
// reauthentication regardless of how many SAs happen to exist.
func (r *StrongswanViciRepository) reauthenticate(ctx context.Context, sess *vici.Session) error {
	ids, err := r.saIDs(ctx, sess)
	if err != nil {
		return err
	}
	if len(ids) == 0 {
		// No SA to reauthenticate. Bring one up instead: this node owns the
		// lane, and the rotation loop is the only thing that runs periodically,
		// so it is also the supervisor.
		//
		// charon does not reliably do this for us. `start_action = start`
		// initiates once at config load, and an initiation that the peer
		// rejects -- NO_PROPOSAL_CHOSEN is the normal answer when the peer's
		// charon is up but has not loaded its connections yet, which is exactly
		// what happens when both containers boot together -- destroys the SA
		// with no further attempt. Observed directly: one initiation, then
		// nothing for the following ten minutes.
		return r.initiate(ctx, sess)
	}
	if len(ids) > 1 {
		// `unique = replace` in swanctl.conf should collapse these. Surfacing it
		// matters because the tunnel still passes traffic while it happens, so
		// nothing else in the system would notice.
		log.Printf("[WARN] [VICI] %d IKE_SAs exist for %q (expected 1): %v; "+
			"reauthenticating the newest only", len(ids), r.cfg.ConnectionName, ids)
	}
	target := newestSAID(ids)

	msg := vici.NewMessage()
	if err := msg.Set("ike-id", target); err != nil {
		return fmt.Errorf("vici: encoding ike-id: %w", err)
	}
	if err := msg.Set("reauth", "yes"); err != nil {
		return fmt.Errorf("vici: encoding reauth: %w", err)
	}

	resp, err := sess.Call(ctx, "rekey", msg)
	if err != nil {
		return fmt.Errorf("vici: rekey ike-id=%s: %w", target, err)
	}
	if err := checkSuccess(resp, "rekey"); err != nil {
		return err
	}
	// success=yes with matches=0 is charon's normal answer when the selector
	// matched nothing, so success alone proves nothing happened. Here it means
	// the SA disappeared between the list and the rekey, which is a real
	// failure: the PPK is loaded but nothing consumed it.
	matches, _ := resp.Get("matches").(string)
	if matches == "" || matches == "0" {
		return fmt.Errorf(
			"vici: rekey matched no IKE_SA for unique id %s on %q (matches=%q); "+
				"the PPK was loaded but is not in use",
			target, r.cfg.ConnectionName, matches)
	}
	return nil
}

// initiate brings the tunnel up when no IKE_SA exists.
//
// A failure here is reported but NOT returned as an error. arnika answers a
// failed SetPSK by calling InvalidateTunnel, which installs a random PPK the
// peer cannot match -- useful when a live tunnel must be torn down, actively
// harmful when there is no tunnel at all, because it poisons the credential the
// next handshake would have used. The PPK for this generation is already
// loaded; the next rotation will try again in one interval.
//
// The loud WARN is the point: a lane that never comes up must be visible in the
// log rather than inferred from an empty `swanctl --list-sas`.
func (r *StrongswanViciRepository) initiate(ctx context.Context, sess *vici.Session) error {
	msg := vici.NewMessage()
	if err := msg.Set("child", r.cfg.ChildName); err != nil {
		return fmt.Errorf("vici: encoding child: %w", err)
	}
	if err := msg.Set("ike", r.cfg.ConnectionName); err != nil {
		return fmt.Errorf("vici: encoding ike: %w", err)
	}
	// charon's own bound, in milliseconds, so the call cannot outlive ctx.
	if err := msg.Set("timeout", strconv.FormatInt(r.cfg.ReauthTimeout.Milliseconds(), 10)); err != nil {
		return fmt.Errorf("vici: encoding timeout: %w", err)
	}

	log.Printf("[INFO] [VICI] no IKE_SA for %q; initiating %s",
		r.cfg.ConnectionName, r.cfg.ChildName)

	resp, err := sess.Call(ctx, "initiate", msg)
	if err != nil {
		log.Printf("[WARN] [VICI] initiate %s failed: %v; PPK is loaded, retrying "+
			"on the next rotation", r.cfg.ChildName, err)
		return nil
	}
	if err := checkSuccess(resp, "initiate"); err != nil {
		log.Printf("[WARN] [VICI] initiate %s did not succeed: %v; PPK is loaded, "+
			"retrying on the next rotation", r.cfg.ChildName, err)
		return nil
	}
	log.Printf("[INFO] [VICI] initiated %s for %q", r.cfg.ChildName, r.cfg.ConnectionName)
	return nil
}

// newestSAID picks the highest unique id. charon assigns them monotonically, so
// the highest is the most recently established -- the one a reauthentication
// should carry forward. Compared numerically, because "10" sorts before "9" as
// a string and reauthenticating a stale SA would leave the live one on the old
// PPK.
func newestSAID(ids []string) string {
	best, bestN := ids[0], -1
	for _, id := range ids {
		n, err := strconv.Atoi(id)
		if err != nil {
			continue
		}
		if n > bestN {
			best, bestN = id, n
		}
	}
	return best
}

// saIDs returns the unique ids of every IKE_SA charon currently holds for the
// connection, newest last is NOT guaranteed -- callers that care must order.
//
// arnika starts rotating the moment charon's VICI socket appears, which is
// before the initial IKE_SA_INIT/IKE_AUTH has completed, so an empty result is
// the normal state immediately after boot rather than an error. The PPK is
// already loaded by then and charon resolves the PPK_ID synchronously during
// IKE_AUTH, so the handshake still in flight picks it up. Treating that as a
// failure is not merely noisy: arnika answers a failed SetPSK by calling
// InvalidateTunnel, which installs a deliberately unmatched random PPK, turning
// a benign startup race into a tunnel that cannot come up at all.
func (r *StrongswanViciRepository) saIDs(ctx context.Context, sess *vici.Session) ([]string, error) {
	msg := vici.NewMessage()
	if err := msg.Set("ike", r.cfg.ConnectionName); err != nil {
		return nil, fmt.Errorf("vici: encoding ike: %w", err)
	}
	// list-sas is a streamed command: charon emits one `list-sa` event per SA
	// and the command response itself carries no SA data, so a plain Call would
	// always look like zero SAs.
	var ids []string
	for m, err := range sess.CallStreaming(ctx, "list-sas", "list-sa", msg) {
		if err != nil {
			return nil, fmt.Errorf("vici: list-sas: %w", err)
		}
		// Each event is keyed by the connection name; the `ike` selector above
		// already filters, but check the key so an unrelated event cannot be
		// counted as one of ours.
		sa, ok := m.Get(r.cfg.ConnectionName).(*vici.Message)
		if !ok {
			continue
		}
		id, ok := sa.Get("uniqueid").(string)
		if !ok || id == "" {
			// An SA charon will not name cannot be targeted by ike-id, and
			// silently skipping it would understate the count that drives the
			// duplicate-SA warning.
			return nil, fmt.Errorf("vici: list-sas returned an SA on %q with no uniqueid",
				r.cfg.ConnectionName)
		}
		ids = append(ids, id)
	}
	return ids, nil
}

// checkSuccess treats an absent success field as failure. govici's Message.Err
// returns nil when the field is missing, which would let a malformed or
// truncated response pass as a successful key rotation.
func checkSuccess(resp *vici.Message, what string) error {
	success, ok := resp.Get("success").(string)
	if !ok {
		return fmt.Errorf("vici: %s: response carried no success field", what)
	}
	if success != "yes" {
		errmsg, _ := resp.Get("errmsg").(string)
		return fmt.Errorf("vici: %s failed: %s", what, errmsg)
	}
	return nil
}

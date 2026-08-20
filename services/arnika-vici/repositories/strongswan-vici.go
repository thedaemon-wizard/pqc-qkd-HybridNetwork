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
	"sync"
	"time"

	"github.com/strongswan/govici/vici"
)

// minPPKBytes is the RFC 8784 entropy floor: "The PPK MUST be at least 256 bits
// of entropy; this will provide 128 bits of post-quantum security."
const minPPKBytes = 32

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

	return r, nil
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
//  3. rekey with reauth=yes
//  4. wait for a new established IKE_SA
//  5. unload-shared the previous generation
//
// Step 5 must come last. Unloading the in-use credential before the replacement
// is confirmed does not tear down the current SA -- it breaks the *next*
// reauthentication, hours later, which is a far harder failure to diagnose.
func (r *StrongswanViciRepository) SetPSK(psk string) error {
	raw, err := base64.StdEncoding.DecodeString(psk)
	if err != nil {
		return fmt.Errorf("vici: PSK is not valid base64: %w", err)
	}
	if len(raw) < minPPKBytes {
		return fmt.Errorf(
			"vici: PPK is %d bytes, RFC 8784 requires at least %d bytes of entropy",
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

	log.Printf("[INFO] [VICI] PPK rotated (id=%s ppk_id=%s bytes=%d)",
		next, r.cfg.PPKID, len(raw))
	return nil
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

func (r *StrongswanViciRepository) unloadPPK(ctx context.Context, sess *vici.Session, id string) error {
	msg := vici.NewMessage()
	if err := msg.Set("id", id); err != nil {
		return fmt.Errorf("vici: encoding id: %w", err)
	}
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
	resp, err := sess.Call(ctx, "get-shared", vici.NewMessage())
	if err != nil {
		return fmt.Errorf("vici: get-shared: %w", err)
	}
	keys, ok := resp.Get("keys").([]string)
	if !ok {
		return fmt.Errorf("vici: get-shared returned no key list (got %T)", resp.Get("keys"))
	}
	for _, k := range keys {
		if k == id {
			return nil
		}
	}
	return fmt.Errorf("vici: %s was not registered by charon (loaded ids: %v)", id, keys)
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

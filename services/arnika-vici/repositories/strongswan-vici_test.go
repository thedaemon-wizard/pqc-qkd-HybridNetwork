package repositories

import (
	"encoding/base64"
	"errors"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"
)

// --- Fake VICI server -------------------------------------------------------
//
// Speaks enough of the VICI wire protocol to exercise the rotation sequence.
// Framing per src/libcharon/plugins/vici/README.md:
//
//	segment      = uint32_be(len(payload)) || payload
//	payload      = <u8 packet type> [<u8 name len> <name>] <elements...>
//	CMD_REQUEST  = 0, CMD_RESPONSE = 1
//	KEY_VALUE    = 3: <u8 name len> <name> <u16_be val len> <value>
//	LIST_START   = 4: <u8 name len> <name>
//	LIST_ITEM    = 5: <u16_be val len> <value>
//	LIST_END     = 6
//
// list-sas is a STREAMED command, which is a different exchange: the client
// registers for an event, issues the request, receives zero or more EVENT
// packets, then a terminating CMD_RESPONSE, then unregisters. The fake has to
// speak that too, otherwise every rotation test fails at the SA lookup rather
// than at the behaviour it is asserting.
//
//	EVENT_REGISTER   = 3 -> EVENT_CONFIRM = 5 / EVENT_UNKNOWN = 6
//	EVENT_UNREGISTER = 4 -> EVENT_CONFIRM = 5
//	EVENT            = 7: <u8 name len> <name> <elements...>
//
// Section markers nest a sub-message: SECTION_START = 1, SECTION_END = 2.

const (
	pktCmdRequest  = 0
	pktCmdResponse = 1

	pktEventRegister   = 3
	pktEventUnregister = 4
	pktEventConfirm    = 5
	pktEvent           = 7

	elSectionStart = 1
	elSectionEnd   = 2

	elKeyValue  = 3
	elListStart = 4
	elListItem  = 5
	elListEnd   = 6
)

type request struct {
	name   string
	fields map[string]string
	lists  map[string][]string
}

type fakeVici struct {
	t    *testing.T
	ln   net.Listener
	path string

	requests []request
	// responses maps a command name to the fields returned. A missing entry
	// yields success=yes.
	responses map[string]map[string]string
	// loaded tracks ids installed via load-shared, so get-shared can answer
	// truthfully and the test can assert unload behaviour.
	loaded map[string]bool
	failOn map[string]string
	// saIDs are the IKE_SA unique ids list-sas reports. Empty models a lane
	// that has not come up yet, which is the branch that initiates rather than
	// reauthenticates.
	saIDs []string
	// registered tracks which streamed events the client subscribed to.
	registered map[string]bool
}

func newFakeVici(t *testing.T) *fakeVici {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "charon.vici")

	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	f := &fakeVici{
		t:         t,
		ln:        ln,
		path:      path,
		responses:  map[string]map[string]string{},
		loaded:     map[string]bool{},
		failOn:     map[string]string{},
		registered: map[string]bool{},
		// One established SA is the normal steady state, so it is the default
		// the rotation tests run against.
		saIDs: []string{"1"},
	}
	go f.serve()
	t.Cleanup(func() { _ = ln.Close(); _ = os.Remove(path) })
	return f
}

func (f *fakeVici) serve() {
	for {
		conn, err := f.ln.Accept()
		if err != nil {
			return
		}
		go f.handle(conn)
	}
}

func (f *fakeVici) handle(conn net.Conn) {
	defer conn.Close()
	for {
		payload, err := readSegment(conn)
		if err != nil {
			return
		}
		if len(payload) == 0 {
			return
		}
		nameLen := int(payload[1])
		name := string(payload[2 : 2+nameLen])

		switch payload[0] {
		case pktEventRegister:
			f.registered[name] = true
			if err := writeSegment(conn, []byte{pktEventConfirm}); err != nil {
				return
			}
			continue
		case pktEventUnregister:
			delete(f.registered, name)
			if err := writeSegment(conn, []byte{pktEventConfirm}); err != nil {
				return
			}
			continue
		case pktCmdRequest:
		default:
			return
		}

		req := parseElements(payload[2+nameLen:])
		req.name = name
		f.requests = append(f.requests, req)

		// Streamed commands emit their payload as events before the response.
		if name == "list-sas" && f.registered["list-sa"] {
			for _, id := range f.saIDs {
				if err := writeSegment(conn, f.listSAEvent(req.fields["ike"], id)); err != nil {
					return
				}
			}
		}

		if err := writeSegment(conn, f.reply(req)); err != nil {
			return
		}
	}
}

// listSAEvent builds one `list-sa` event: a section named for the connection,
// containing the SA's uniqueid. That nesting is what the adapter reads, so a
// flat message here would let a broken parser pass.
func (f *fakeVici) listSAEvent(conn, uniqueID string) []byte {
	out := []byte{pktEvent, byte(len("list-sa"))}
	out = append(out, "list-sa"...)

	out = append(out, elSectionStart, byte(len(conn)))
	out = append(out, conn...)

	out = append(out, elKeyValue, byte(len("uniqueid")))
	out = append(out, "uniqueid"...)
	out = append(out, byte(len(uniqueID)>>8), byte(len(uniqueID)))
	out = append(out, uniqueID...)

	out = append(out, elSectionEnd)
	return out
}

func (f *fakeVici) reply(req request) []byte {
	fields := map[string]string{}
	var lists map[string][]string

	switch req.name {
	case "version":
		fields = map[string]string{"daemon": "charon", "version": "6.0.7"}

	case "load-shared":
		if msg, bad := f.failOn["load-shared"]; bad {
			fields = map[string]string{"success": "no", "errmsg": msg}
		} else {
			f.loaded[req.fields["id"]] = true
			fields = map[string]string{"success": "yes"}
		}

	case "unload-shared":
		delete(f.loaded, req.fields["id"])
		fields = map[string]string{"success": "yes"}

	case "get-shared":
		ids := make([]string, 0, len(f.loaded))
		for id := range f.loaded {
			ids = append(ids, id)
		}
		lists = map[string][]string{"keys": ids}

	case "rekey":
		if msg, bad := f.failOn["rekey"]; bad {
			fields = map[string]string{"success": "no", "errmsg": msg}
		} else if override, ok := f.responses["rekey"]; ok {
			fields = override
		} else {
			fields = map[string]string{"success": "yes", "matches": "1"}
		}

	default:
		fields = map[string]string{"success": "yes"}
	}

	return encodeResponse(fields, lists)
}

func (f *fakeVici) callsTo(name string) []request {
	var out []request
	for _, r := range f.requests {
		if r.name == name {
			out = append(out, r)
		}
	}
	return out
}

// --- wire helpers -----------------------------------------------------------

func readSegment(c net.Conn) ([]byte, error) {
	var hdr [4]byte
	if _, err := ioReadFull(c, hdr[:]); err != nil {
		return nil, err
	}
	n := int(hdr[0])<<24 | int(hdr[1])<<16 | int(hdr[2])<<8 | int(hdr[3])
	buf := make([]byte, n)
	if _, err := ioReadFull(c, buf); err != nil {
		return nil, err
	}
	return buf, nil
}

func writeSegment(c net.Conn, payload []byte) error {
	n := len(payload)
	hdr := []byte{byte(n >> 24), byte(n >> 16), byte(n >> 8), byte(n)}
	if _, err := c.Write(hdr); err != nil {
		return err
	}
	_, err := c.Write(payload)
	return err
}

func ioReadFull(c net.Conn, b []byte) (int, error) {
	got := 0
	for got < len(b) {
		n, err := c.Read(b[got:])
		if n > 0 {
			got += n
		}
		if err != nil {
			return got, err
		}
	}
	return got, nil
}

func parseElements(b []byte) request {
	r := request{fields: map[string]string{}, lists: map[string][]string{}}
	var listKey string
	i := 0
	for i < len(b) {
		switch b[i] {
		case elKeyValue:
			i++
			nl := int(b[i])
			i++
			key := string(b[i : i+nl])
			i += nl
			vl := int(b[i])<<8 | int(b[i+1])
			i += 2
			r.fields[key] = string(b[i : i+vl])
			i += vl
		case elListStart:
			i++
			nl := int(b[i])
			i++
			listKey = string(b[i : i+nl])
			i += nl
			r.lists[listKey] = []string{}
		case elListItem:
			i++
			vl := int(b[i])<<8 | int(b[i+1])
			i += 2
			r.lists[listKey] = append(r.lists[listKey], string(b[i:i+vl]))
			i += vl
		case elListEnd:
			i++
			listKey = ""
		default:
			return r
		}
	}
	return r
}

func encodeResponse(fields map[string]string, lists map[string][]string) []byte {
	out := []byte{pktCmdResponse}
	for k, v := range fields {
		out = append(out, elKeyValue, byte(len(k)))
		out = append(out, k...)
		out = append(out, byte(len(v)>>8), byte(len(v)))
		out = append(out, v...)
	}
	for k, items := range lists {
		out = append(out, elListStart, byte(len(k)))
		out = append(out, k...)
		for _, it := range items {
			out = append(out, elListItem, byte(len(it)>>8), byte(len(it)))
			out = append(out, it...)
		}
		out = append(out, elListEnd)
	}
	return out
}

// --- helpers ----------------------------------------------------------------

func testConfig(path string) ViciConfig {
	return ViciConfig{
		SocketPath:       path,
		ConnectionName:   "pqcqkd-vpn",
		ChildName:        "tunnel",
		PPKID:            "ppk-qkd@pqcqkd.local",
		CredentialPrefix: "qkd-bob",
		BootstrapCredentialID: "ppk-qkd-bootstrap",
		ReauthTimeout:    5 * time.Second,
		// The tests exercise the rotation path, which only the peer that owns
		// the IKE_SA walks. The responder path is a single early return.
		DriveReauth: true,
	}
}

func psk32(fill byte) string {
	b := make([]byte, 32)
	for i := range b {
		b[i] = fill
	}
	return base64.StdEncoding.EncodeToString(b)
}

// --- tests ------------------------------------------------------------------

func TestValidateRejectsIncompleteConfig(t *testing.T) {
	for name, mutate := range map[string]func(*ViciConfig){
		"no socket":     func(c *ViciConfig) { c.SocketPath = "" },
		"no connection": func(c *ViciConfig) { c.ConnectionName = "" },
		"no ppk id":     func(c *ViciConfig) { c.PPKID = "" },
		"no prefix":     func(c *ViciConfig) { c.CredentialPrefix = "" },
		"no timeout":    func(c *ViciConfig) { c.ReauthTimeout = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			cfg := testConfig("/tmp/x")
			mutate(&cfg)
			if err := cfg.validate(); err == nil {
				t.Fatal("expected validation error, got nil")
			}
		})
	}
}

func TestSetPSKPerformsOverlapThenSwap(t *testing.T) {
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}

	if err := repo.SetPSK(psk32(0x01)); err != nil {
		t.Fatalf("first rotation: %v", err)
	}
	if err := repo.SetPSK(psk32(0x02)); err != nil {
		t.Fatalf("second rotation: %v", err)
	}

	loads := f.callsTo("load-shared")
	if len(loads) != 2 {
		t.Fatalf("want 2 load-shared calls, got %d", len(loads))
	}
	if got := loads[0].fields["id"]; got != "qkd-bob-1" {
		t.Errorf("first id = %q, want qkd-bob-1", got)
	}
	if got := loads[1].fields["id"]; got != "qkd-bob-2" {
		t.Errorf("second id = %q, want qkd-bob-2", got)
	}

	// The PPK type is the whole point: SHARED_IKE would authenticate but
	// contribute nothing to SKEYSEED.
	for _, l := range loads {
		if got := l.fields["type"]; got != "ppk" {
			t.Errorf("type = %q, want ppk", got)
		}
		if got := l.lists["owners"]; len(got) != 1 || got[0] != "ppk-qkd@pqcqkd.local" {
			t.Errorf("owners = %v, want [ppk-qkd@pqcqkd.local]", got)
		}
		if len(l.fields["data"]) != 32 {
			t.Errorf("data = %d bytes, want 32 raw bytes", len(l.fields["data"]))
		}
	}

	// Only the first generation is unloaded, and only after the second landed.
	// The bootstrap credential is retired alongside it -- once, on the first
	// rotation -- so two unloads total across two rotations.
	var unloadedIDs []string
	for _, u := range f.callsTo("unload-shared") {
		unloadedIDs = append(unloadedIDs, u.fields["id"])
	}
	want := []string{"ppk-qkd-bootstrap", "qkd-bob-1"}
	got := append([]string(nil), unloadedIDs...)
	sort.Strings(got)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unloaded %v, want exactly %v", unloadedIDs, want)
	}
}

func TestBootstrapCredentialIsRetiredOnce(t *testing.T) {
	// The bootstrap PPK is registered under the SAME PPK_ID as every rotated
	// credential, so leaving it loaded means two keys answer one IKE_AUTH
	// lookup and charon's choice is unspecified. It carries no QKD material, so
	// selecting it would present as PPK-protected while delivering none of the
	// quantum contribution the lane exists for.
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	for i, fill := range []byte{0x11, 0x12, 0x13} {
		if err := repo.SetPSK(psk32(fill)); err != nil {
			t.Fatalf("rotation %d: %v", i+1, err)
		}
	}

	n := 0
	for _, u := range f.callsTo("unload-shared") {
		if u.fields["id"] == "ppk-qkd-bootstrap" {
			n++
		}
	}
	if n != 1 {
		t.Errorf("bootstrap unloaded %d times across 3 rotations, want exactly 1", n)
	}
	if f.loaded["ppk-qkd-bootstrap"] {
		t.Error("bootstrap credential is still registered with charon")
	}
}

func TestReconcileAdoptsNewestAndDropsOlderOrphans(t *testing.T) {
	// generation and loadedID are process-local, so without reconciliation a
	// restart begins again at qkd-bob-1 while every id from the previous run
	// stays registered forever -- SetPSK only unloads what this process loaded.
	f := newFakeVici(t)
	f.loaded["qkd-bob-3"] = true
	f.loaded["qkd-bob-7"] = true
	f.loaded["qkd-bob-5"] = true
	f.loaded["some-other-cred"] = true

	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}

	// The newest survives: its key material came from a QKD exchange that
	// already happened and cannot be re-derived here, and it is what the peer
	// most likely still holds. Dropping it would strand this node on the
	// bootstrap PPK until the next rotation.
	if !f.loaded["qkd-bob-7"] {
		t.Error("qkd-bob-7 should have been adopted, not unloaded")
	}
	for _, id := range []string{"qkd-bob-3", "qkd-bob-5"} {
		if f.loaded[id] {
			t.Errorf("%s is an older orphan and should have been unloaded", id)
		}
	}
	// Credentials this adapter did not create are left strictly alone.
	if !f.loaded["some-other-cred"] {
		t.Error("unrelated credential must not be touched")
	}

	// Numbering continues from the adopted generation rather than colliding.
	if err := repo.SetPSK(psk32(0x21)); err != nil {
		t.Fatalf("rotate: %v", err)
	}
	loads := f.callsTo("load-shared")
	if got := loads[len(loads)-1].fields["id"]; got != "qkd-bob-8" {
		t.Errorf("next generation = %q, want qkd-bob-8", got)
	}
}

func TestSetPSKAlwaysSetsAnID(t *testing.T) {
	// An id-less load-shared accumulates one entry per rotation forever, is
	// invisible to get-shared, and can never be removed except by clear-creds.
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK(psk32(0x03)); err != nil {
		t.Fatalf("rotate: %v", err)
	}
	for _, l := range f.callsTo("load-shared") {
		if strings.TrimSpace(l.fields["id"]) == "" {
			t.Fatal("load-shared issued without an id")
		}
	}
}

func TestSetPSKDrivesReauthNotPlainRekey(t *testing.T) {
	// A CREATE_CHILD_SA rekey carries no AUTH payload and never re-reads
	// credentials, so without reauth=yes the new PPK would never be used.
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK(psk32(0x04)); err != nil {
		t.Fatalf("rotate: %v", err)
	}
	rekeys := f.callsTo("rekey")
	if len(rekeys) != 1 {
		t.Fatalf("want 1 rekey, got %d", len(rekeys))
	}
	if got := rekeys[0].fields["reauth"]; got != "yes" {
		t.Errorf("reauth = %q, want yes", got)
	}
	// Selected by unique id, NOT by connection name. `ike = <connection>` makes
	// charon reauthenticate every SA on the connection, and because a
	// make-before-break reauth builds the replacement before dropping the
	// original, N SAs become 2N -- a multiplier that took a live two-node run to
	// 140 concurrent SAs. `ike-id` costs exactly one reauthentication.
	if got := rekeys[0].fields["ike"]; got != "" {
		t.Errorf("ike = %q, want it unset so the rekey cannot fan out", got)
	}
	if got := rekeys[0].fields["ike-id"]; got != "1" {
		t.Errorf("ike-id = %q, want 1 (the only SA the fake reports)", got)
	}
}

func TestSetPSKInitiatesWhenNoSAExists(t *testing.T) {
	// arnika starts rotating before the first IKE_AUTH completes, so an empty
	// SA list is the normal state at boot rather than an error.
	//
	// It must not be reported as a failed rotation: arnika answers a failed
	// SetPSK with InvalidateTunnel, which installs a random PPK the peer cannot
	// match -- poisoning the credential the pending handshake was about to use.
	// It must instead bring the lane up, because charon does not reliably retry
	// an initiation the peer rejected while it was still loading its config.
	f := newFakeVici(t)
	f.saIDs = nil

	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK(psk32(0x07)); err != nil {
		t.Fatalf("rotate with no SA must succeed, got: %v", err)
	}

	if n := len(f.callsTo("rekey")); n != 0 {
		t.Errorf("got %d rekey calls, want 0 -- there is no SA to reauthenticate", n)
	}
	initiates := f.callsTo("initiate")
	if len(initiates) != 1 {
		t.Fatalf("want 1 initiate, got %d", len(initiates))
	}
	if got := initiates[0].fields["child"]; got != "tunnel" {
		t.Errorf("child = %q, want tunnel", got)
	}
	if got := initiates[0].fields["ike"]; got != "pqcqkd-vpn" {
		t.Errorf("ike = %q, want pqcqkd-vpn", got)
	}
}

func TestSetPSKOnResponderLoadsButDoesNotDrive(t *testing.T) {
	// Both peers rotate their own copy of the PPK, but they share one IKE_SA.
	// If both also reauthenticate it, each rotation triggers two
	// make-before-break reauthentications and the SA count climbs by one per
	// rotation forever. The responder loads and stops there.
	f := newFakeVici(t)
	cfg := testConfig(f.path)
	cfg.DriveReauth = false

	repo, err := NewStrongswanViciRepository(cfg)
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK(psk32(0x08)); err != nil {
		t.Fatalf("rotate: %v", err)
	}

	// The load is the part that must still happen: it is what lets this node
	// answer the initiator's IKE_AUTH.
	if n := len(f.callsTo("load-shared")); n != 1 {
		t.Errorf("got %d load-shared calls, want 1", n)
	}
	if n := len(f.callsTo("rekey")); n != 0 {
		t.Errorf("got %d rekey calls, want 0 -- the peer drives the SA", n)
	}
	if n := len(f.callsTo("initiate")); n != 0 {
		t.Errorf("got %d initiate calls, want 0 -- the responder never initiates", n)
	}
}

func TestSetPSKFailsWhenRekeyMatchesNothing(t *testing.T) {
	// success=yes with matches=0 is charon's normal answer for a selector that
	// matched no SA. Treating that as success would report a rotation that
	// never reached the daemon.
	f := newFakeVici(t)
	f.responses["rekey"] = map[string]string{"success": "yes", "matches": "0"}

	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	err = repo.SetPSK(psk32(0x05))
	if err == nil {
		t.Fatal("expected error when rekey matches no SA")
	}
	if !strings.Contains(err.Error(), "matched no IKE_SA") {
		t.Errorf("error = %v, want it to mention matching no IKE_SA", err)
	}
}

func TestSetPSKDoesNotUnloadPreviousWhenReauthFails(t *testing.T) {
	f := newFakeVici(t)
	f.failOn["rekey"] = "no matching SA"

	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK(psk32(0x06)); err == nil {
		t.Fatal("expected rotation to fail")
	}
	if n := len(f.callsTo("unload-shared")); n != 0 {
		t.Fatalf("unloaded a credential despite failed reauth (%d calls)", n)
	}
}

func TestSetPSKRejectsShortKey(t *testing.T) {
	// RFC 8784: the PPK must carry at least 256 bits of entropy.
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	short := base64.StdEncoding.EncodeToString(make([]byte, 16))
	err = repo.SetPSK(short)
	if err == nil {
		t.Fatal("expected short PPK to be rejected")
	}
	if !strings.Contains(err.Error(), "RFC 8784") {
		t.Errorf("error = %v, want it to cite the RFC 8784 entropy floor", err)
	}
	if n := len(f.callsTo("load-shared")); n != 0 {
		t.Fatalf("short key reached charon (%d load-shared calls)", n)
	}
}

func TestSetPSKRejectsNonBase64(t *testing.T) {
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK("not!valid!base64"); err == nil {
		t.Fatal("expected non-base64 PSK to be rejected")
	}
}

func TestInvalidateTunnelInstallsRandomKey(t *testing.T) {
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}

	orig := randRead
	t.Cleanup(func() { randRead = orig })
	randRead = func(b []byte) error {
		for i := range b {
			b[i] = 0xAB
		}
		return nil
	}

	if err := repo.InvalidateTunnel(); err != nil {
		t.Fatalf("invalidate: %v", err)
	}
	loads := f.callsTo("load-shared")
	if len(loads) != 1 {
		t.Fatalf("want 1 load-shared, got %d", len(loads))
	}
	if data := loads[0].fields["data"]; len(data) != 32 || data[0] != 0xAB {
		t.Errorf("data = %d bytes starting %#x, want 32 bytes of 0xAB", len(data), data[0])
	}
}

func TestInvalidateTunnelPropagatesRandomnessFailure(t *testing.T) {
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}

	orig := randRead
	t.Cleanup(func() { randRead = orig })
	randRead = func([]byte) error { return errors.New("entropy pool drained") }

	if err := repo.InvalidateTunnel(); err == nil {
		t.Fatal("expected randomness failure to surface, not be silently replaced")
	}
	if n := len(f.callsTo("load-shared")); n != 0 {
		t.Fatalf("issued load-shared despite failed randomness (%d calls)", n)
	}
}

func TestConstructorFailsOnUnreachableSocket(t *testing.T) {
	cfg := testConfig(filepath.Join(t.TempDir(), "absent.vici"))
	if _, err := NewStrongswanViciRepository(cfg); err == nil {
		t.Fatal("expected construction to fail against a missing socket")
	}
}

func TestNeverInvokesLoadCreds(t *testing.T) {
	// swanctl --load-creds is a destructive sync that would unload the rotating
	// QKD PPK. This adapter must never trigger that path.
	f := newFakeVici(t)
	repo, err := NewStrongswanViciRepository(testConfig(f.path))
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if err := repo.SetPSK(psk32(0x07)); err != nil {
		t.Fatalf("rotate: %v", err)
	}
	for _, r := range f.requests {
		if r.name == "load-creds" || r.name == "clear-creds" {
			t.Fatalf("adapter issued %q, which would destroy injected credentials", r.name)
		}
	}
}

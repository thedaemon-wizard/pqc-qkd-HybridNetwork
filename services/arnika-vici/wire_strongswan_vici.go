//go:build strongswan_vici

// Wiring for the strongSwan VICI key writer.
//
// The package and file layout follow upstream arnika's KEYCONTROL.md ("Naming
// and File Layout Conventions"): the adapter lives in its own package,
// repositories/swanvici, carries no writer-selection tag, and this root-level
// wiring file, named `wire_` plus the tag, is the only place the tag appears.
// The tag name does not follow them: KEYCONTROL.md names writer tags
// wireguard_<backend>, and this one keeps its existing name, strongswan_vici.
// Renaming it is left to the upstream adapter PR. Build with:
//
//	go build -tags strongswan_vici
//
// See services/arnika-vici/README.md for the upstream contribution notes,
// including the one-line build-tag change wire_wireguard_netlink.go needs so
// the two writers remain mutually exclusive.
package main

import (
	"fmt"
	"os"
	"time"

	"github.com/arnika-project/arnika/config"
	"github.com/arnika-project/arnika/repositories/swanvici"
	"github.com/arnika-project/arnika/services"
)

// Environment surface specific to this adapter. Read here and not in
// config.Config, as KEYCONTROL.md's rule 3 asks of every backend: "Backend-
// specific configuration is read in the wiring file". WIREGUARD_INTERFACE and
// WIREGUARD_PEER_PUBLIC_KEY are nevertheless still mandatory in config.Parse,
// which is an upstream wart this adapter inherits -- see README.md.
const (
	envViciSocket     = "VICI_SOCKET"
	envViciConnection = "VICI_CONNECTION"
	envViciPPKID      = "VICI_PPK_ID"
	envViciPrefix     = "VICI_CREDENTIAL_PREFIX"
	envViciTimeout    = "VICI_REAUTH_TIMEOUT"
	envViciRole       = "VICI_IKE_ROLE"
	envViciChild      = "VICI_CHILD"
	envViciBootstrap  = "VICI_BOOTSTRAP_ID"
)

func getKeyWriterService(cfg *config.Config) (*services.KeyWriterService, error) {
	viciCfg := swanvici.Config{
		SocketPath:            os.Getenv(envViciSocket),
		ConnectionName:        os.Getenv(envViciConnection),
		ChildName:             os.Getenv(envViciChild),
		PPKID:                 os.Getenv(envViciPPKID),
		CredentialPrefix:      os.Getenv(envViciPrefix),
		BootstrapCredentialID: os.Getenv(envViciBootstrap),
	}

	// No silent defaults: an unset or malformed timeout is a configuration
	// error, not something to paper over with a guess.
	rawTimeout := os.Getenv(envViciTimeout)
	if rawTimeout == "" {
		return nil, fmt.Errorf("%s must be set (e.g. 30s)", envViciTimeout)
	}
	timeout, err := time.ParseDuration(rawTimeout)
	if err != nil {
		return nil, fmt.Errorf("%s is not a valid duration: %w", envViciTimeout, err)
	}
	viciCfg.ReauthTimeout = timeout

	// Which peer owns the shared IKE_SA. Both peers rotate the PPK; exactly one
	// reauthenticates. No default: guessing wrong gives either two drivers (the
	// SA count grows without bound) or none (rotated keys never enter the key
	// schedule), and both look like a working tunnel from the outside.
	switch role := os.Getenv(envViciRole); role {
	case "initiator":
		viciCfg.DriveReauth = true
	case "responder":
		viciCfg.DriveReauth = false
	case "":
		return nil, fmt.Errorf("%s must be set to \"initiator\" or \"responder\"", envViciRole)
	default:
		return nil, fmt.Errorf("%s is %q; expected \"initiator\" or \"responder\"",
			envViciRole, role)
	}

	// The reauthentication this adapter drives must complete within one arnika
	// rotation interval, otherwise rotations queue up behind each other.
	if timeout >= cfg.Interval {
		return nil, fmt.Errorf(
			"%s (%s) must be shorter than INTERVAL (%s), otherwise key rotations overlap",
			envViciTimeout, timeout, cfg.Interval)
	}

	viciRepo, err := swanvici.NewRepository(viciCfg)
	if err != nil {
		return nil, err
	}
	// KeyWriterService owns invalidation (a fresh random key through SetPSK)
	// and serialises every write, so the repository implements SetPSK only.
	return services.NewKeyWriterService(viciRepo), nil
}

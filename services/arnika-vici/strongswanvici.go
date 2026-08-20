//go:build strongswan_vici

// Key-writer adapter selection for the strongSwan VICI backend.
//
// This mirrors upstream arnika's wireguardnetlink.go: one build-tagged file per
// key-writer adapter, each providing getKeyWriterService. Build with:
//
//	go build -tags strongswan_vici
//
// See services/arnika-vici/README.md for the upstream contribution notes,
// including the one-line build-tag change wireguardnetlink.go needs so the two
// adapters remain mutually exclusive.
package main

import (
	"fmt"
	"os"
	"time"

	"github.com/arnika-project/arnika/repositories"
	"github.com/arnika-project/arnika/services"

	"github.com/arnika-project/arnika/config"
)

// Environment surface specific to this adapter. Kept separate from
// config.Config so the upstream config parser needs no change to build with
// this tag; a real upstream PR would fold these into config.Parse and make
// WIREGUARD_INTERFACE / WIREGUARD_PEER_PUBLIC_KEY conditional on the selected
// adapter (they are currently mandatory, which is an upstream wart this
// adapter inherits -- see README.md).
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
	viciCfg := repositories.ViciConfig{
		SocketPath:       os.Getenv(envViciSocket),
		ConnectionName:   os.Getenv(envViciConnection),
		ChildName:        os.Getenv(envViciChild),
		PPKID:            os.Getenv(envViciPPKID),
		CredentialPrefix: os.Getenv(envViciPrefix),
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

	viciRepo, err := repositories.NewStrongswanViciRepository(viciCfg)
	if err != nil {
		return nil, err
	}
	return services.NewKeyWriterService(viciRepo), nil
}

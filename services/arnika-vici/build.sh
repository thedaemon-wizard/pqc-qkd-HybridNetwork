#!/bin/sh
# =====================================================================
# Build arnika with the strongSwan VICI key-writer adapter.
#
# The adapter is kept outside submodules/arnika so the submodule stays a
# pristine checkout of upstream. This script overlays the adapter onto a copy of
# the upstream tree exactly as the proposed upstream PR would add it, then
# builds with -tags strongswan_vici.
#
# Usage:  build.sh <arnika-src> <adapter-src> <output-binary>
#
# Used by nodes/strongswan/Dockerfile and by CI, so the container image and the
# test job build the binary the same way.
# =====================================================================
set -eu

ARNIKA_SRC=${1:?usage: build.sh <arnika-src> <adapter-src> <output-binary>}
ADAPTER_SRC=${2:?usage: build.sh <arnika-src> <adapter-src> <output-binary>}
OUTPUT=${3:?usage: build.sh <arnika-src> <adapter-src> <output-binary>}

# Resolve to absolute paths before anything cd's. Relative arguments would
# silently stop resolving once we move into the work directory below -- which
# is exactly what happens when this is invoked from a repository root rather
# than from the Dockerfile, where the arguments are already absolute.
ARNIKA_SRC=$(cd "$ARNIKA_SRC" && pwd)
ADAPTER_SRC=$(cd "$ADAPTER_SRC" && pwd)
case $OUTPUT in
    /*) ;;
    *)  OUTPUT="$(pwd)/$OUTPUT" ;;
esac

# Upstream's own build vars (see submodules/arnika/Makefile). arnika hardens key
# material with runtime/secret, which is gated behind this GOEXPERIMENT and
# requires Go >= 1.26.
export CGO_ENABLED=0
export GOEXPERIMENT=runtimesecret

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp -a "$ARNIKA_SRC"/. "$WORK"/
cd "$WORK"

# Glob, not a single named file. Copying only strongswan-vici.go left
# strongswan-vici_test.go behind, so `go test ./repositories/...` ran arnika's
# own tests, reported ok, and never once executed the adapter's. Test files are
# ignored by `go build`, so including them here costs the build nothing.
cp "$ADAPTER_SRC"/repositories/*.go repositories/
cp "$ADAPTER_SRC/strongswanvici.go" ./

# Upstream selects the netlink writer with a trailing NEGATION, so the default
# writer is also compiled in for any adapter tag it has not been taught about:
#
#   pin 9d44332   //go:build wireguard_netlink || !wireguard_mikrotik
#   main 3a8cc13  //go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)
#
# Upstream added `&& !wireguard_netlink_netns` when it landed the netns writer
# (PR #48). That fixes netns and leaves the shape intact: each new adapter has
# to be enumerated here or it collides. `strongswan_vici` is not enumerated, so
# `-tags strongswan_vici` still satisfies the negation and still yields two
# definitions of getKeyWriterService -- one from wireguardnetlink.go and one
# from the adapter. Confirmed against main: all three of wireguardnetlink.go,
# wireguardmikrotik.go and wireguardnetlinknetns.go define that function.
#
# So this rewrite is still needed, for the same reason as before. What changed
# is only the string being rewritten. See
# 0001-make-key-writer-adapters-mutually-exclusive.patch -- the same change,
# formatted for submission upstream, and still not submitted: the maintainer
# has not been asked, and it affects writer selection for every build.
EXPECTED='//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)'
ACTUAL=$(head -1 wireguardnetlink.go)
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "FATAL: upstream changed wireguardnetlink.go's build tag." >&2
    echo "  expected: $EXPECTED" >&2
    echo "  actual:   $ACTUAL" >&2
    echo "Re-check the adapter selection logic before bumping the submodule." >&2
    exit 1
fi
{
    # Keeps upstream's own exclusion of the netns writer and adds ours.
    # Dropping `!wireguard_netlink_netns` here would silently re-break the
    # case upstream just fixed, in a tree upstream never sees.
    printf '%s\n' '//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns && !strongswan_vici)'
    tail -n +2 wireguardnetlink.go
} > wireguardnetlink.go.new
mv wireguardnetlink.go.new wireguardnetlink.go

# Pinned: govici is the official strongSwan VICI client (MIT).
go get github.com/strongswan/govici@v0.8.2
go mod tidy

go build -trimpath -ldflags "-w -s" -tags strongswan_vici -o "$OUTPUT" .
echo "built $OUTPUT with the strongSwan VICI key-writer"

# Optional, for CI. Vetting and testing have to happen in THIS tree, with the
# same -tags, because both depend on the wireguardnetlink.go build-tag change
# made above: without it, -tags strongswan_vici compiles two definitions of
# getKeyWriterService and the package does not build at all.
#
# Doing it here rather than in a separate CI step keeps one place that knows how
# to assemble the overlay. A second copy of this logic drifted from it once
# already -- the CI step vetted an unpatched tree and failed on the duplicate.
if [ "${ARNIKA_VICI_VET_AND_TEST:-0}" = "1" ]; then
    echo "--- go vet -tags strongswan_vici ./... ---"
    go vet -tags strongswan_vici ./...
    echo "--- go test -tags strongswan_vici ./repositories/... ---"
    go test -tags strongswan_vici ./repositories/... -v
fi

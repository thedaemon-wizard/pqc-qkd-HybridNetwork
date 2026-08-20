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

cp "$ADAPTER_SRC/repositories/strongswan-vici.go" repositories/
cp "$ADAPTER_SRC/strongswanvici.go" ./

# Upstream selects the netlink writer with
#     //go:build wireguard_netlink || !wireguard_mikrotik
# The trailing negation means the file is also compiled in for any NEW adapter
# tag, so without this change -tags strongswan_vici yields two definitions of
# getKeyWriterService. Narrow it so each adapter tag deselects the default.
#
# See 0001-make-key-writer-adapters-mutually-exclusive.patch -- the same change,
# formatted for submission upstream.
EXPECTED='//go:build wireguard_netlink || !wireguard_mikrotik'
ACTUAL=$(head -1 wireguardnetlink.go)
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "FATAL: upstream changed wireguardnetlink.go's build tag." >&2
    echo "  expected: $EXPECTED" >&2
    echo "  actual:   $ACTUAL" >&2
    echo "Re-check the adapter selection logic before bumping the submodule." >&2
    exit 1
fi
{
    printf '%s\n' '//go:build wireguard_netlink || (!wireguard_mikrotik && !strongswan_vici)'
    tail -n +2 wireguardnetlink.go
} > wireguardnetlink.go.new
mv wireguardnetlink.go.new wireguardnetlink.go

# Pinned: govici is the official strongSwan VICI client (MIT).
go get github.com/strongswan/govici@v0.8.2
go mod tidy

go build -trimpath -ldflags "-w -s" -tags strongswan_vici -o "$OUTPUT" .
echo "built $OUTPUT with the strongSwan VICI key-writer"

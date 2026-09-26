#!/bin/sh
# =====================================================================
# Build arnika with the strongSwan VICI key-writer adapter.
#
# The adapter is kept outside submodules/arnika so the submodule stays a
# pristine checkout of upstream. This script overlays the adapter onto a copy of
# the upstream tree exactly as the proposed upstream PR would add it, then
# builds with -tags strongswan_vici.
#
# Layout overlaid (upstream KEYCONTROL.md, "Naming and File Layout Conventions"):
#
#   repositories/swanvici/*.go   the adapter package, no writer-selection tag
#   wire_strongswan_vici.go      the wiring file, //go:build strongswan_vici
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

# The adapter's paths inside the arnika tree, and the upstream default writer
# whose build tag has to be narrowed. Named once, because every check below
# refers to them.
ADAPTER_PKG=repositories/swanvici
ADAPTER_WIRE=wire_strongswan_vici.go
DEFAULT_WRITER=wire_wireguard_netlink.go

# Refuse to overlay onto a tree that already has either file. If upstream ever
# ships its own strongSwan writer under these names, copying ours over it would
# build a binary that is neither upstream's nor ours, with nothing in the log
# to say so. That is a decision for a person, not for this script.
for path in "$ADAPTER_PKG" "$ADAPTER_WIRE"; do
    if [ -e "$ARNIKA_SRC/$path" ]; then
        echo "FATAL: the arnika tree already contains $path." >&2
        echo "  Upstream now ships a file this overlay would replace." >&2
        echo "  Compare it with services/arnika-vici before building." >&2
        exit 1
    fi
done
# The adapter's own sources must be where this script copies them from. A glob
# that matched nothing would otherwise be copied literally and fail with a
# cp error that does not say what is missing.
if ! ls "$ADAPTER_SRC/$ADAPTER_PKG"/*.go >/dev/null 2>&1; then
    echo "FATAL: no Go sources in $ADAPTER_SRC/$ADAPTER_PKG" >&2
    exit 1
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp -a "$ARNIKA_SRC"/. "$WORK"/
cd "$WORK"

# Glob, not a single named file. Copying only the adapter source once left its
# _test.go behind, so `go test` ran arnika's own tests, reported ok, and never
# once executed the adapter's. Test files are ignored by `go build`, so
# including them here costs the build nothing.
mkdir -p "$ADAPTER_PKG"
cp "$ADAPTER_SRC/$ADAPTER_PKG"/*.go "$ADAPTER_PKG"/
cp "$ADAPTER_SRC/$ADAPTER_WIRE" ./

# Upstream selects the netlink writer with a trailing NEGATION, so the default
# writer is also compiled in for any writer tag it has not been taught about:
#
#   pin 9d44332   //go:build wireguard_netlink || !wireguard_mikrotik
#   pin 3a8cc13   //go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)
#   pin f4cf9ba   the same line, in wire_wireguard_netlink.go (PR #51 renamed
#                 wireguardnetlink.go and the other writers to wire_*.go)
#
# Upstream added `&& !wireguard_netlink_netns` when it landed the netns writer
# (PR #48). That fixes netns and leaves the shape intact: each new writer has to
# be enumerated here or it collides. `strongswan_vici` is not enumerated, so
# `-tags strongswan_vici` still satisfies the negation and still yields two
# definitions of getKeyWriterService -- one from wire_wireguard_netlink.go and
# one from wire_strongswan_vici.go.
#
# So this rewrite is still needed. It is not proposed upstream on its own:
# upstream's KEYCONTROL.md makes extending the default's negation part of adding
# a writer ("Update the default constraint", step 3 of "Adding a new key
# writer"), so it travels with an adapter PR.
EXPECTED='//go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)'
if [ ! -f "$DEFAULT_WRITER" ]; then
    echo "FATAL: the arnika tree has no $DEFAULT_WRITER." >&2
    echo "  Upstream moved the default writer again; teach this script the new" >&2
    echo "  layout before bumping the submodule." >&2
    exit 1
fi
ACTUAL=$(head -1 "$DEFAULT_WRITER")
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "FATAL: upstream changed $DEFAULT_WRITER's build tag." >&2
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
    tail -n +2 "$DEFAULT_WRITER"
} > "$DEFAULT_WRITER.new"
mv "$DEFAULT_WRITER.new" "$DEFAULT_WRITER"

# Pinned: govici is the official strongSwan VICI client (MIT).
go get github.com/strongswan/govici@v0.8.2
go mod tidy

go build -trimpath -ldflags "-w -s" -tags strongswan_vici -o "$OUTPUT" .
echo "built $OUTPUT with the strongSwan VICI key-writer"

# Optional, for CI. Vetting and testing have to happen in THIS tree, with the
# same -tags, because both depend on the build-tag change made above: without
# it, -tags strongswan_vici compiles two definitions of getKeyWriterService and
# the package does not build at all.
#
# Doing it here rather than in a separate CI step keeps one place that knows how
# to assemble the overlay. A second copy of this logic drifted from it once
# already -- the CI step vetted an unpatched tree and failed on the duplicate.
if [ "${ARNIKA_VICI_VET_AND_TEST:-0}" = "1" ]; then
    echo "--- go vet -tags strongswan_vici ./... ---"
    go vet -tags strongswan_vici ./...
    # -race is not available: it needs cgo, and CGO_ENABLED=0 is upstream's
    # build setting for every writer.
    echo "--- go test -tags strongswan_vici ./$ADAPTER_PKG/... ---"
    go test -tags strongswan_vici "./$ADAPTER_PKG/..." -v

    # The narrowing must fix exactly one build and break none. Mirrors
    # upstream's own "Two writer tags must never compile together" CI check
    # (arnika .github/workflows/ci.yml), with this writer added to the set.
    echo "--- the default build (no writer tag) still selects the netlink writer ---"
    go build -o /dev/null .
    # Every upstream writer tag, paired with ours, must fail -- and fail on the
    # duplicate definition, not on some unrelated compile error that would
    # make this check pass for the wrong reason. The list is upstream's
    # WRITERS array at f4cf9ba; a writer upstream adds later is caught by
    # tests/test_the_build_tag_narrowing_is_exhaustive.py, which derives the
    # set from the tree instead of from this list.
    for tag in wireguard_netlink wireguard_mikrotik wireguard_netlink_netns; do
        echo "--- -tags '$tag strongswan_vici' must not build ---"
        if out=$(go build -tags "$tag strongswan_vici" -o /dev/null . 2>&1); then
            echo "FATAL: tags '$tag strongswan_vici' built; two writers compiled together" >&2
            exit 1
        fi
        case $out in
            *"getKeyWriterService redeclared"*)
                echo "ok: fails on the duplicate getKeyWriterService" ;;
            *)
                echo "FATAL: tags '$tag strongswan_vici' failed, but not on the duplicate writer:" >&2
                printf '%s\n' "$out" >&2
                exit 1 ;;
        esac
    done
fi

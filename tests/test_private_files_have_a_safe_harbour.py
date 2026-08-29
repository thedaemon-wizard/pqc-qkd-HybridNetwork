"""Operator-private files must be protected by a rule that travels.

The operator keeps working files out of this repository -- planning notes, host
access details, commercial material. They were held back by `.git/info/exclude`,
which is **per-clone**: it is not committed and does not travel. Verified by
simulating a clean clone with only the repository's own `.gitignore`, where
`git add -A` staged both of them.

It had held in the working copy, which is why several `git add -A` runs never
staged them, but that was a property of one machine rather than of the project.

The safe harbour is a generic `/private/` directory. Generic on purpose: listing
the filenames in `.gitignore` would disclose them in a public repository, which
is exactly what the rule exists to prevent. `VERIFICATION_CHECKLIST.md` row 6.4
made that mistake -- it spelled out two private filenames while asserting that
"a reference from a tracked file discloses the name", and its own grep returned
the checklist.

**This file used to make the same mistake, one level down.** It carried the
names in plaintext so it could grep for them, and then exempted itself from its
own check by path. That exemption was not a wart in the guard; it was the guard
recording that it violated the rule it enforces. This repository is public, so
the test asserting "no tracked file names a private file" was itself the tracked
file naming them -- to anyone reading the suite, and to anyone searching it.

So the names are stored as SHA-256 digests and candidate tokens are hashed
before comparison. The guard keeps working -- in CI, with no artefact and no
submodule -- and the self-exemption is gone, because there is no longer a
plaintext name to exempt.

**What this buys, stated narrowly, because the obvious reading is wrong.**

It keeps the names out of the TIP TREE. That is all. It is not a confidentiality
measure, and describing it as one would be false:

  - The plaintext is in published history. **133 commits reachable from `main`
    have it in their tree** -- an earlier version of this docstring said
    "three", which counted only the commits that changed it rather than the
    commits that contain it, and understated the cost of a history rewrite by
    a factor of forty. The diff of the commit that removes it prints it in
    full besides.
    GitHub renders and indexes blame, file history and commit diffs, so a reader
    still finds the names by clicking rather than by guessing.
  - The digests are unsalted, necessarily: the check must run from a fresh clone
    with no secret to key on. A filename is a small search space, so a candidate
    list of a few dozen recovers them. This was demonstrated, not assumed --
    all preimages fell to a 50-candidate sweep built only from the blob still
    on `main`.

Removing them from history means rewriting a published branch, which is the
operator's call, not a test's. Until that happens the honest description is:
this stops NEW references accumulating and keeps a browsing reader from
tripping over one. It does not make the names private, because they are not.

**The tokeniser is the load-bearing part, and the first version was weaker than
the substring test it replaced.** Hashing forces exact-token equality, so
anything that is not exactly the hashed string slips through. The first draft
matched `<name>.md` and missed `<name>.md.` (a trailing sentence period joins
the token), `<name>.md-old`, `private/<name>/` and `<name>*` -- one shape out of
five, where the old `if "<name>.md" in body` caught all five.

The fix is to store STEMS and to expand every candidate at each `.`, `-` and `_`
boundary. The first attempt at that emitted only PREFIXES, which fixed the
right-hand cases and left every left-hand one (`notes-<name>.md`,
`2026-08-<name>.md`, `my_<name>.md`) invisible -- all three of which the
substring test had caught. The claim that prefixes made this "a superset" was
therefore false; the two were incomparable. Spans now run in both directions.

A stem also matches the bare English word, which is a false positive in the
loud direction and is the one to prefer.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"

# SHA-256 of lowercased STEMS, not of full filenames.
#
# Stems, because an extension is the easiest thing to vary: a digest of
# `<name>.md` is blind to `<name>.rst`, `<name>*`, `private/<name>/` and a
# trailing sentence period. Two of these are the two spellings of one name; the
# third is the shared prefix of a family.
#
# To add one: hash the lowercased stem and paste the digest. Do not paste the
# stem, not even in a comment; that is the whole point of this file.
_PRIVATE_DIGESTS = frozenset({
    "59b817983b45e008fc59f901c8f87153e7c1fc80a34ec5cad78bd0bdab1edbeb",
    "0024e33f12d44eb69133a0612478c357fe0c7d5477a95f842a6a33f9a56bf1ad",
    "8ed11a91cf0dec238ca8550097fb6d2bc4ce6251899ea0b020c3a677c08e354b",
})

# Filename-shaped runs. Includes `.`, `-` and `_` so a full filename arrives as
# one token; _tokens() then takes it apart again at every one of those
# boundaries. Anything outside this class -- `/`, whitespace, quotes, `*` -- is
# already a separator, so `private/<name>/` and `<name>*` arrive split.
_TOKEN = re.compile(r"[a-z0-9_.-]+")
_SEPARATORS = "._-"


def _tokens(text: str) -> set[str]:
    """Every candidate a private name could appear as.

    For each filename-shaped run, emit every span that both STARTS and ENDS on
    a `.`, `-` or `_` boundary (or the ends of the run):

        <name>.md            -> <name>, md, <name>.md
        see <name>.md.       -> ...                       (trailing period)
        <name>.md-old        -> ...                       (right-decorated)
        notes-<name>.md      -> notes, <name>, md, ...    (LEFT-decorated)
        2026-08-<name>.md    -> ...                       (date-prefixed)
        private/<name>/      -> private, <name>           (already split on /)
        <name>*              -> <name>                    (already split on *)

    **Prefixes alone were not enough, and the previous docstring here claimed
    otherwise.** It said this made the check "a SUPERSET of the substring test
    it replaced". That was false: emitting only prefixes caught right-hand
    decoration and missed every left-hand one, while the substring test it
    replaced caught both. The two were incomparable, not ordered, and the three
    left-decorated forms above were live misses.

    The accurate property, now that spans run in both directions: a stored stem
    is found wherever it appears as a separator-delimited component of a
    filename-shaped token. It is still not literal substring matching -- a stem
    buried inside a word with no separator (`xx<name>yy`) is not a filename
    reference and is deliberately not matched.
    """
    out: set[str] = set()
    for run in _TOKEN.findall(text.lower()):
        cuts = [i for i, ch in enumerate(run) if ch in _SEPARATORS]
        starts = [0] + [i + 1 for i in cuts]
        ends = cuts + [len(run)]
        for s in starts:
            for e in ends:
                if e > s:
                    out.add(run[s:e])
    return out


def _names_a_private_file(text: str) -> bool:
    return any(hashlib.sha256(t.encode()).hexdigest() in _PRIVATE_DIGESTS
               for t in _tokens(text))


def _ignored(relpath: str) -> bool:
    """Ask git itself, rather than re-implementing gitignore matching."""
    return subprocess.run(
        ["git", "check-ignore", "-q", relpath],
        cwd=ROOT, capture_output=True, check=False,
    ).returncode == 0


def test_the_private_directory_is_ignored():
    assert _ignored("private/anything.md"), (
        "/private/ is no longer ignored, so operator-private files placed there "
        "would be committed."
    )
    assert _ignored("private/nested/deep/file.txt"), "the rule must cover subdirectories"


def test_the_rule_lives_in_gitignore_not_only_in_a_local_exclude():
    """The whole point: a per-clone exclude does not protect a fresh clone."""
    assert "/private/" in GITIGNORE.read_text(encoding="utf-8"), (
        "the /private/ rule is not in the tracked .gitignore. If it has moved to "
        ".git/info/exclude, the protection has stopped travelling to other clones "
        "-- which is the defect this replaced."
    )


def test_gitignore_does_not_name_the_private_files():
    """A rule that names what it hides defeats itself in a public repository."""
    assert not _names_a_private_file(GITIGNORE.read_text(encoding="utf-8")), (
        ".gitignore names an operator-private file. Naming one in a tracked "
        "file discloses it; that is why the rule is a generic directory."
    )


def _tracked() -> list[str]:
    """`-z`, because `stdout.split()` shreds any path containing a space.

    A shredded path yields fragments that are not files, so they are skipped --
    and the count of things scanned goes UP while coverage goes down. No
    tracked path contains a space today; this is so that stops being load
    bearing.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True,
        check=False).stdout
    return [p for p in out.split("\0") if p]


def test_no_tracked_file_names_the_private_files():
    """Same rule, applied to the whole repository rather than one file.

    No path is exempt, including this one. That is now possible because the
    names are not written here.

    Both the BODY and the PATH are checked. Body-only was the original shape,
    and it could not see the one case that matters most: committing the private
    file itself. A file named for a private stem discloses it in `git ls-files`
    whatever its contents are, and the body scan would have passed it.
    """
    offenders = []
    for rel in _tracked():
        if _names_a_private_file(rel):
            offenders.append(f"{rel} (path)")
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _names_a_private_file(body):
            offenders.append(rel)
    assert not offenders, (
        f"these tracked files name an operator-private file: {offenders}. "
        "Describe the rule, not the filenames."
    )


# --------------------------------------------------------------------------
# The detector has to actually detect. A hashed guard fails silently if the
# tokenisation stops producing the form that was hashed, and it would fail in
# the safe-looking direction: everything passes.
# --------------------------------------------------------------------------

# A stand-in for a private stem. Everything below is expressed against this
# rather than against a real name, so the tests can be thorough without the
# file disclosing anything.
_PROBE = "zzprobestem"
_PROBE_DIGEST = hashlib.sha256(_PROBE.encode()).hexdigest()


def _caught(text: str) -> bool:
    """`_names_a_private_file` with the probe stem treated as private."""
    patched = _PRIVATE_DIGESTS | {_PROBE_DIGEST}
    return any(hashlib.sha256(t.encode()).hexdigest() in patched
               for t in _tokens(text))


def test_the_detector_catches_every_shape_a_filename_appears_in():
    """The first hashed draft caught one of these five and shipped anyway.

    Hashing forces exact-token equality, so each way of decorating a name is a
    separate way to miss it. The substring test this replaced caught all five;
    a replacement that caught one would have been a regression sold as an
    improvement.
    """
    for text in (
        f"see {_PROBE}.md",              # the plain reference
        f"see {_PROBE}.md.",             # trailing sentence period
        f"see {_PROBE}.md-old",          # right-decorated
        f"see {_PROBE}.md.bak",          # second extension
        f"private/{_PROBE}/",            # a directory rule
        f"{_PROBE}*",                    # a glob
        f"/{_PROBE}.md",                 # a rooted gitignore entry
        f"'{_PROBE}.md'",                # quoted, as in a grep pattern
        f"notes-{_PROBE}.md",            # LEFT-decorated -- missed by prefixes
        f"2026-08-{_PROBE}.md",          # date-prefixed  -- missed by prefixes
        f"my_{_PROBE}.md",               # underscore-prefixed
        f"draft.{_PROBE}.md",            # dotted prefix
    ):
        assert _caught(text), f"missed: {text!r}"


def test_the_detector_does_not_fire_on_unrelated_text():
    """Loud is the right direction to fail, but not on everything."""
    for text in ("see docs/keyrate.md for the model",
                 "a perfectly ordinary sentence",
                 f"{_PROBE}x.md",        # different stem, not a boundary
                 f"x{_PROBE}.md"):       # substring, but not at a boundary
        assert not _caught(text), f"false positive on {text!r}"


def test_the_boundary_expansion_runs_in_both_directions():
    """Pin the mechanism, so a 'simplification' has to argue with a test.

    Prefixes alone shipped once and missed every left-decorated reference, so
    the suffix and interior spans are asserted explicitly rather than implied.
    """
    toks = _tokens("aa.bb-cc_dd.md")
    for expected in ("aa", "aa.bb", "aa.bb-cc", "aa.bb-cc_dd",   # prefixes
                     "md", "dd.md", "cc_dd.md",                   # suffixes
                     "bb", "cc", "dd", "bb-cc", "cc_dd"):         # interior
        assert expected in toks, f"span {expected!r} not emitted"


def test_every_stored_digest_is_a_sha256_and_none_is_a_plaintext_token():
    """Guards against someone 'fixing' a miss by pasting the name back in."""
    for d in _PRIVATE_DIGESTS:
        assert re.fullmatch(r"[0-9a-f]{64}", d), (
            f"{d!r} is not a SHA-256 digest. If a name was pasted in to make a "
            f"check work, the file is disclosing it again.")

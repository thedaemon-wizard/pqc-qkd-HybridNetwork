/**
 * A known-answer test for ML-KEM that is not self-referential.
 *
 * The project had no KAT. `/api/kat` was named one but seeded nothing and
 * compared nothing, and the obvious remedy -- record what this code produces
 * and assert it forever after -- proves only that the code equals itself. A
 * golden vector taken from the implementation under test cannot detect a
 * consistently wrong implementation.
 *
 * These vectors are different: each digest was produced INDEPENDENTLY by two
 * implementations written in different languages by different authors, from
 * the same seed, and they agreed byte for byte.
 *
 *   liboqs   C,  in the pqc-validator image, via `generate_keypair_seed`
 *   @noble   JS, in the browser bundle, via `ml_kem*.keygen(seed)`
 *
 * ML-KEM key generation is deterministic given the 64-byte seed (FIPS 203
 * `ML-KEM.KeyGen_internal`, seed = d || z), so agreement is only possible if
 * both implement the standard identically -- including the seed byte order,
 * the matrix expansion and the encoding of the encapsulation key. A vector
 * that two independent implementations arrive at separately is evidence about
 * FIPS 203; a vector one implementation reports about itself is not.
 *
 * The liboqs side of the comparison runs in CI inside the pqc-validator image
 * (tests/test_mlkem_kat_matches_liboqs.py). This file pins the browser side to
 * the same digests, so a drift in either implementation breaks one of the two.
 *
 * To regenerate after a deliberate upgrade, recompute from BOTH sides and only
 * accept a new digest if they still agree. Taking the new value from whichever
 * side changed would silently convert this back into a self-check.
 */
import { describe, expect, it } from "vitest";

import { ml_kem1024, ml_kem512, ml_kem768 } from "@noble/post-quantum/ml-kem.js";

/** The all-0x01 seed. Arbitrary, fixed, and used identically on both sides. */
const SEED = new Uint8Array(64).fill(0x01);

async function sha256Hex(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data as BufferSource);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Encapsulation-key digests for seed = 0x01 x 64.
 *
 * Cross-derived 2026-08-22: liboqs in the pqc-validator image and
 * @noble/post-quantum 0.7.0 in Node produced identical bytes for all three
 * parameter sets. Public-key lengths are FIPS 203 Table 2.
 */
const CROSS_DERIVED = [
  {
    name: "ML-KEM-512", impl: ml_kem512, publicKeyLen: 800,
    sha256: "871c0a93974ea840f32bf4fd4352e37a5e2422815e0f43f73f6acd4895b93e37",
  },
  {
    name: "ML-KEM-768", impl: ml_kem768, publicKeyLen: 1184,
    sha256: "e68d60857f9cb41f88c278ca430e472c6df5679fd5bac3ce872334293c5d0c42",
  },
  {
    name: "ML-KEM-1024", impl: ml_kem1024, publicKeyLen: 1568,
    sha256: "05227acb49aefea81141d2bbc32ed84178283517d724ebc04d570ce84725f656",
  },
] as const;

describe("ML-KEM key generation matches an independently derived vector", () => {
  it.each(CROSS_DERIVED)("$name", async ({ impl, publicKeyLen, sha256 }) => {
    const { publicKey } = impl.keygen(SEED);
    expect(publicKey.length).toBe(publicKeyLen);
    expect(await sha256Hex(publicKey)).toBe(sha256);
  });

  it("gives every parameter set a distinct key", () => {
    // A vector table is easy to mis-transcribe. If two rows ever matched, one
    // of them would be pinned against the wrong algorithm and still pass.
    const keys = CROSS_DERIVED.map((v) => v.impl.keygen(SEED).publicKey.length);
    expect(new Set(keys).size).toBe(CROSS_DERIVED.length);
    expect(new Set(CROSS_DERIVED.map((v) => v.sha256)).size).toBe(CROSS_DERIVED.length);
  });
});

describe("the determinism the vector depends on", () => {
  it("returns the same key for the same seed", () => {
    const a = ml_kem768.keygen(SEED);
    const b = ml_kem768.keygen(SEED);
    expect(a.publicKey).toEqual(b.publicKey);
    expect(a.secretKey).toEqual(b.secretKey);
  });

  it("returns a different key for a different seed", () => {
    // Guards against an implementation that ignores the seed entirely, which
    // would make every seeded assertion above pass for the wrong reason --
    // the precise failure `/api/kat` had, where the seed was parsed and
    // discarded.
    const other = new Uint8Array(64).fill(0x02);
    expect(ml_kem768.keygen(SEED).publicKey).not.toEqual(ml_kem768.keygen(other).publicKey);
  });

  it("encapsulates deterministically given the message", () => {
    // FIPS 203 Encaps_internal(ek, m). Needed for the shared-secret half of a
    // KAT to mean anything.
    const { publicKey } = ml_kem768.keygen(SEED);
    const m = new Uint8Array(32).fill(0x02);
    const one = ml_kem768.encapsulate(publicKey, m);
    const two = ml_kem768.encapsulate(publicKey, m);
    expect(one.cipherText).toEqual(two.cipherText);
    expect(one.sharedSecret).toEqual(two.sharedSecret);
  });

  it("round-trips the deterministic ciphertext", () => {
    const { publicKey, secretKey } = ml_kem768.keygen(SEED);
    const { cipherText, sharedSecret } = ml_kem768.encapsulate(publicKey, new Uint8Array(32).fill(0x02));
    expect(ml_kem768.decapsulate(cipherText, secretKey)).toEqual(sharedSecret);
  });
});

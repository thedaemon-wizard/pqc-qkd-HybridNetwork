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

const unhex = (h: string) => Uint8Array.from(h.match(/../g)!.map((b) => parseInt(b, 16)));

/**
 * NIST ACVP test case, ML-KEM-768 key generation.
 *
 * This is the authoritative vector: it comes from NIST's own validation suite,
 * not from any implementation in this repository.
 *
 *   usnistgov/ACVP-Server, gen-val/json-files/ML-KEM-keyGen-FIPS203/
 *   internalProjection.json @ 15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0
 *   testGroups[1].tests[0]  -- parameterSet ML-KEM-768, tgId 2, tcId 26
 *
 * ACVP supplies `d` and `z` as separate 32-byte fields. FIPS 203 Algorithm 16
 * takes them as an ordered pair KeyGen_internal(d, z); the 64-byte `d || z`
 * packing is an implementation convention, and @noble uses it -- seed[0..31]
 * is d, seed[32..63] is z. Reversing the order fails, which was checked rather
 * than assumed.
 *
 * A warning worth carrying: the C2SP/CCTV "intermediate" vectors look ideal
 * because they chain d, z, ek, dk, m, K and c in one file, but they target
 * FIPS 203 *ipd* rather than the final August 2024 standard and every value
 * mismatches. They were tested and discarded.
 */
const ACVP_ML_KEM_768_KEYGEN = {
  d: "e582b7d75e6c80b05ae392a1fc9f7153b12390fd99930368cc67a768baebc8a0",
  z: "1cdacb8740c0b87c4a379575f187b367cbfa3b300bf591b109f79816e9cbe8f0",
  ekLen: 1184,
  dkLen: 2400,
  ekSha256: "4158f6afb5e516c99f1da07da8c651348422b17c1f4e9a08ad73fb1f91249b3e",
  dkSha256: "7aab35839207f72b310abe36e2daa1cc7ff6f7fa8941e439967cd47d9b437079",
} as const;

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

describe("ML-KEM-768 matches the NIST ACVP vector", () => {
  const { d, z, ekLen, dkLen, ekSha256, dkSha256 } = ACVP_ML_KEM_768_KEYGEN;

  it("derives the published encapsulation and decapsulation keys", async () => {
    const { publicKey, secretKey } = ml_kem768.keygen(unhex(d + z));
    expect(publicKey.length).toBe(ekLen);
    expect(secretKey.length).toBe(dkLen);
    expect(await sha256Hex(publicKey)).toBe(ekSha256);
    expect(await sha256Hex(secretKey)).toBe(dkSha256);
  });

  it("fails if d and z are swapped", async () => {
    // The 64-byte packing is convention, not spec, so the ordering is the one
    // thing about this vector that could be wrong while everything still looks
    // plausible. Asserting the wrong order FAILS is what pins it.
    const { publicKey } = ml_kem768.keygen(unhex(z + d));
    expect(await sha256Hex(publicKey)).not.toBe(ekSha256);
  });
});

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

/**
 * Client-side post-quantum cryptography.
 *
 * Runs FIPS 203 / 204 / 205 primitives in the browser via `@noble/post-quantum`
 * so the public demo's crypto-agility matrix and KEM round-trips need no
 * backend at all. The liboqs-backed `pqc-validator` service remains the
 * server-side cross-check for the full stack and for CI.
 *
 * HONEST LIMITATIONS -- surfaced in the UI, not buried here:
 *
 *   * `@noble/post-quantum` is SELF-audited (v0.6.1, April 2026). It has not
 *     had an independent third-party audit.
 *   * It makes NO constant-time claim. Its own README is explicit that
 *     JavaScript engines, JIT, GC and bigint arithmetic cannot provide the
 *     execution guarantees a constant-time claim would need.
 *
 * Both are acceptable here because this is a simulator with no real secrets.
 * The production key paths in this project (arnika, Rosenpass, strongSwan) use
 * native Go/Rust/C implementations, never this module.
 */

import { ml_kem512, ml_kem768, ml_kem1024 } from "@noble/post-quantum/ml-kem.js";
import { ml_dsa44, ml_dsa65, ml_dsa87 } from "@noble/post-quantum/ml-dsa.js";

/** Library provenance, shown in the UI so results are attributable. */
export const PQC_PROVIDER = {
  name: "@noble/post-quantum",
  version: "0.7.0",
  license: "MIT",
  audited: false,
  constantTime: false,
  note: "self-audited (v0.6.1, 2026-04); no constant-time guarantee in pure JS",
} as const;

export interface KemResult {
  algo: string;
  standard: string;
  /** NIST security category (FIPS 203 Table 2). */
  category: number;
  publicKeyLen: number;
  secretKeyLen: number;
  cipherTextLen: number;
  sharedSecretLen: number;
  /** The whole point of the round-trip: both sides must derive the same secret. */
  sharedSecretMatch: boolean;
  elapsedMs: number;
}

export interface SigResult {
  algo: string;
  standard: string;
  category: number;
  publicKeyLen: number;
  secretKeyLen: number;
  signatureLen: number;
  verified: boolean;
  /** A tampered message must NOT verify; a scheme that accepts it is broken. */
  rejectsTamperedMessage: boolean;
  elapsedMs: number;
}

const KEMS = {
  "ML-KEM-512": { impl: ml_kem512, category: 1 },
  "ML-KEM-768": { impl: ml_kem768, category: 3 },
  "ML-KEM-1024": { impl: ml_kem1024, category: 5 },
} as const;

const SIGS = {
  "ML-DSA-44": { impl: ml_dsa44, category: 2 },
  "ML-DSA-65": { impl: ml_dsa65, category: 3 },
  "ML-DSA-87": { impl: ml_dsa87, category: 5 },
} as const;

export type KemName = keyof typeof KEMS;
export type SigName = keyof typeof SIGS;

export const KEM_NAMES = Object.keys(KEMS) as KemName[];
export const SIG_NAMES = Object.keys(SIGS) as SigName[];

/**
 * Full ML-KEM encapsulate/decapsulate round-trip (FIPS 203).
 *
 * Alice generates a keypair, Bob encapsulates to her public key, Alice
 * decapsulates. The shared secrets must be byte-identical.
 */
export function kemRoundtrip(name: KemName): KemResult {
  const { impl, category } = KEMS[name];
  const t0 = performance.now();

  const { publicKey, secretKey } = impl.keygen();
  const { cipherText, sharedSecret } = impl.encapsulate(publicKey);
  const recovered = impl.decapsulate(cipherText, secretKey);

  const elapsedMs = performance.now() - t0;

  return {
    algo: name,
    standard: "FIPS 203",
    category,
    publicKeyLen: publicKey.length,
    secretKeyLen: secretKey.length,
    cipherTextLen: cipherText.length,
    sharedSecretLen: sharedSecret.length,
    sharedSecretMatch: bytesEqual(sharedSecret, recovered),
    elapsedMs,
  };
}

/**
 * ML-DSA sign/verify round-trip (FIPS 204), including a negative control.
 *
 * A test that only checks `verify(sig, msg) === true` would pass against an
 * implementation that returns true unconditionally, so a tampered message is
 * also checked and must be rejected.
 */
export function sigRoundtrip(name: SigName): SigResult {
  const { impl, category } = SIGS[name];
  const message = new TextEncoder().encode(
    "PQC-QKD hybrid testbed — ML-DSA round-trip",
  );

  const t0 = performance.now();
  const { publicKey, secretKey } = impl.keygen();
  const signature = impl.sign(message, secretKey);
  const verified = impl.verify(signature, message, publicKey);
  const elapsedMs = performance.now() - t0;

  const tampered = Uint8Array.from(message);
  tampered[0] ^= 0xff;
  const rejectsTamperedMessage = !impl.verify(signature, tampered, publicKey);

  return {
    algo: name,
    standard: "FIPS 204",
    category,
    publicKeyLen: publicKey.length,
    secretKeyLen: secretKey.length,
    signatureLen: signature.length,
    verified,
    rejectsTamperedMessage,
    elapsedMs,
  };
}

/**
 * The crypto-agility matrix (RFC 7696): exercise every parameter set of every
 * supported algorithm, so swapping one for another is demonstrably a
 * configuration change rather than a code change.
 */
export function agilityMatrix(): { kems: KemResult[]; sigs: SigResult[]; allPass: boolean } {
  const kems = KEM_NAMES.map(kemRoundtrip);
  const sigs = SIG_NAMES.map(sigRoundtrip);
  const allPass =
    kems.every((k) => k.sharedSecretMatch) &&
    sigs.every((s) => s.verified && s.rejectsTamperedMessage);
  return { kems, sigs, allPass };
}

/** Constant-time-ish comparison. Not security-critical here, but no early exit. */
function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * Client-side post-quantum cryptography.
 *
 * Runs FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) and FIPS 205 (SLH-DSA) primitives
 * in the browser via `@noble/post-quantum`, so the public demo's crypto-agility
 * matrix and KEM round-trips need no backend at all.
 *
 * SLH-DSA is here for a specific reason rather than for completeness. ML-KEM
 * and ML-DSA are both module-lattice schemes: a structural break in that family
 * would take out every algorithm on this page at once. SLH-DSA is hash-based,
 * resting only on the security of its hash function, so it is the one option
 * whose failure would be uncorrelated with the others. That is what algorithm
 * agility is for -- RFC 7696 is about being able to move, and having somewhere
 * to move to.
 *
 * Only the `s` (small-signature) parameter sets and one `f` are exposed. The
 * full FIPS 205 set is twelve; the rest differ by hash function and speed/size
 * tradeoff without adding a distinct security argument, and each one costs
 * bundle size and a slow signing path in the browser.
 *
 * Worth knowing before citing this as compliance: NSA CNSA 2.0 states that
 * "while SLH-DSA is hash-based, it is not part of CNSA and is not approved for
 * any use in NSS". BSI TR-02102-1 does recommend it. The algorithms differ in
 * standing between agencies, not only in mathematics. The liboqs-backed `pqc-validator` service remains the
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
import {
  slh_dsa_sha2_128f, slh_dsa_sha2_128s,
  slh_dsa_sha2_192s, slh_dsa_sha2_256s,
} from "@noble/post-quantum/slh-dsa.js";

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
  /**
   * Mathematical family the scheme rests on.
   *
   * Reported because it is the only thing on this page that tells a reader
   * whether two algorithms would fail together. ML-KEM and ML-DSA are both
   * module-lattice; SLH-DSA is hash-based.
   */
  family: string;
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
  // FIPS 204 -- module-lattice (ML-DSA).
  "ML-DSA-44": { impl: ml_dsa44, category: 2, standard: "FIPS 204", family: "module-lattice" },
  "ML-DSA-65": { impl: ml_dsa65, category: 3, standard: "FIPS 204", family: "module-lattice" },
  "ML-DSA-87": { impl: ml_dsa87, category: 5, standard: "FIPS 204", family: "module-lattice" },
  // FIPS 205 -- stateless hash-based (SLH-DSA). Signing is orders of magnitude
  // slower than ML-DSA, especially the `s` sets; that cost is the tradeoff for
  // resting on a different mathematical assumption.
  "SLH-DSA-SHA2-128s": { impl: slh_dsa_sha2_128s, category: 1, standard: "FIPS 205", family: "hash-based" },
  "SLH-DSA-SHA2-128f": { impl: slh_dsa_sha2_128f, category: 1, standard: "FIPS 205", family: "hash-based" },
  "SLH-DSA-SHA2-192s": { impl: slh_dsa_sha2_192s, category: 3, standard: "FIPS 205", family: "hash-based" },
  "SLH-DSA-SHA2-256s": { impl: slh_dsa_sha2_256s, category: 5, standard: "FIPS 205", family: "hash-based" },
} as const;

export type KemName = keyof typeof KEMS;
export type SigName = keyof typeof SIGS;

export const KEM_NAMES = Object.keys(KEMS) as KemName[];
export const SIG_NAMES = Object.keys(SIGS) as SigName[];

/**
 * Mathematical family per scheme, for the UI to label the choice.
 *
 * Exported rather than inferred from the name, so a scheme added to SIGS
 * cannot appear in the picker with no family beside it.
 */
export const SIG_FAMILY: Record<SigName, string> =
  Object.fromEntries(SIG_NAMES.map((n) => [n, SIGS[n].family])) as Record<SigName, string>;

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
  // `standard` comes from the registry, not a literal. It was hardcoded to
  // "FIPS 204", which was true while ML-DSA was the only family here and would
  // have labelled every SLH-DSA result with the wrong standard the moment one
  // was added.
  const { impl, category, standard, family } = SIGS[name];
  const message = new TextEncoder().encode(
    "PQC-QKD hybrid testbed — signature round-trip",
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
    standard,
    family,
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

/**
 * ML-KEM interoperability against an independent implementation.
 *
 * The /pqc page called liboqs an "independent cross-check" while comparing
 * only `ss_len` and `ct_len`. Two implementations agreeing that ML-KEM-768
 * ciphertext is 1088 bytes shows that both read the same table in FIPS 203 --
 * a completely wrong implementation produces 1088-byte ciphertexts too.
 *
 * This makes them actually interoperate. We generate a keypair here with
 * @noble, the server encapsulates to it with liboqs in C, and we decapsulate
 * what comes back. If the shared secrets agree, two independently written
 * implementations agree on the arithmetic, which is the claim being made.
 *
 * The server returns SHA-256 of its shared secret rather than the secret, so
 * the comparison is equally conclusive with nothing sensitive on the wire.
 */
export interface InteropResult {
  algo: string;
  /** The property under test: both sides derived the same shared secret. */
  agrees: boolean;
  ourSha256: string;
  theirSha256: string;
  ciphertextLen: number;
  serverImpl: string;
}

const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function sha256Hex(data: Uint8Array): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", data as BufferSource);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function kemInterop(name: KemName): Promise<InteropResult> {
  const { impl } = KEMS[name];
  const { publicKey, secretKey } = impl.keygen();

  const r = await fetch("/api/pqc/interop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ algo: name, public_key_b64: b64(publicKey) }),
  });
  if (!r.ok) throw new Error(`interop check failed: HTTP ${r.status}`);
  const body = await r.json();

  // Decapsulate THEIR ciphertext with OUR secret key. This is the step that
  // cannot succeed unless both implementations are correct.
  const ourSecret = impl.decapsulate(unb64(body.ciphertext_b64), secretKey);
  const ourSha256 = await sha256Hex(ourSecret);

  return {
    algo: name,
    agrees: ourSha256 === body.shared_secret_sha256,
    ourSha256,
    theirSha256: body.shared_secret_sha256,
    ciphertextLen: body.ciphertext_len,
    serverImpl: body.server_impl,
  };
}

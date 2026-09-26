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
 * any use in NSS". BSI TR-02102-1 (2026-01) recommends SLH-DSA only in its
 * category 3 and 5 parameter sets, and of the lattice schemes only ML-KEM-768
 * / 1024 and ML-DSA-65 / 87 -- so several sets offered here are standardised
 * but not recommended by it -- and recommends the lattice ones only in hybrid
 * combination with a classical scheme, while hash-based signatures may in
 * principle be used alone. POLICY_STANDING records this per algorithm and
 * /pqc shows it. The algorithms differ in standing between agencies, not only
 * in mathematics. The liboqs-backed `pqc-validator` service remains the
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
 * The production key paths in this project use native implementations, never
 * this module: arnika's PQC-HPKE (Go standard library HPKE), Rosenpass for the
 * WireGuard data tunnel wg1 (Rust), and strongSwan (C).
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
  // The installed version, injected at build time (vite.config.ts). A literal
  // here stayed at 0.7.0 after the dependency moved to 0.7.1.
  version: __NOBLE_PQ_VERSION__,
  license: "MIT",
  audited: false,
  constantTime: false,
  note: "self-audited (v0.6.1, 2026-04); no constant-time guarantee in pure JS",
} as const;

export interface KemResult {
  algo: string;
  standard: string;
  /**
   * NIST security category.
   *
   * Was cited as "FIPS 203 Table 2", which states neither the categories nor
   * the key sizes -- it is the parameter-set table (n, q, k, eta1, eta2, du,
   * dv, required RBG strength), and FIPS 203 introduces it as exactly that:
   * "The values of these variables in each parameter set are given in Table 2
   * of Section 8."
   *
   * The categories are the bullet list in Section 3.2, "The ML-KEM Scheme" --
   * ML-KEM-512 category 1, ML-KEM-768 category 3, ML-KEM-1024 category 5 --
   * restated in Section 8 ("Concretely, ML-KEM-512 is claimed to be in
   * security category 1..."). Categories 1-5 are defined in SP 800-57 Part 1,
   * not in FIPS 203. Byte sizes are Table 3.
   */
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

/**
 * Where each offered algorithm stands with three bodies, as recorded on
 * 2026-09-26 (POLICY_STANDING_RECORDED, the date /pqc prints beside each
 * line). A record of published positions, not a compliance claim, and dated
 * because positions change:
 *   NIST -- the standard that specifies it (FIPS 203 / 204 / 205);
 *   BSI  -- TR-02102-1, version 2026-01 (23 January 2026): ML-KEM-768/1024
 *           (Table 2.7), ML-DSA-65/87 (Table 5.7) and SLH-DSA in categories 3
 *           and 5 (Table 5.6), the signatures in their "hedged" variants;
 *   CNSA -- NSA CNSA 2.0: ML-KEM-1024 and ML-DSA-87 only; SLH-DSA "is not
 *           part of CNSA and is not approved for any use in NSS". Re-read on
 *           2026-09-26 in the CNSA 2.0 FAQ, Ver. 2.1 (December 2024), via the
 *           archived copy docs/threat-model.md cites (the NSA host refuses
 *           scripted fetches).
 * Shown on /pqc beside every result, so a green tick on ML-KEM-512 does not
 * read as the same endorsement as one on ML-KEM-1024.
 *
 * `bsiCondition` is the condition BSI attaches to a recommendation, and is
 * printed with it. /pqc runs every algorithm standalone, and a bare
 * "recommended" beside a standalone ML-KEM-768 result misstated the guideline.
 * Checked against the 2026-01 PDF on 2026-09-26:
 *   section 2.4 -- "It is recommended to use quantum-safe KEMs in a hybrid
 *           manner", and section 2.1 limits the recommendation to "the
 *           hybrid use ... of quantum-safe methods in combination with
 *           classical methods";
 *   section 5.3.4 -- "recommends the use of a quantum-safe signature scheme
 *           only in combination with a classic signature scheme", except that
 *           hash-based signatures "can, provided that the implementation
 *           security ... is carefully considered, in principle also be used
 *           alone (i.e. not in hybrid form)".
 * BSI's other condition, the "hedged" signing variant, is not printed because
 * /pqc meets it: `impl.sign(message, secretKey)` passes no `extraEntropy`, and
 * @noble/post-quantum then draws fresh randomness for each signature.
 */
export const POLICY_STANDING_RECORDED = "2026-09-26";

/** BSI's condition for the lattice schemes it recommends (TR-02102-1 2026-01, sections 2.1, 2.4, 5.3.4). */
const BSI_HYBRID_ONLY = "hybrid with a classical scheme only";
/** BSI's allowance for hash-based signatures (TR-02102-1 2026-01, section 5.3.4). */
const BSI_MAY_STAND_ALONE = "may be used alone";

export interface PolicyStanding {
  nist: string;
  bsi: boolean;
  /** Printed after "recommended"; set exactly when `bsi` is true. */
  bsiCondition: string | null;
  cnsa: boolean;
}

export const POLICY_STANDING: Record<string, PolicyStanding> = {
  "ML-KEM-512": { nist: "FIPS 203", bsi: false, bsiCondition: null, cnsa: false },
  "ML-KEM-768": { nist: "FIPS 203", bsi: true, bsiCondition: BSI_HYBRID_ONLY, cnsa: false },
  "ML-KEM-1024": { nist: "FIPS 203", bsi: true, bsiCondition: BSI_HYBRID_ONLY, cnsa: true },
  "ML-DSA-44": { nist: "FIPS 204", bsi: false, bsiCondition: null, cnsa: false },
  "ML-DSA-65": { nist: "FIPS 204", bsi: true, bsiCondition: BSI_HYBRID_ONLY, cnsa: false },
  "ML-DSA-87": { nist: "FIPS 204", bsi: true, bsiCondition: BSI_HYBRID_ONLY, cnsa: true },
  "SLH-DSA-SHA2-128s": { nist: "FIPS 205", bsi: false, bsiCondition: null, cnsa: false },
  "SLH-DSA-SHA2-128f": { nist: "FIPS 205", bsi: false, bsiCondition: null, cnsa: false },
  "SLH-DSA-SHA2-192s": { nist: "FIPS 205", bsi: true, bsiCondition: BSI_MAY_STAND_ALONE, cnsa: false },
  "SLH-DSA-SHA2-256s": { nist: "FIPS 205", bsi: true, bsiCondition: BSI_MAY_STAND_ALONE, cnsa: false },
};

/**
 * One line for the UI, e.g. "FIPS 203 · BSI TR-02102-1: recommended (hybrid
 * with a classical scheme only) · CNSA 2.0: not approved (as recorded ...)".
 */
export function policyStanding(algo: string): string {
  const p = POLICY_STANDING[algo];
  if (!p) return "policy standing not recorded";
  const bsi = p.bsi
    ? `recommended${p.bsiCondition ? ` (${p.bsiCondition})` : ""}`
    : "not recommended";
  return `${p.nist} · BSI TR-02102-1: ${bsi}`
    + ` · CNSA 2.0: ${p.cnsa ? "approved" : "not approved"} (as recorded ${POLICY_STANDING_RECORDED})`;
}

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
 * The crypto-agility matrix (RFC 7696): exercise the listed parameter sets
 * (KEM_NAMES and SIG_NAMES -- all three ML-KEM and ML-DSA sets, four of the
 * twelve SLH-DSA sets) through one interface, so swapping one for another is
 * a list entry rather than new code.
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

/**
 * Real in-browser crypto for the client-side simulation (Round 5).
 *
 * Uses @noble/hashes + @noble/ciphers (MIT, audited) so the public demo keeps
 * the project's "real crypto" fidelity with NO backend:
 *   - HKDF-SHA3-256  (mirrors services/webui-backend/app/e2e_orchestrator.py:
 *                     salt="pqcqkd-e2e", info="mode-<A|B|C>", length 32)
 *   - ChaCha20-Poly1305 (mirrors the Phase-4 data-exchange AEAD, AAD "alice->bob")
 */
import { sha3_256 } from "@noble/hashes/sha3.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";

const enc = new TextEncoder();

/** Random bytes via the Web Crypto CSPRNG. */
export function randomBytes(n: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(n));
}

/** Hex of a byte array. */
export function toHex(b: Uint8Array): string {
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

/**
 * Derive a 32-byte PSK from QKD ‖ PQC key material via HKDF-SHA3-256.
 * Identical parameters to the backend orchestrator so PSKs are reproducible.
 */
export function deriveHkdfSha3(
  qkdKey: Uint8Array, pqcKey: Uint8Array, mode: string,
): Uint8Array {
  const ikm = new Uint8Array(qkdKey.length + pqcKey.length);
  ikm.set(qkdKey, 0);
  ikm.set(pqcKey, qkdKey.length);
  return hkdf(sha3_256, ikm, enc.encode("pqcqkd-e2e"), enc.encode(`mode-${mode}`), 32);
}

/**
 * Encrypt one packet with ChaCha20-Poly1305 under `key`, returning the
 * ciphertext length (ct + tag) and the 12-byte nonce length, mirroring the
 * backend's per-packet byte accounting.
 */
export function chachaEncrypt(
  key: Uint8Array, plaintext: Uint8Array,
): { ctLen: number; nonceLen: number } {
  const nonce = randomBytes(12);
  const ct = chacha20poly1305(key, nonce, enc.encode("alice->bob")).encrypt(plaintext);
  return { ctLen: ct.length, nonceLen: nonce.length };
}

export function encodeUtf8(s: string): Uint8Array {
  return enc.encode(s);
}

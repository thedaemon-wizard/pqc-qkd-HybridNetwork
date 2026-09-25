/**
 * Run the crypto-agility matrix in BOTH implementations and compare them.
 *
 * `/verify` fetched `POST /api/pqc/agility` alone and labelled the panel
 * "Crypto-Agility Matrix (liboqs ...)". `agilityMatrix()` in `./pqc` has
 * existed the whole time with ZERO call sites, and the reason it was never
 * wired in is recorded in the backend: replacing the server call would make
 * the panel's "liboqs" provenance label false.
 *
 * Replacing it would. Running both does not. So this returns a comparison
 * rather than a substitute, and the panel keeps naming liboqs for the half
 * that liboqs produced.
 *
 * WHAT IS STRONG AND WHAT IS WEAK, because the distinction is the whole point
 * and the same mistake was already made once on `/pqc`:
 *
 *   STRONG -- both implementations independently ran a real round-trip over
 *   the same algorithm set and both report pass. @noble encapsulates and
 *   decapsulates in TypeScript and compares the recovered secret to the sent
 *   one; liboqs does the equivalent in C. For a signature, pass means BOTH
 *   halves on BOTH sides: a genuine signature verifies AND a tampered message
 *   is rejected. The browser has always checked both. The server reported only
 *   `ok = verify(...)` -- so a liboqs verify that accepted everything would
 *   have passed -- and now reports `rejects_tampered` as well. A signature row
 *   counts as a server pass only when that field is present and true; a
 *   validator that does not send it cannot be credited with a check it did
 *   not report (`serverTamperNotReported` names those rows).
 *
 *   Names are matched by what they denote, not by spelling: liboqs calls
 *   FIPS 205's SLH-DSA-SHA2-128s "SLH_DSA_PURE_SHA2_128S", and exact matching
 *   meant no SLH-DSA row -- the family the agility argument rests on -- was
 *   ever compared.
 *
 *   WEAK -- byte lengths. Both read the same FIPS 203/204/205 parameter
 *   tables, so agreement on `pk_len` shows they can both read. A completely
 *   wrong implementation produces 1184-byte encapsulation keys too. Reported
 *   because a mismatch would still be informative, and labelled so nobody
 *   cites it as interoperability.
 *
 * The genuinely conclusive check -- liboqs encapsulating to a key @noble
 * generated, and the two shared secrets agreeing -- is `mlkemInterop()` in
 * `./pqc`, which `/pqc` already runs. This file does not duplicate it.
 */
import { agilityMatrix } from "./pqc";

/** One row of `POST /api/pqc/agility`'s `matrix`. */
export interface ServerRow {
  algo: string;
  family: "KEM" | "SIG" | string;
  enabled: boolean;
  ok: boolean;
  pk_len?: number;
  ct_len?: number;
  ss_len?: number;
  sig_len?: number;
  /** SIG rows: the server verified a tampered message and it was rejected. */
  rejects_tampered?: boolean;
  /** The hardness assumption, when the validator reports it. */
  assumption?: string;
}

/**
 * liboqs spells FIPS 205 parameter sets `SLH_DSA_PURE_<HASH>_<N><S|F>`; the
 * standard, and @noble, spell them `SLH-DSA-<HASH>-<N><s|f>`. Map the first
 * onto the second so the two implementations' rows meet. Any other name is
 * already spelled the FIPS way by both sides (ML-KEM-768, ML-DSA-65).
 */
const LIBOQS_SLH_DSA = /^SLH_DSA_PURE_(SHA2|SHAKE)_(\d+)([SF])$/;
export function fipsName(algo: string): string {
  const m = LIBOQS_SLH_DSA.exec(algo);
  return m ? `SLH-DSA-${m[1]}-${m[2]}${m[3].toLowerCase()}` : algo;
}

/**
 * The hardness assumption behind each family, by FIPS name prefix. Shown on
 * /verify because it is the column that says which rows would fail together:
 * a structural break in module lattices takes out every ML-KEM and ML-DSA row
 * at once, and none of the SLH-DSA rows.
 */
const ASSUMPTION_BY_PREFIX: [string, string][] = [
  ["ML-KEM-", "module lattice (MLWE)"],
  ["ML-DSA-", "module lattice (MLWE / MSIS)"],
  ["SLH-DSA-", "hash functions only"],
];
export function assumptionOf(algo: string): string | null {
  const name = fipsName(algo);
  return ASSUMPTION_BY_PREFIX.find(([p]) => name.startsWith(p))?.[1] ?? null;
}

export interface AlgoComparison {
  /** The FIPS spelling; `serverAlgo` is liboqs's, when it differs. */
  algo: string;
  serverAlgo: string;
  family: string;
  /** Both implementations exercised it and both passed. The strong signal. */
  bothPass: boolean;
  serverPass: boolean | null;
  clientPass: boolean | null;
  /** Byte lengths agree. Weak: both read the same standard's table. */
  lengthsAgree: boolean | null;
  /** Non-empty when a length differs, naming the field and both values. */
  lengthNotes: string[];
}

export interface CrossCheckResult {
  compared: AlgoComparison[];
  /** SIG rows whose server half did not report `rejects_tampered`. */
  serverTamperNotReported: string[];
  /** In the server matrix but not exercised in the browser, and vice versa. */
  serverOnly: string[];
  clientOnly: string[];
  /** Every algorithm both ran, passed in both. */
  allBothPass: boolean;
  /** Every compared algorithm agreed on every reported length. */
  allLengthsAgree: boolean;
}

function cmp(
  label: string, a: number | undefined, b: number | undefined, notes: string[],
): boolean | null {
  // `null`, not `true`: an absent field on one side is "not compared", and
  // reporting that as agreement is the absence-as-measurement defect this
  // repository treats as a bug everywhere else.
  if (typeof a !== "number" || typeof b !== "number") return null;
  if (a === b) return true;
  notes.push(`${label}: liboqs ${a} vs @noble ${b}`);
  return false;
}

/**
 * @param serverMatrix `matrix` from `POST /api/pqc/agility`, or null when the
 *   backend was unreachable. With null the browser half still runs and the
 *   result reports every algorithm as client-only -- a static deployment gets
 *   a real answer rather than an empty panel.
 */
export function crossCheckAgility(serverMatrix: ServerRow[] | null): CrossCheckResult {
  const client = agilityMatrix();

  const clientRows = new Map<string, { pass: boolean; pk: number; ct?: number; ss?: number; sig?: number; family: string }>();
  for (const k of client.kems) {
    clientRows.set(k.algo, {
      pass: k.sharedSecretMatch, family: "KEM",
      pk: k.publicKeyLen, ct: k.cipherTextLen, ss: k.sharedSecretLen,
    });
  }
  for (const s of client.sigs) {
    clientRows.set(s.algo, {
      // Both halves, not just `verified`. An implementation that verifies
      // everything passes the first check and fails the second.
      pass: s.verified && s.rejectsTamperedMessage, family: "SIG",
      pk: s.publicKeyLen, sig: s.signatureLen,
    });
  }

  const server = new Map<string, ServerRow>();
  for (const r of serverMatrix ?? []) server.set(fipsName(r.algo), r);

  const compared: AlgoComparison[] = [];
  const serverTamperNotReported: string[] = [];
  for (const [algo, c] of clientRows) {
    const s = server.get(algo);
    if (!s) continue;
    // A signature passes on the server only with its negative control.
    const isSig = c.family === "SIG";
    if (isSig && typeof s.rejects_tampered !== "boolean") serverTamperNotReported.push(algo);
    const serverPass = s.ok && (!isSig || s.rejects_tampered === true);
    const lengthNotes: string[] = [];
    const checks = [
      cmp("pk_len", s.pk_len, c.pk, lengthNotes),
      cmp("ct_len", s.ct_len, c.ct, lengthNotes),
      cmp("ss_len", s.ss_len, c.ss, lengthNotes),
      cmp("sig_len", s.sig_len, c.sig, lengthNotes),
    ].filter((x): x is boolean => x !== null);
    compared.push({
      algo, serverAlgo: s.algo, family: c.family,
      serverPass, clientPass: c.pass,
      bothPass: serverPass && c.pass,
      lengthsAgree: checks.length ? checks.every(Boolean) : null,
      lengthNotes,
    });
  }

  const comparedNames = new Set(compared.map((c) => c.algo));
  return {
    compared,
    serverTamperNotReported,
    serverOnly: [...server.values()].filter((r) => !comparedNames.has(fipsName(r.algo))).map((r) => r.algo),
    clientOnly: [...clientRows.keys()].filter((a) => !comparedNames.has(a)),
    // `.every` on an empty array is true, which would make an unreachable
    // backend render as agreement. Require something to have been compared.
    allBothPass: compared.length > 0 && compared.every((c) => c.bothPass),
    allLengthsAgree:
      compared.length > 0 && compared.every((c) => c.lengthsAgree !== false),
  };
}

/**
 * The ETSI GS QKD 014 message shapes of THIS repository's KME
 * (services/bb84-kme/app/etsi014.py), for /protocol-lab's timeline.
 *
 * Shapes only: the timeline draws what a per-hop 014 exchange looks like on
 * this stack; nothing is sent. tests/test_protocol_lab_etsi_spec.py checks every
 * path, status code and the bits claim below against etsi014.py, so this cannot
 * drift into describing a different API.
 */
export const ETSI014_THIS_REPO = {
  prefix: "/api/v1/keys",
  status: "/{sae_id}/status",
  encKeys: "/{sae_id}/enc_keys",
  decKeys: "/{sae_id}/dec_keys",
  /** `size` is in bits here; ETSI GS QKD 004's Key_chunk_size is in bytes. */
  sizeUnit: "bits",
  http: {
    wrongSize: 400,
    poolEmpty: 503,
    unknownKeyId: 404,
  },
} as const;

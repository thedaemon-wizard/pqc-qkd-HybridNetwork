/**
 * Hardware-In-The-Loop bridge — documents how to wire a real ETSI 014 KMS
 * (ID Quantique Cerberis, Toshiba MUSE, …) into the same arnika pipeline by
 * pointing `KMS_URL` at the device's KME endpoint.
 *
 * No live UI control here because real-hardware connection requires per-site
 * mTLS material and physical access; this page acts as the operator's checklist.
 */
export default function HIL() {
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Hardware-In-The-Loop (HIL) Bridge</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        Because this PoC speaks the <b>ETSI GS QKD 014 standard REST API</b>, you
        can drop in a <b>real QKD device</b> by bypassing the Python KME and
        pointing <code>arnika</code> directly at the device's KMS endpoint.
      </p>

      <ol style={{ color: "#cbd6f5", lineHeight: 1.7, maxWidth: 760 }}>
        <li>Expose the device (ID Quantique Cerberis / Toshiba MUSE / etc.) on a
            management network reachable from the <code>alice</code> node.</li>
        <li>Set <code>KMS_URL=https://&lt;device&gt;/api/v1/keys/&lt;SAE_ID&gt;</code>
            in <code>.env</code>.</li>
        <li>Drop the device-issued mTLS certificates into <code>./pki/</code>
            and toggle <code>ETSI_MTLS_ENABLED=true</code>.</li>
        <li>Run <code>docker compose restart alice bob</code> so
            <code>arnika</code> picks up the new endpoint.</li>
        <li>Confirm success with <code>docker logs alice | grep "PSK configured"</code> —
            you should see hardware-sourced PSK rotations.</li>
      </ol>

      <h3 style={{ marginTop: 24 }}>Reported interoperable devices</h3>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7 }}>
        <li>ID Quantique XG / Cerberis series (native ETSI 014)</li>
        <li>Toshiba MUSE Q-KMS — requires the ETSI 014 compatibility mode</li>
        <li>Thinkquantum TQ-KME — exposes ETSI 014 + 020 dual stack</li>
      </ul>

      <h3 style={{ marginTop: 24 }}>Out of scope / caveats</h3>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7 }}>
        <li>Vendor-specific drivers (USB / serial) are not implemented in this PoC.</li>
        <li>Xanadu's cloud CV-QKD backend was <b>decommissioned in 2026-01</b>;
            local CV-QKD simulation remains available.</li>
        <li>Proprietary key-management APIs (HSM-backed, etc.) need bespoke adapters.</li>
      </ul>
    </div>
  );
}

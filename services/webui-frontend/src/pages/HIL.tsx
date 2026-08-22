/**
 * Hardware-In-The-Loop bridge — documents how to wire a real ETSI 014 KMS
 * into the same arnika pipeline by pointing `KMS_URL` at its KME endpoint.
 *
 * No live UI control here because real-hardware connection requires per-site
 * mTLS material and physical access; this page acts as the operator's checklist.
 *
 * Every vendor name below was checked against the vendor's own product page on
 * 2026-08-22. The list previously read "Reported interoperable devices" and
 * named "Toshiba MUSE Q-KMS" and "Thinkquantum TQ-KME" -- neither product
 * exists under those names -- and credited ThinkQuantum with ETSI 020, which is
 * ID Quantique's profile, not theirs. Nothing here has been tested against this
 * PoC, so the heading no longer claims it was.
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
        <li>Expose the key-management endpoint on a management network reachable
            from the <code>alice</code> node. On most platforms this is a
            separate KMS rather than the QKD appliance itself — see the table
            below.</li>
        <li>Set <code>KMS_URL=https://&lt;device&gt;/api/v1/keys/&lt;SAE_ID&gt;</code>
            in <code>.env</code>.</li>
        <li>Drop the device-issued mTLS certificates into <code>./pki/</code>.
            <b>mTLS is not implemented.</b> This step used to say to set
            <code>ETSI_MTLS_ENABLED=true</code>; no code has ever read that
            variable, so setting it changed nothing. Attaching real hardware
            needs the TLS client-certificate path built first.</li>
        <li>Run <code>docker compose restart alice bob</code> so
            <code>arnika</code> picks up the new endpoint.</li>
        <li>Confirm success with <code>docker logs alice | grep "PSK configured"</code> —
            you should see hardware-sourced PSK rotations.</li>
      </ol>

      <h3 style={{ marginTop: 24 }}>Platforms documenting an ETSI GS QKD 014 interface</h3>
      <p style={{ color: "#9aa9d8", maxWidth: 760, marginTop: 0 }}>
        Taken from each vendor's own product documentation, checked 2026-08-22.
        <b> None of these has been tested against this PoC</b> — they are listed
        because they publish an ETSI 014 REST interface, which is the only thing
        the <code>KMS_URL</code> swap above requires.
      </p>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7, maxWidth: 760 }}>
        <li><b>ID Quantique</b> XG series (Cerberis XG / XGR, Clavis XG / XGR).
            The ETSI interface is exposed by the <b>Clarion KX</b> key-management
            layer, not by the QKD appliance, so <code>KMS_URL</code> points at
            Clarion KX. IDQ lists ETSI 014 and 020 there. Note that the Cerberis
            XG and XGR product pages currently carry a "no longer available for
            purchase" banner.</li>
        <li><b>Toshiba</b> Quantum Key Management System (Q-KMS) — "REST-based
            key delivery API, compliant with ETSI GS QKD 014". It is the default
            interface; there is no compatibility mode to enable.</li>
        <li><b>ThinkQuantum</b> QUKY (QUKY-TX / QUKY-RX) — the integrated key
            management system documents <b>ETSI 014 and ETSI 004</b>.</li>
      </ul>

      <h3 style={{ marginTop: 24 }}>Out of scope / caveats</h3>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7 }}>
        <li>Vendor-specific drivers (USB / serial) are not implemented in this PoC.</li>
        <li>Xanadu's photonic quantum cloud was <b>decommissioned on
            2026-01-16</b> and the Strawberry Fields SDK archived the same day —
            that is the commit this repository pins the submodule to. It was a
            continuous-variable <i>quantum computing</i> service (X8, Borealis);
            this line previously called it a "CV-QKD backend", but Xanadu never
            offered QKD, and the string "QKD" does not occur anywhere in the
            Strawberry Fields tree. Local CV-QKD simulation (GG02) is unaffected
            and remains available.</li>
        <li>Proprietary key-management APIs (HSM-backed, etc.) need bespoke adapters.</li>
      </ul>
    </div>
  );
}

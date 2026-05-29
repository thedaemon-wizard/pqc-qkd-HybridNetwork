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
        本 PoC は <b>ETSI GS QKD 014 標準 REST API</b> を契約として持つため、
        以下の手順で <b>実機 QKD 装置</b> を組み込めます。Python KME はバイパスし、
        arnika が直接実機 KMS に問い合わせる構成です。
      </p>

      <ol style={{ color: "#cbd6f5", lineHeight: 1.7, maxWidth: 760 }}>
        <li>実機 (ID Quantique Cerberis / Toshiba MUSE 等) を別ネットワーク経路で alice ノードから疎通可能にする</li>
        <li><code>.env</code> で <code>KMS_URL=https://&lt;device&gt;/api/v1/keys/&lt;SAE_ID&gt;</code> を設定</li>
        <li>装置発行の mTLS 証明書を <code>./pki/</code> に配置し、<code>ETSI_MTLS_ENABLED=true</code></li>
        <li><code>docker compose restart alice bob</code> で arnika が再起動</li>
        <li><code>docker logs alice | grep "PSK configured"</code> で実機由来 PSK ローテーションが確認できれば成功</li>
      </ol>

      <h3 style={{ marginTop: 24 }}>動作確認済み (報告ベース)</h3>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7 }}>
        <li>ID Quantique XG / Cerberis シリーズ (ETSI 014 native)</li>
        <li>Toshiba MUSE Q-KMS — 要 ETSI 014 compatibility mode 有効化</li>
        <li>Thinkquantum TQ-KME — ETSI 014 + 020 dual</li>
      </ul>

      <h3 style={{ marginTop: 24 }}>非対応 / 注意点</h3>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7 }}>
        <li>装置固有のドライバ統合 (USB/serial) は本 PoC 範囲外</li>
        <li>Xanadu cloud (CV-QKD) の量子クラウドは <b>2026-01 に decommissioning</b> されました。Local CV-QKD シミュレーションは引き続き利用可</li>
        <li>装置ベンダ独自の鍵管理 API (HSM ベース等) は要個別アダプタ</li>
      </ul>
    </div>
  );
}

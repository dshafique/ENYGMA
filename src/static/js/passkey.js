/* WebAuthn plumbing. Nothing here ever logs a challenge or a credential. */
const b64urlToBuf = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0)).buffer;
};
const bufToB64url = (b) =>
  btoa(String.fromCharCode(...new Uint8Array(b)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error("request failed"), { status: res.status, data });
  return data;
}

export async function enrol(deviceName, say) {
  const opts = await post("/auth/register/options");
  const token = opts.challengeToken;
  opts.challenge = b64urlToBuf(opts.challenge);
  opts.user.id = b64urlToBuf(opts.user.id);
  (opts.excludeCredentials || []).forEach((c) => (c.id = b64urlToBuf(c.id)));
  say("Reading");
  const cred = await navigator.credentials.create({ publicKey: opts });
  await post("/auth/register/verify", {
    challengeToken: token,
    deviceName,
    credential: {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        attestationObject: bufToB64url(cred.response.attestationObject),
      },
      clientExtensionResults: cred.getClientExtensionResults(),
    },
  });
}

export async function unlock(say) {
  const opts = await post("/auth/login/options");
  const token = opts.challengeToken;
  opts.challenge = b64urlToBuf(opts.challenge);
  (opts.allowCredentials || []).forEach((c) => (c.id = b64urlToBuf(c.id)));
  say("Reading");
  const cred = await navigator.credentials.get({ publicKey: opts });
  await post("/auth/login/verify", {
    challengeToken: token,
    credential: {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        authenticatorData: bufToB64url(cred.response.authenticatorData),
        signature: bufToB64url(cred.response.signature),
        userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : null,
      },
      clientExtensionResults: cred.getClientExtensionResults(),
    },
  });
}

/* Whether a passkey can happen here at all.
 *
 * Inside the native shell it cannot. WebAuthn needs the browser or a native
 * Credential Manager bridge, and a plain Android WebView is neither, so
 * navigator.credentials.get() there fails in a way that looks to him exactly
 * like a button that does nothing. Two separate screens offered that button as
 * the primary action and both were dead in the app.
 *
 * Asked as a capability rather than "am I in Capacitor", because the answer is
 * the same for any browser without a platform authenticator and the question is
 * the honest one. Cached: the answer cannot change while the page is open.
 */
let _can = null;
export function passkeysWork() {
  if (_can) return _can;
  _can = (async () => {
    try {
      if (!window.PublicKeyCredential) return false;
      const ask = PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable;
      if (typeof ask !== "function") return false;
      return await ask.call(PublicKeyCredential);
    } catch (e) {
      return false;
    }
  })();
  return _can;
}

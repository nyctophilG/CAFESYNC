// passkey.js — WebAuthn browser-side glue.
//
// WebAuthn's JS API uses ArrayBuffers (binary blobs) for things like the
// challenge, credential ID, and signature. JSON only handles strings. So
// we encode/decode at every boundary using base64url (URL-safe base64
// without padding), which is what the spec recommends.
//
// This file exposes two public functions:
//   - registerPasskey(name)   — call from "Add passkey" button, logged in
//   - loginWithPasskey()      — call from "Sign in with passkey" button

// === Base64url helpers ===========================================

// Convert a base64url string (no padding) to ArrayBuffer.
function b64urlToBuffer(b64url) {
    const padding = "=".repeat((4 - (b64url.length % 4)) % 4);
    const b64 = (b64url + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(b64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes.buffer;
}

// Convert an ArrayBuffer (or Uint8Array) to a base64url string.
function bufferToB64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let s = "";
    for (let i = 0; i < bytes.byteLength; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// === Registration ===============================================

async function registerPasskey(name) {
    if (!window.PublicKeyCredential) {
        throw new Error("Your browser doesn't support passkeys.");
    }

    // Step 1: ask the server for registration options.
    const beginRes = await fetch("/passkey/register/begin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
    });
    if (!beginRes.ok) {
        if (beginRes.status === 401) {
            window.location.href = "/login";
            return;
        }
        throw new Error(`Failed to start registration: ${beginRes.status}`);
    }
    const options = await beginRes.json();

    // Step 2: convert the base64url-encoded fields into ArrayBuffers,
    // because that's what navigator.credentials.create() expects.
    const publicKey = {
        ...options,
        challenge: b64urlToBuffer(options.challenge),
        user: {
            ...options.user,
            id: b64urlToBuffer(options.user.id),
        },
        excludeCredentials: (options.excludeCredentials || []).map(c => ({
            ...c,
            id: b64urlToBuffer(c.id),
        })),
    };

    // Step 3: ask the browser/OS to create a credential. This triggers the
    // Touch ID / Face ID / Windows Hello / security key prompt.
    let credential;
    try {
        credential = await navigator.credentials.create({ publicKey });
    } catch (err) {
        // Common cases: user cancelled, no biometric available, etc.
        // We surface the error message to the UI.
        throw new Error(`Passkey registration cancelled: ${err.message || err.name}`);
    }
    if (!credential) {
        throw new Error("No credential returned by the browser.");
    }

    // Step 4: serialize the credential back to JSON-friendly base64url.
    const att = credential.response;
    const body = {
        id: credential.id,
        rawId: bufferToB64url(credential.rawId),
        type: credential.type,
        response: {
            clientDataJSON: bufferToB64url(att.clientDataJSON),
            attestationObject: bufferToB64url(att.attestationObject),
        },
        // The webauthn library accepts these but not all browsers send them.
        ...(credential.authenticatorAttachment
            ? { authenticatorAttachment: credential.authenticatorAttachment }
            : {}),
        clientExtensionResults: credential.getClientExtensionResults
            ? credential.getClientExtensionResults()
            : {},
        // Our own field for the device label.
        name: name || "Passkey",
    };

    // Step 5: send to server for verification + storage.
    const completeRes = await fetch("/passkey/register/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
    });
    if (!completeRes.ok) {
        const err = await completeRes.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(`Server rejected the passkey: ${err.detail}`);
    }
    return await completeRes.json();
}

// === Login =======================================================

async function loginWithPasskey() {
    if (!window.PublicKeyCredential) {
        throw new Error("Your browser doesn't support passkeys.");
    }

    // Step 1: get auth options.
    const beginRes = await fetch("/passkey/login/begin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
    });
    if (!beginRes.ok) {
        throw new Error(`Failed to start login: ${beginRes.status}`);
    }
    const options = await beginRes.json();

    const publicKey = {
        ...options,
        challenge: b64urlToBuffer(options.challenge),
        // allowCredentials is empty for discoverable-credential flow,
        // but if the server included any, decode them too.
        allowCredentials: (options.allowCredentials || []).map(c => ({
            ...c,
            id: b64urlToBuffer(c.id),
        })),
    };

    // Step 2: ask the OS to find a passkey. With discoverable credentials
    // the OS shows a picker of accounts that have passkeys for this site.
    let assertion;
    try {
        assertion = await navigator.credentials.get({ publicKey });
    } catch (err) {
        throw new Error(`Passkey sign-in cancelled: ${err.message || err.name}`);
    }
    if (!assertion) {
        throw new Error("No assertion returned by the browser.");
    }

    // Step 3: serialize and send.
    const r = assertion.response;
    const body = {
        id: assertion.id,
        rawId: bufferToB64url(assertion.rawId),
        type: assertion.type,
        response: {
            clientDataJSON: bufferToB64url(r.clientDataJSON),
            authenticatorData: bufferToB64url(r.authenticatorData),
            signature: bufferToB64url(r.signature),
            userHandle: r.userHandle ? bufferToB64url(r.userHandle) : null,
        },
        clientExtensionResults: assertion.getClientExtensionResults
            ? assertion.getClientExtensionResults()
            : {},
    };

    const completeRes = await fetch("/passkey/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
    });
    if (!completeRes.ok) {
        const err = await completeRes.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(`Sign-in failed: ${err.detail}`);
    }
    const data = await completeRes.json();
    if (data.redirect) {
        window.location.href = data.redirect;
    }
    return data;
}

// Expose for templates.
window.cafesyncPasskey = {
    register: registerPasskey,
    login: loginWithPasskey,
    isSupported: () => !!window.PublicKeyCredential,
};

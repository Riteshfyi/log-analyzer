import { NextRequest, NextResponse } from "next/server";

const WEBEX_TOKEN_URL =
  process.env.WEBEX_TOKEN_URL || "https://integration.webexapis.com/v1/access_token";
const CLIENT_ID = process.env.WEBEX_CLIENT_ID || "";
const CLIENT_SECRET = process.env.WEBEX_CLIENT_SECRET || "";
const REDIRECT_URI =
  process.env.WEBEX_REDIRECT_URI || "http://localhost:3000/api/auth/callback";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");

  console.log("[Auth Callback] Received — code:", code ? "yes" : "no", "state:", state ? "yes" : "no", "error:", error || "none");

  const baseUrl = new URL("/", request.url).toString().replace(/\/$/, "");

  if (error) {
    return NextResponse.redirect(
      `${baseUrl}/#error=${encodeURIComponent(error)}`
    );
  }

  if (!code) {
    return NextResponse.redirect(
      `${baseUrl}/#error=${encodeURIComponent("No authorization code received")}`
    );
  }

  const savedState = request.cookies.get("webex_oauth_state")?.value;
  if (!state || state !== savedState) {
    return NextResponse.redirect(
      `${baseUrl}/#error=${encodeURIComponent("Invalid OAuth state — possible CSRF attack")}`
    );
  }

  try {
    const tokenResponse = await fetch(WEBEX_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: CLIENT_ID,
        client_secret: CLIENT_SECRET,
        code,
        redirect_uri: REDIRECT_URI,
      }),
    });

    if (!tokenResponse.ok) {
      const errBody = await tokenResponse.text();
      console.error("Webex token exchange failed:", errBody);
      return NextResponse.redirect(
        `${baseUrl}/#error=${encodeURIComponent("Token exchange failed")}`
      );
    }

    const tokenData = await tokenResponse.json();
    const accessToken = tokenData.access_token;

    console.log("[Auth Callback] Token exchange response — has access_token:", !!accessToken, "token_type:", tokenData.token_type, "expires_in:", tokenData.expires_in);

    if (!accessToken) {
      return NextResponse.redirect(
        `${baseUrl}/#error=${encodeURIComponent("No access token in response")}`
      );
    }

    const response = NextResponse.redirect(
      `${baseUrl}/#access_token=${encodeURIComponent(accessToken)}`
    );

    response.cookies.delete("webex_oauth_state");

    return response;
  } catch (err) {
    console.error("OAuth callback error:", err);
    return NextResponse.redirect(
      `${baseUrl}/#error=${encodeURIComponent("Authentication failed")}`
    );
  }
}

import { NextResponse } from "next/server";
import crypto from "crypto";

const WEBEX_AUTH_URL =
  process.env.WEBEX_AUTH_URL || "https://integration.webexapis.com/v1/authorize";
const CLIENT_ID = process.env.WEBEX_CLIENT_ID || "";
const REDIRECT_URI =
  process.env.WEBEX_REDIRECT_URI || "http://localhost:3000/api/auth/callback";
const SCOPES = process.env.WEBEX_SCOPES || "spark:all spark:applications_token spark:kms";

export async function GET() {
  if (!CLIENT_ID) {
    return NextResponse.json(
      { error: "WEBEX_CLIENT_ID is not configured" },
      { status: 500 }
    );
  }

  const state = crypto.randomBytes(32).toString("hex");

  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    redirect_uri: REDIRECT_URI,
    scope: SCOPES,
    state,
  });

  const response = NextResponse.redirect(`${WEBEX_AUTH_URL}?${params}`);

  response.cookies.set("webex_oauth_state", state, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 600,
  });

  return response;
}

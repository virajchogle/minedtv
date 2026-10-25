/**
 * Sign up, sign in, sign out and "who am I", for the browser.
 *
 * Login and signup forward to the API and keep the returned token in an
 * httpOnly cookie; the response body carries only the account. Every other
 * request picks the cookie up in the /api/minedtv proxy.
 */

import { NextRequest } from "next/server";

import {
  SESSION_COOKIE,
  UPSTREAM,
  missingKeyResponse,
  unreachableResponse,
} from "@/lib/server/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ action: string }> };

const COOKIE_BASE = "Path=/; HttpOnly; SameSite=Lax";
const secure = () => (process.env.NODE_ENV === "production" ? "; Secure" : "");

function clearCookie(response: Response): Response {
  response.headers.append("Set-Cookie", `${SESSION_COOKIE}=; ${COOKIE_BASE}; Max-Age=0${secure()}`);
  return response;
}

async function upstream(path: string, init: RequestInit): Promise<Response> {
  const apiKey = process.env.MINEDTV_API_KEY;
  if (!apiKey) return missingKeyResponse();
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", apiKey);
  try {
    return await fetch(`${UPSTREAM}${path}`, { ...init, headers, cache: "no-store" });
  } catch (error) {
    return unreachableResponse(error);
  }
}

export async function POST(request: NextRequest, context: Context) {
  const { action } = await context.params;

  if (action === "logout") {
    return clearCookie(new Response(null, { status: 204 }));
  }
  if (action !== "login" && action !== "signup") {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  const res = await upstream(`/auth/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
  const body = await res.json().catch(() => ({ detail: `${res.status} ${res.statusText}` }));
  if (!res.ok) return Response.json(body, { status: res.status });

  const { token, expires_at, user } = body as { token: string; expires_at: string; user: unknown };
  const maxAge = Math.max(0, Math.floor((Date.parse(expires_at) - Date.now()) / 1000));
  const response = Response.json(user, { status: res.status });
  response.headers.append(
    "Set-Cookie",
    `${SESSION_COOKIE}=${encodeURIComponent(token)}; ${COOKIE_BASE}; Max-Age=${maxAge}${secure()}`
  );
  return response;
}

export async function GET(request: NextRequest, context: Context) {
  const { action } = await context.params;
  if (action !== "me") return Response.json({ detail: "Not found" }, { status: 404 });

  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return Response.json({ detail: "Not signed in" }, { status: 401 });

  const res = await upstream("/auth/me", { headers: { Authorization: `Bearer ${token}` } });
  const body = await res.json().catch(() => ({ detail: `${res.status} ${res.statusText}` }));
  const response = Response.json(body, { status: res.status });
  // A stale or forged cookie is dropped so the browser stops sending it.
  return res.status === 401 ? clearCookie(response) : response;
}

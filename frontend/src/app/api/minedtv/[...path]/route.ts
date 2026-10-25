/**
 * Server-side proxy to the deployed MinedTV API.
 *
 * The service requires an `X-API-Key` on every route. That key is a shared
 * secret, so it must never be sent to the browser: it lives in
 * `MINEDTV_API_KEY` (no `NEXT_PUBLIC_` prefix, so Next will not inline it into
 * client bundles) and is attached here, in the Node runtime.
 *
 * Everything the client does goes through `/api/minedtv/...`, which maps
 * one-to-one onto the upstream path.
 */

import { NextRequest } from "next/server";

import {
  SESSION_COOKIE,
  UPSTREAM,
  missingKeyResponse,
  unreachableResponse,
} from "@/lib/server/upstream";

export const runtime = "nodejs";
// The upstream is a live service; nothing here may be cached at build time.
export const dynamic = "force-dynamic";

/** Request headers worth forwarding. Hop-by-hop and auth headers are dropped. */
const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "x-user-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "cache-control", "etag"];

async function proxy(request: NextRequest, path: string[]) {
  const apiKey = process.env.MINEDTV_API_KEY;
  if (!apiKey) return missingKeyResponse();

  const target = new URL(`${UPSTREAM}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers({ "X-API-Key": apiKey });
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // The login token sits in an httpOnly cookie; the API wants it as a bearer token.
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (session) headers.set("Authorization", `Bearer ${session}`);

  const method = request.method;
  const hasBody = method !== "GET" && method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch (error) {
    return unreachableResponse(error);
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}

export async function PATCH(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}

export async function DELETE(request: NextRequest, context: Context) {
  return proxy(request, (await context.params).path);
}

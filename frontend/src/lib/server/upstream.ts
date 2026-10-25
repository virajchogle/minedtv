/**
 * Server-only helpers shared by the API proxy and the auth routes.
 *
 * The login token lives in an httpOnly cookie, so browser code never sees it;
 * the proxy turns it into `Authorization: Bearer` on the way upstream.
 */

export const UPSTREAM =
  process.env.MINEDTV_API_BASE_URL ??
  "https://minedtv-api-818252181045.us-east1.run.app";

export const SESSION_COOKIE = "minedtv_session";

export function missingKeyResponse(): Response {
  return Response.json(
    {
      detail:
        "MINEDTV_API_KEY is not set on the server, so the deployed MinedIt API cannot be reached. Add it to frontend/.env.local and restart the dev server.",
    },
    { status: 503 }
  );
}

export function unreachableResponse(error: unknown): Response {
  return Response.json(
    {
      detail: `Could not reach the MinedIt API at ${UPSTREAM}: ${
        error instanceof Error ? error.message : "network error"
      }`,
    },
    { status: 502 }
  );
}

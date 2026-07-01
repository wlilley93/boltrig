/**
 * Shared helpers for `app/api/**` route handlers.
 *
 * Gives every endpoint a consistent JSON envelope and error handling:
 * - success → `{ data: ... }`
 * - failure → `{ error: { code, message, issues? } }`
 *
 * Route handlers stay free to hold business logic and secrets (the file is
 * server-only by construction) — these helpers only standardise the I/O shape.
 */

import { NextRequest, NextResponse } from "next/server";
import { ZodError } from "zod";

/** Throw inside a route handler to return a specific error response. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RouteContext = { params: Promise<Record<string, string>> };

/**
 * Wraps an `app/api` route handler. The handler returns its payload (wrapped
 * as `{ data }`, 200) or a `NextResponse` (passed through). Thrown errors are
 * mapped to the error envelope:
 * - `ZodError` / malformed JSON → 400
 * - `ApiError` → its own status/code
 * - anything else → 500 (logged server-side, no internals leaked)
 */
export function handle<C extends RouteContext = RouteContext>(
  handler: (req: NextRequest, ctx: C) => Promise<unknown>,
) {
  return async (req: NextRequest, ctx: C): Promise<NextResponse> => {
    try {
      const result = await handler(req, ctx);
      if (result instanceof NextResponse) return result;
      return NextResponse.json({ data: result }, { status: 200 });
    } catch (error) {
      if (error instanceof ZodError) {
        return NextResponse.json(
          {
            error: {
              code: "invalid_input",
              message: "Invalid request payload.",
              issues: error.issues.map((issue) => ({
                path: issue.path.map(String).join("."),
                message: issue.message,
              })),
            },
          },
          { status: 400 },
        );
      }
      if (error instanceof SyntaxError) {
        return NextResponse.json(
          { error: { code: "invalid_json", message: "Request body is not valid JSON." } },
          { status: 400 },
        );
      }
      if (error instanceof ApiError) {
        return NextResponse.json(
          { error: { code: error.code, message: error.message } },
          { status: error.status },
        );
      }
      console.error("[api] unhandled error:", error);
      return NextResponse.json(
        { error: { code: "internal_error", message: "Something went wrong." } },
        { status: 500 },
      );
    }
  };
}

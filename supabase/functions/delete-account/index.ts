import { createClient } from "npm:@supabase/supabase-js@2";
import { hasFreshOtp } from "./auth.ts";

const BUCKET = "private-cvs";
const LIST_PAGE_SIZE = 1000;
const REMOVE_BATCH_SIZE = 100;
type StorageFolderApi = {
  list: (
    folder: string,
    options: {
      limit: number;
      offset: number;
      sortBy: { column: string; order: "asc" | "desc" };
    },
  ) => Promise<
    {
      data: Array<{ name: string; id: string | null }> | null;
      error: unknown | null;
    }
  >;
};

function jsonResponse(status: number, body: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json",
    },
  });
}

async function collectFiles(
  storage: StorageFolderApi,
  folder: string,
  depth = 0,
): Promise<string[]> {
  if (depth > 8) throw new Error("Unexpectedly deep storage hierarchy");
  const files: string[] = [];
  let offset = 0;

  while (true) {
    const { data, error } = await storage.list(folder, {
      limit: LIST_PAGE_SIZE,
      offset,
      sortBy: { column: "name", order: "asc" },
    });
    if (error) throw new Error("Could not enumerate account files");
    const entries = data ?? [];
    for (const entry of entries) {
      const path = `${folder}/${entry.name}`;
      if (entry.id === null) {
        files.push(...await collectFiles(storage, path, depth + 1));
      } else {
        files.push(path);
      }
    }
    if (entries.length < LIST_PAGE_SIZE) break;
    offset += entries.length;
  }

  return files;
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  const authorization = request.headers.get("Authorization") ?? "";
  const match = authorization.match(/^Bearer\s+(.+)$/i);
  if (!match) return jsonResponse(401, { error: "Authentication required" });

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const publishableKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !publishableKey || !serviceRoleKey) {
    return jsonResponse(503, { error: "Deletion service is not configured" });
  }

  const caller = createClient(supabaseUrl, publishableKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { data: userData, error: userError } = await caller.auth.getUser(
    match[1],
  );
  const user = userData.user;
  if (userError || !user || !user.email_confirmed_at || !user.email) {
    return jsonResponse(401, {
      error: "A verified account session is required",
    });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonResponse(400, { error: "DELETE confirmation required" });
  }
  const confirmation =
    typeof body === "object" && body !== null && "confirmation" in body
      ? (body as { confirmation?: unknown }).confirmation
      : null;
  if (confirmation !== "DELETE") {
    return jsonResponse(400, { error: "DELETE confirmation required" });
  }

  // Identity comes from auth.getUser above. Claims are read from that same
  // verified JWT only to require a recent OTP authentication, so an old or
  // magic-link-only bearer token cannot irreversibly delete the account.
  if (!hasFreshOtp(match[1], user.id, Math.floor(Date.now() / 1000))) {
    return jsonResponse(403, {
      error: "Fresh email-code authentication required",
    });
  }

  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  try {
    // All user objects live beneath the UUID prefix. Enumerate and remove them
    // before deleting auth.users, which cascades the user's private table rows.
    const files = await collectFiles(admin.storage.from(BUCKET), user.id);
    for (let index = 0; index < files.length; index += REMOVE_BATCH_SIZE) {
      const { error } = await admin.storage.from(BUCKET).remove(
        files.slice(index, index + REMOVE_BATCH_SIZE),
      );
      if (error) throw new Error("Could not remove all account files");
    }

    const { error: deleteError } = await admin.auth.admin.deleteUser(
      user.id,
      false,
    );
    if (deleteError) throw new Error("Could not remove account");
    return jsonResponse(200, { status: "deleted" });
  } catch {
    // Avoid returning user identifiers, object paths, or provider internals.
    return jsonResponse(500, {
      error: "Deletion did not complete; contact the site owner",
    });
  }
});

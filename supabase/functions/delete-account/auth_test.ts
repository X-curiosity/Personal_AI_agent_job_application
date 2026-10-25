import { assertEquals } from "jsr:@std/assert";
import { hasFreshOtp } from "./auth.ts";

function token(claims: unknown): string {
  const json = JSON.stringify(claims);
  const encoded = btoa(json).replace(/=/g, "").replace(/\+/g, "-").replace(
    /\//g,
    "_",
  );
  return `header.${encoded}.signature`;
}

Deno.test("fresh OTP and matching subject are required", () => {
  const now = 1_000_000;
  const valid = {
    sub: "user-1",
    auth_time: now - 30,
    amr: [{ method: "otp", timestamp: now - 30 }],
  };
  assertEquals(hasFreshOtp(token(valid), "user-1", now), true);
  assertEquals(hasFreshOtp(token(valid), "other", now), false);
  assertEquals(
    hasFreshOtp(token({ ...valid, auth_time: now - 601 }), "user-1", now),
    false,
  );
  assertEquals(
    hasFreshOtp(
      token({ ...valid, amr: [{ method: "magiclink", timestamp: now }] }),
      "user-1",
      now,
    ),
    false,
  );
  assertEquals(
    hasFreshOtp(
      token({ ...valid, amr: [{ method: "otp", timestamp: now - 601 }] }),
      "user-1",
      now,
    ),
    false,
  );
  assertEquals(hasFreshOtp("invalid", "user-1", now), false);
});

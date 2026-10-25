export function hasFreshOtp(
  token: string,
  userId: string,
  nowSeconds: number,
): boolean {
  try {
    const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(
      atob(encoded + "=".repeat((4 - encoded.length % 4) % 4)),
    );
    const authTime = typeof claims.auth_time === "number"
      ? claims.auth_time
      : 0;
    const methods = Array.isArray(claims.amr) ? claims.amr : [];
    const freshOtp = methods.some((entry: unknown) => {
      if (typeof entry !== "object" || entry === null) return false;
      const method = "method" in entry ? entry.method : null;
      const timestamp = "timestamp" in entry ? entry.timestamp : null;
      return method === "otp" && typeof timestamp === "number" &&
        timestamp <= nowSeconds && nowSeconds - timestamp <= 600;
    });
    return claims.sub === userId && authTime > 0 && authTime <= nowSeconds &&
      nowSeconds - authTime <= 600 && freshOtp;
  } catch {
    return false;
  }
}

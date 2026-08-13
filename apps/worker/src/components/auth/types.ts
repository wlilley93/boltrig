export type GateState =
  | "checking"
  | "authenticated"
  | "unauthenticated"
  | "password_change_required"
  | "enrollment_required";

export type RecoveryFlow = "none" | "request" | "confirm";

import { useContext } from "react";

import { AuthContext } from "../../app/App";

export const ROLE_LEVEL = Object.freeze({
  Viewer: 0,
  Operator: 1,
  Engineer: 2,
  Admin: 3,
});

export const hasRole = (mode, identity, requiredRole) => {
  if (!(requiredRole in ROLE_LEVEL)) return false;
  const level =
    mode === "open"
      ? ROLE_LEVEL.Admin
      : mode === "local"
      ? ROLE_LEVEL[identity?.role] ?? -1
      : -1;
  return level >= ROLE_LEVEL[requiredRole];
};

export const roleBlockReason = (mode, identity, requiredRole) => {
  if (mode === "local" && !identity) return "Login required";
  if (mode === "unavailable" || mode === "unknown")
    return "Authentication state unavailable";
  return hasRole(mode, identity, requiredRole)
    ? ""
    : `${requiredRole} permission required`;
};

export const useRoleAccess = (requiredRole) => {
  const { mode, identity } = useContext(AuthContext);
  return {
    allowed: hasRole(mode, identity, requiredRole),
    reason: roleBlockReason(mode, identity, requiredRole),
  };
};

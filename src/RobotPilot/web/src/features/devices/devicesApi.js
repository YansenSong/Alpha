import { apiFetch } from "../../shared/api/apiFetch";

export const fetchSerialPorts = async () => {
  const response = await apiFetch("/api/devices/serial-ports", {
    cache: "no-store",
  });
  return response.json();
};

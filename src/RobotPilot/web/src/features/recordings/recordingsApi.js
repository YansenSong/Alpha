import { apiFetch } from "../../shared/api/apiFetch";

const readJsonResponse = async (response) => {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      data.message ||
        data.description ||
        "Something went wrong talking to the robot. Try again.",
    );
  }
  return data;
};

const postJson = async (path, body) =>
  readJsonResponse(
    await apiFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }),
  );

export const fetchRecordings = async () =>
  readJsonResponse(await apiFetch("/api/recordings", { cache: "no-store" }));

export const fetchRecordingsStatus = async () =>
  readJsonResponse(
    await apiFetch("/api/recordings/status", { cache: "no-store" }),
  );

export const startRecording = ({ name, description, topics }) =>
  postJson("/api/recordings/start", { name, description, topics });

export const stopRecording = () => postJson("/api/recordings/stop");

// Triggers a browser download of the zipped bag. Not a fetch — pointing the
// browser at the URL lets it stream the (potentially large) archive straight
// to disk without buffering it in JS memory.
export const downloadRecording = (id) => {
  window.open(
    `/api/recordings/${encodeURIComponent(id)}/download`,
    "_blank",
    "noopener",
  );
};

export const deleteRecording = async (id) =>
  readJsonResponse(
    await apiFetch(`/api/recordings/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  );

export const startReplay = (id, rate) =>
  postJson(`/api/recordings/${encodeURIComponent(id)}/replay/start`, { rate });

export const stopReplay = () => postJson("/api/recordings/replay/stop");
export const pauseReplay = () => postJson("/api/recordings/replay/pause");
export const resumeReplay = () => postJson("/api/recordings/replay/resume");

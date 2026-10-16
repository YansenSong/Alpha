const MAX_EXPONENT = 20;
const JITTER_RATIO = 0.2;

export function getReconnectDelay(
  attempt,
  baseMs = 1000,
  maxMs = 30000,
  random = Math.random,
) {
  const normalizedAttempt = Number.isFinite(attempt)
    ? Math.max(0, Math.floor(attempt))
    : 0;
  const safeBase = Number.isFinite(baseMs) && baseMs > 0 ? baseMs : 1000;
  const safeMax = Number.isFinite(maxMs) && maxMs >= safeBase ? maxMs : 30000;
  const exponent = Math.min(normalizedAttempt, MAX_EXPONENT);
  const backoff = Math.min(safeMax, safeBase * 2 ** exponent);
  const sample = Math.max(0, Math.min(1, random()));
  const jittered = backoff * (1 - JITTER_RATIO + sample * JITTER_RATIO * 2);
  return Math.min(safeMax, Math.round(jittered));
}

export function createReconnectController({
  connect,
  baseMs = 1000,
  maxMs = 30000,
  random = Math.random,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) {
  let attempt = 0;
  let timer = null;
  let disposed = false;

  return {
    schedule() {
      if (disposed || timer !== null) return null;
      const delay = getReconnectDelay(attempt, baseMs, maxMs, random);
      attempt += 1;
      timer = setTimer(() => {
        timer = null;
        if (!disposed) connect();
      }, delay);
      return delay;
    },
    connected() {
      attempt = 0;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
    dispose() {
      disposed = true;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
  };
}

import { createGateway } from "./server.mjs";

if (!process.argv.includes("--trust-project")) {
  console.error("Pass --trust-project to authorize this repository's Pi resources for this process.");
  process.exitCode = 1;
} else {
  try {
    const port = Number(process.env.PI_GATEWAY_PORT ?? 8769);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid PI_GATEWAY_PORT");
    const gateway = await createGateway({ port });
    console.log(`Pi Gateway: ws://127.0.0.1:${gateway.port}/agent-api/ws (local development only)`);
    let stopping = false;
    const stop = async () => {
      if (stopping) return;
      stopping = true;
      const deadline = setTimeout(() => process.exit(1), 10000);
      try { await gateway.close(); } catch { process.exitCode = 1; }
      finally { clearTimeout(deadline); }
    };
    process.on("SIGINT", stop);
    process.on("SIGTERM", stop);
  } catch (error) {
    console.error(`Gateway startup failed: ${error.message}`);
    process.exitCode = 1;
  }
}

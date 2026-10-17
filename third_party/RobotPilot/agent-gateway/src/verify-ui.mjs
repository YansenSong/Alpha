import { checkUiModules } from "./ui-module-check.mjs";
try {
  const count = await checkUiModules(process.argv[2] ?? "http://127.0.0.1:3000");
  console.log(`PASS ${count} live Vite modules, including the lazy AgentPage default export`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}

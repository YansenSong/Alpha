import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { checkUiModules } from "../src/ui-module-check.mjs";

test("rejects a 200 response containing an empty lazy module", async () => {
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/javascript" });
    res.end("\n//# sourceMappingURL=data:application/json;base64,e30=");
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    await assert.rejects(checkUiModules(`http://127.0.0.1:${server.address().port}`), /AgentPage\.jsx.*missing export default/);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

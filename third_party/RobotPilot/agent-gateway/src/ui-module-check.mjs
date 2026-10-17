// An HTTP 200 SPA shell is insufficient: React.lazy also needs a real export.
export async function checkUiModules(baseUrl) {
  const modules = [
    ["/src/pages/AgentPage.jsx", "export default"],
    ["/src/features/agent/AssistantMessage.jsx", "export default"],
    ["/src/features/agent/ToolCallCard.jsx", "export default"],
    ["/src/features/agent/useTranscriptScroll.js", "export default"],
    ["/src/features/agent/useAgentSocket.js", "export default"],
    ["/src/features/agent/groupMessages.js", "export function groupMessages"],
    ["/src/features/agent/agentReducer.js", "export function agentReducer"],
  ];
  for (const [pathname, expected] of modules) {
    const response = await fetch(new URL(pathname, baseUrl), { signal: AbortSignal.timeout(10000) });
    const source = await response.text();
    if (!response.ok || !source.includes(expected)) {
      throw new Error(`Invalid Vite module ${pathname}: HTTP ${response.status}, missing ${expected}. Recompile or restart the development server.`);
    }
  }
  return modules.length;
}

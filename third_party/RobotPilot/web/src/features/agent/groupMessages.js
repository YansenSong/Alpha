// Pi may emit several assistant messages and tool calls for one response.
// Group consecutive agent activity under one author, keeping event order intact.
export function groupMessages(items) {
  const groups = [];
  for (const item of items) {
    if (item.role === "user") {
      groups.push({ id: item.id, role: "user", parts: [item] });
      continue;
    }
    let group = groups.at(-1);
    if (!group || group.role === "user") {
      group = { id: item.id, role: "assistant", parts: [] };
      groups.push(group);
    }
    group.parts.push(item);
  }
  return groups
    .map((group) => {
      const parts = group.parts.filter(
        (item, index) =>
          item.role !== "assistant" ||
          item.text?.trim() ||
          (item.status === "running" && index === group.parts.length - 1) ||
          ["error", "aborted", "interrupted"].includes(item.status),
      );
      return {
        ...group,
        parts,
        status: parts.some((part) => part.status === "running")
          ? "running"
          : parts.at(-1)?.status ?? "done",
      };
    })
    .filter((group) => group.parts.length);
}

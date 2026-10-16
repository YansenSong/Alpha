let transport = null;

export const setMissionCommandTransport = (next) => {
  transport = next;
};

export const sendMissionCommand = (command) => {
  if (!transport) return false;
  transport(command);
  return true;
};

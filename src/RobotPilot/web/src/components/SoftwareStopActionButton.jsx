import React from "react";

const SoftwareStopActionButton = ({
  active = false,
  children,
  disabled = false,
  onClick,
  title,
}) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={title}
    className={`inline-flex h-9 w-28 shrink-0 items-center justify-center rounded-lg border-2 px-2 font-[RobotoMono] text-[9px] font-bold leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
      active
        ? "border-statusYellow bg-statusYellow/10 text-statusYellow hover:bg-statusYellow hover:text-bgBase"
        : "border-statusRed bg-statusRed/10 text-statusRed hover:bg-statusRed hover:text-white"
    }`}
  >
    {children}
  </button>
);

export default SoftwareStopActionButton;

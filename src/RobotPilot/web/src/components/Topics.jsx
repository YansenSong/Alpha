import { T } from "../shared/i18n/i18n";
import React from "react";

const RobotLog = () => {
  return (
    <article className="h-full w-full rounded-lg bg-white font-[RobotoMono] ">
      <header className="flex items-center justify-between rounded-t-lg bg-themeLightGray px-4">
        <h2 className="text-2xl text-black">
          <T>{"Topics"}</T>
        </h2>
        <button className="my-2 cursor-auto rounded-lg bg-white px-[14px] py-[7px] text-xl">
          <T>{"Clear"}</T>{" "}
        </button>
      </header>
      <ul className="flex h-[70px] flex-col overflow-y-auto px-4 py-3">
        <li className="flex h-full items-center justify-center text-center font-[RobotoMono] text-[20px] text-themeTextGray">
          <T>{"Coming soon!"}</T>{" "}
        </li>
      </ul>
    </article>
  );
};

export default RobotLog;

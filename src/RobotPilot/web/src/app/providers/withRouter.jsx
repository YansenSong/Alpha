import React, { Suspense } from "react";
import { BrowserRouter } from "react-router-dom";

const withRouter = (component) => () => (
  <BrowserRouter>
    <Suspense fallback={<div className="p-6 text-sm">正在加载页面…</div>}>{component()}</Suspense>
  </BrowserRouter>
);

export default withRouter;

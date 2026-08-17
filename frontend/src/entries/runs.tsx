// The /runs page's real mounting entry -- replaces plan 22-03's build-only
// placeholder. Reads the embedded __INITIAL_DATA__ island, finds the mount element
// react_page.html renders, and mounts <RunsPage> onto it.
import { createRoot } from "react-dom/client";

import { readInitialData } from "../boot/pageData";
import { RunsPage, type RunsListPage } from "../pages/RunsPage";

// Must match app/routes/templating.py's REACT_MOUNT_ID literal exactly.
const MOUNT_ELEMENT_ID = "react-root";

const data = readInitialData<RunsListPage>();
const mountElement = document.getElementById(MOUNT_ELEMENT_ID);
if (!mountElement) {
  throw new Error(
    `runs entry: no element with id "${MOUNT_ELEMENT_ID}" to mount RunsPage into`,
  );
}

createRoot(mountElement).render(<RunsPage data={data} />);

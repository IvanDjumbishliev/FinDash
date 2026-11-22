import assert from "node:assert/strict";
import test from "node:test";
import { dashboardSections, defaultWidgets, readWidgets, saveWidgets } from "../src/dashboard.js";

test("dashboard preferences persist per account, including a layout with no widgets", () => {
  const storage = new Map();
  const local = { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) };
  assert.deepEqual(readWidgets(local, 11), defaultWidgets);
  saveWidgets(local, 11, ["portfolio", "monthly", "obsolete"]);
  saveWidgets(local, 12, []);
  assert.deepEqual(readWidgets(local, 11), ["monthly", "portfolio"]);
  assert.deepEqual(readWidgets(local, 12), []);
  assert.deepEqual(readWidgets(local, 13), defaultWidgets);
});

test("dashboard requests only selected aggregate widgets and ignores blocked storage", () => {
  assert.equal(dashboardSections(["forecast", "heatmap", "monthly", "deals"]), "monthly,deals");
  assert.deepEqual(readWidgets({ getItem: () => { throw Error("Blocked"); } }, 14), defaultWidgets);
});

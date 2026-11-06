import assert from "node:assert/strict";
import { test } from "node:test";

import { translator } from "../../../i18n/core.js";
import { statusLabel } from "./statusLabels.js";
import { loadingProgress } from "./loadingState.js";

test("every loading step the screen can show, and every update line, is said in the view's language", () => {
  const zh = translator("zh-CN");
  for (const phase of ["", "catalog", "compile", "generate", "meshing", "read", "geometry", "view"]) {
    const { label } = loadingProgress({ phase });
    assert.notEqual(statusLabel(label, zh), label, `${label} has a translation`);
  }
  assert.equal(statusLabel("Opening model", zh), "正在打开模型");
  assert.equal(statusLabel("Meshing parts 37/256…", zh), "正在网格化零件 37/256…");
  assert.equal(statusLabel("Updating model…", translator("ja")), "モデルを更新しています…");
  assert.equal(statusLabel("A file's own words", zh), "A file's own words", "anything else shows as it came");
  assert.equal(statusLabel("Opening model"), "Opening model", "English without a translator");
});

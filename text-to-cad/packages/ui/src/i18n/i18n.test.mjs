import assert from "node:assert/strict";
import { test } from "node:test";

import en from "./locales/en.js";
import ja from "./locales/ja.js";
import ko from "./locales/ko.js";
import zhCN from "./locales/zh-CN.js";
import zhTW from "./locales/zh-TW.js";
import { DEFAULT_LOCALE, LOCALES, english, localeForTag, normalizeLocale, resolveLocale, translateIn, translator } from "./core.js";

const TABLES = { "en": en, "zh-CN": zhCN, "zh-TW": zhTW, "ja": ja, "ko": ko };

test("every locale answers with the same keys as English, and agrees with it on placeholders", () => {
  assert.deepEqual(Object.keys(TABLES), [...LOCALES], "every locale has its dictionary here");
  for (const locale of LOCALES) {
    const table = TABLES[locale];
    assert.deepEqual(Object.keys(table).sort(), Object.keys(en).sort(), `${locale}'s keys drift from en's`);
    for (const [key, text] of Object.entries(table)) {
      const wanted = [...String(en[key]).matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort().join(",");
      const got = [...String(text).matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort().join(",");
      assert.equal(got, wanted, `${locale}.${key}'s placeholders drift from en's`);
    }
  }
  assert.equal(LOCALES[0], DEFAULT_LOCALE, "English is first and the default");
});

test("each language is named in its own language, the same in every dictionary", () => {
  const names = { "en": "English", "zh-CN": "简体中文", "zh-TW": "繁體中文", "ja": "日本語", "ko": "한국어" };
  for (const table of Object.values(TABLES)) {
    for (const locale of LOCALES) assert.equal(table[`language.${locale}`], names[locale]);
  }
});

test("Traditional Chinese is Taiwan's own words, not Simplified Chinese converted", () => {
  assert.equal(zhTW["file.missing"], "檔案不存在");
  assert.equal(zhTW["explorer.folders"], "資料夾");
  assert.equal(zhCN["explorer.folders"], "文件夹");
  assert.equal(zhTW["explorer.searching"], "搜尋中…");
});

test("normalizeLocale takes the exact locale, else the case-folded one, else nothing", () => {
  assert.equal(normalizeLocale("en"), "en");
  assert.equal(normalizeLocale("zh-CN"), "zh-CN");
  assert.equal(normalizeLocale("ZH-cn"), "zh-CN");
  assert.equal(normalizeLocale("fr"), undefined);
  assert.equal(normalizeLocale(""), undefined);
  assert.equal(normalizeLocale(undefined), undefined);
});

test("a language tag reads in its locale: Chinese by script, else region", () => {
  for (const tag of ["zh", "zh-CN", "zh-Hans", "zh-SG", "zh-Hans-HK", "zh_CN"]) assert.equal(localeForTag(tag), "zh-CN", tag);
  for (const tag of ["zh-TW", "zh-Hant", "zh-HK", "zh-MO", "zh-Hant-CN", "zh_TW"]) assert.equal(localeForTag(tag), "zh-TW", tag);
  for (const tag of ["ja", "ja-JP"]) assert.equal(localeForTag(tag), "ja", tag);
  for (const tag of ["ko", "ko-KR"]) assert.equal(localeForTag(tag), "ko", tag);
  for (const tag of ["en", "en-GB"]) assert.equal(localeForTag(tag), "en", tag);
  for (const tag of ["fr-FR", "de", "", undefined]) assert.equal(localeForTag(tag), undefined, String(tag));
});

test("resolveLocale takes the first preference the viewer speaks", () => {
  assert.equal(resolveLocale(["zh-CN", "en"]), "zh-CN");
  assert.equal(resolveLocale(["fr-FR", "zh-TW", "en"]), "zh-TW");
  assert.equal(resolveLocale(["fr-FR", "en-US", "ja"]), "en");
  assert.equal(resolveLocale([undefined, "ko-KR"]), "ko", "a host with no locale falls to the browser's");
  assert.equal(resolveLocale(["fr-FR", "de-DE"]), "en", "nothing understood is English");
  assert.equal(resolveLocale([]), "en");
  assert.equal(resolveLocale(undefined), "en");
});

test("a locale's translator fills braces, is one function per locale, and an unknown locale reads English", () => {
  const t = translator("zh-CN");
  assert.equal(t("file.missing"), "文件不存在");
  assert.equal(t("home.openAria", { name: "bracket.step" }), "打开 bracket.step");
  assert.equal(translator("zh-CN"), t, "the same function every time, so a memo on it holds until the language changes");
  assert.equal(translator("fr"), english);
  assert.equal(translator(undefined), english);
  assert.equal(english("file.missing"), "File does not exist");
});

test("a locale that misses a key reads English; a key nobody has reads as itself", () => {
  assert.equal(translateIn("zh-CN", "home.byline"), "构建万物。");
  assert.equal(translateIn("en", "home.byline"), "Build anything.");
  assert.equal(translateIn("zh-CN", "no.such.key"), "no.such.key");
  assert.equal(translateIn("fr", "file.missing"), "File does not exist", "an unsupported locale reads English");
});

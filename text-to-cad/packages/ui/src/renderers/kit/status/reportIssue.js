import { issueUrl } from "../../../file-viewer/navigation/links.js";

// Report Issue opens as "Issue: ", for the person to finish, labelled `bug` — the label GitHub gives
// every repository for "Something isn't working". GitHub applies a URL's labels only for someone
// with triage access to the repository and drops them for everyone else, who open the issue
// unlabelled, so naming one costs nobody anything.
const TITLE = "Issue: ";
const LABELS = ["bug"];

// The failure as the card shows it, bold: its first line, no longer than the card lets it be.
const firstLine = (text) => String(text || "").split("\n").map((line) => line.trim()).find(Boolean) || "";
const clip = (text, length) => (text.length > length ? `${text.slice(0, length)}…` : text);

// A path separator as it is written, or as a request's URL spells it; where more than one stand
// together, they are one.
const SLASH = String.raw`(?:[\\/]|%2f|%5c)`;
const SEPARATOR = `${SLASH}+`;
// One word of a name: no separator, no space.
const WORD = String.raw`(?:(?!${SLASH})\S)+`;
// A home directory: `/Users/ada/`, `/home/ada/`, or on a drive `C:\Users\Ada Lovelace\`, whose name may
// hold spaces. A letter is a drive only on its own: what comes before it is kept.
const HOME = new RegExp(String.raw`(?:(^|\W)[a-z](?::|%3a)${SLASH}users${SEPARATOR}${WORD}(?: ${WORD})*|${SLASH}(?:users|home)${SEPARATOR}${WORD})${SEPARATOR}`, "giu");

const escaped = (text) => text.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
// One part of a path as it is written, and as a request's URL spells it (`%20`, or `+`).
const spellings = (part) => {
  let encoded = part;
  try { encoded = encodeURIComponent(part); } catch { /* an unpaired surrogate is written as it is */ }
  return [...new Set([part, encoded, new URLSearchParams({ part }).toString().slice("part=".length)])].map(escaped).join("|");
};

/**
 * What of the card's text may leave the machine. `file`, the path the alert names the file by
 * (absolute, as the catalog lists it), is written as its name wherever it stands — with either
 * slash, or in a request's URL — and then any home directory left, in a path the failure names (a
 * traceback's, a package's), as `~/`. Returns `file`'s name and the function that does this to a text.
 * Only `file` itself is found: a longer path that happens to end as it does, under another root,
 * keeps its directories.
 */
function withoutPaths(file) {
  const parts = String(file || "").split(/[\\/]+/u).filter(Boolean);
  const name = parts[parts.length - 1] || "";
  // A path of one part is its name already. Found whole: not after a word or a directory, not before more of a word.
  const path = parts.length > 1
    ? new RegExp(String.raw`(^|[^\w.~/\\-])(?:${SEPARATOR})?${parts.map((part) => `(?:${spellings(part)})`).join(SEPARATOR)}(?![\w-])`, "giu") : null;
  const scrub = (text) => {
    const written = String(text ?? "");
    return (path ? written.replace(path, (_, before) => `${before}${name}`) : written).replace(HOME, (_, before = "") => `${before}~/`);
  };
  return { name, scrub };
}

/**
 * Report Issue's address, from the alert card (`ViewerAlertCard`): a new issue on `issues` saying
 * what the card says. It opens as "Issue: " for the person to finish, labelled `bug`; its body asks
 * what the person was doing, quotes the card — title, message, failure — and names the file (by
 * its name, never its path), the version and the platform; the card's Details close it, and are
 * what gives way when the address grows too long (`issueUrl`). Nothing of this machine goes with
 * it: the file's path is written as its name wherever the card writes it, and a home directory
 * in anything else as `~/`. "" where the host has no tracker.
 *
 * @param {string | undefined} issues `ViewerLinks.issues`.
 * @param {{ title: string, message?: string, reason?: string, details?: string }} alert
 *   The card's alert, its `title` as the card shows it.
 * @param {{ file?: string, version?: string, platform?: string }} [about]
 *   The file's path as the alert names it (absolute), the host's version and platform.
 */
export function alertIssueUrl(issues, alert, { file = "", version = "", platform = "" } = {}) {
  const { name, scrub } = withoutPaths(file);
  // Scrubbed whole, then cut: a path cut in half is no longer one to find.
  const reason = clip(firstLine(scrub(alert.reason)), 360);
  const quote = [`**${scrub(alert.title)}**`, scrub(alert.message).trim(), reason].filter(Boolean)
    .join("\n").split("\n").map((line) => `> ${line}`.trimEnd()).join("\n");
  return issueUrl(issues, {
    title: TITLE,
    labels: LABELS,
    body: `**What were you doing?**\n\n\n\n**Error**\n\n${quote}`,
    about: { File: name, CAD: version, Platform: platform },
    details: scrub(alert.details)
  });
}

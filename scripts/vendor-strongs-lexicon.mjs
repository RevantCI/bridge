#!/usr/bin/env node

import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import {
  mkdir, readFile, rename, rm, writeFile,
} from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { execFileSync } from "node:child_process";

const SCHEMA = "bridge-strongs-lexicon/v1";
const OWNER = "Open Scriptures";
const PINNED_COMMIT = "0acd2f251c2d35ff8db2dece4e0593979d3ac223";
const REPOSITORY = "https://github.com/openscriptures/strongs.git";
const RELEASE = "https://github.com/openscriptures/strongs";

function usage() {
  console.error(
    "Usage: node scripts/vendor-strongs-lexicon.mjs --checkout <openscriptures/strongs checkout> " +
    "[--output engine/resources]",
  );
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || !value) {
      usage();
      process.exit(2);
    }
    parsed[flag.slice(2)] = value;
  }
  if (!parsed.checkout) {
    usage();
    process.exit(2);
  }
  return parsed;
}

function sha256(data) {
  return createHash("sha256").update(data).digest("hex");
}

function gitHead(checkout) {
  return execFileSync("git", ["-C", checkout, "rev-parse", "HEAD"], {
    encoding: "utf8",
  }).trim();
}

// The Hebrew data's KJV renderings use "[idiom]"/"[phrase]" as literal
// placeholder tokens for the traditional Strong's typographic markers ×
// (a KJV word supplied to complete the sense) and + (a KJV word joined from
// a separate original-language term). The Greek data does not use these
// tokens (it spells the idiom marker as literal "X" instead) so it is left
// untouched rather than guessing a replacement.
function normalizeKjvDef(text) {
  if (!text) return text;
  return text.replaceAll("[idiom]", "×").replaceAll("[phrase]", "+");
}

function clean(text) {
  return typeof text === "string" ? text.trim() : text;
}

function compactHebrewEntry(strong, raw) {
  const out = { strong };
  if (raw.lemma) out.lemma = clean(raw.lemma);
  if (raw.xlit) out.translit = clean(raw.xlit);
  if (raw.pron) out.pron = clean(raw.pron);
  if (raw.derivation) out.derivation = clean(raw.derivation);
  if (raw.strongs_def) out.meaning = clean(raw.strongs_def);
  if (raw.kjv_def) out.usage = normalizeKjvDef(clean(raw.kjv_def));
  return out;
}

function compactGreekEntry(strong, raw) {
  const out = { strong };
  if (raw.lemma) out.lemma = clean(raw.lemma);
  if (raw.translit) out.translit = clean(raw.translit);
  if (raw.derivation) out.derivation = clean(raw.derivation);
  if (raw.strongs_def) out.meaning = clean(raw.strongs_def);
  if (raw.kjv_def) out.usage = clean(raw.kjv_def);
  return out;
}

async function buildLanguage({
  languageId, entries, outputRoot, checkout, sourceFile, packageVersion,
}) {
  const pack = {
    schema: SCHEMA,
    languageId,
    resourceId: "strongs",
    version: packageVersion,
    owner: OWNER,
    sourceCommit: PINNED_COMMIT,
    sourceFile,
    entries,
  };
  const packedBytes = gzipSync(Buffer.from(JSON.stringify(pack), "utf8"), {
    level: 9,
    mtime: 0,
  });

  const destination = path.resolve(
    outputRoot, languageId, "lexicons", "strongs", `v${packageVersion}_openscriptures`,
  );
  const expectedParent = path.resolve(outputRoot, languageId, "lexicons", "strongs");
  if (path.dirname(destination) !== expectedParent) {
    throw new Error(`Unsafe output path: ${destination}`);
  }
  const staging = `${destination}.staging`;
  await rm(staging, { recursive: true, force: true });
  await mkdir(staging, { recursive: true });

  const outputName = "entries.json.gz";
  await writeFile(path.join(staging, outputName), packedBytes);
  const artifactSha256 = sha256(packedBytes);

  await writeFile(path.join(staging, "index.json"), `${JSON.stringify({
    schema: SCHEMA,
    languageId,
    resourceId: "strongs",
    version: packageVersion,
    owner: OWNER,
    entries: Object.keys(entries).length,
  }, null, 2)}\n`, "utf8");

  const provenance = {
    schemaVersion: 1,
    artifactName: `Bridge Strong's Lexicon (${languageId})`,
    description:
      "A compact derivative of Open Scriptures' Strong's Dictionary JSON, keyed by Strong's " +
      "number. Retains lemma, transliteration, pronunciation (Hebrew only), derivation, the " +
      "Strong's-def gloss, and the KJV-def usage note for every entry.",
    license: "CC-BY-SA (Open Scriptures); underlying 1890s Strong's Concordance text is public domain",
    attribution: `Open Scriptures' Strong's Dictionaries of Hebrew and Greek, ${RELEASE}`,
    source: {
      repository: REPOSITORY,
      release: RELEASE,
      commit: PINNED_COMMIT,
      languageId,
      resourceId: "strongs",
      version: packageVersion,
      owner: OWNER,
      sourceFile,
      sourceSha256: sha256(await readFile(path.join(checkout, sourceFile))),
    },
    generator: {
      script: "scripts/vendor-strongs-lexicon.mjs",
      schema: SCHEMA,
    },
    changes: [
      `Extracted the ${languageId === "hbo" ? "hebrew/strongs-hebrew-dictionary.js" : "greek/strongs-greek-dictionary.js"} CommonJS module's data object.`,
      "Renamed fields to a stable schema (lemma/translit/pron/derivation/meaning/usage) shared across both languages.",
      languageId === "hbo"
        ? "Normalized the \"[idiom]\"/\"[phrase]\" placeholder tokens in KJV usage notes to ×/+ (the traditional Strong's typographic markers); left untouched for Greek, which does not use these tokens."
        : "No placeholder-token normalization was needed for the Greek usage notes.",
      "Compressed the whole per-language dictionary into one gzip artifact (lookup is by Strong's number, not by book/verse, so no per-book split is needed).",
    ],
    artifacts: { entries: { artifact: outputName, artifactSha256, entries: Object.keys(entries).length } },
  };
  await writeFile(
    path.join(staging, "PROVENANCE.json"),
    `${JSON.stringify(provenance, null, 2)}\n`,
    "utf8",
  );

  await writeFile(path.join(staging, "NOTICE.md"), `# Bridge Strong's Lexicon (${languageId})

This directory contains a modified, compressed derivative of the Strong's Hebrew/Greek
Dictionary JSON data published by Open Scriptures at ${RELEASE} (commit \`${PINNED_COMMIT}\`).

That data's own file header states:

> Copyright ${languageId === "hbo" ? "2010" : "2009"}, Open Scriptures. CC-BY-SA. Derived from XML.

The underlying dictionary text is James Strong's *Exhaustive Concordance* (Hebrew dictionary
1894, Greek dictionary 1890), which is in the public domain. Open Scriptures' JSON/XML encoding
and corrections layered on top of that public-domain text are what carry the CC-BY-SA notice
above (no specific CC-BY-SA version number is stated in the source file itself).

See \`PROVENANCE.json\` for the exact source commit, artifact hash, and the changes made by
Bridge's vendoring script.
`, "utf8");

  await rm(destination, { recursive: true, force: true });
  await mkdir(expectedParent, { recursive: true });
  await rename(staging, destination);
  console.log(`${languageId}: ${Object.keys(entries).length} entries -> ${destination}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const checkout = path.resolve(args.checkout);
  const actualCommit = gitHead(checkout);
  if (actualCommit !== PINNED_COMMIT) {
    throw new Error(`openscriptures/strongs must be checked out at ${PINNED_COMMIT}; found ${actualCommit}`);
  }

  const require = createRequire(import.meta.url);
  const packageJson = JSON.parse(await readFile(path.join(checkout, "package.json"), "utf8"));
  const hebrewPath = path.join(checkout, "hebrew", "strongs-hebrew-dictionary.js");
  const greekPath = path.join(checkout, "greek", "strongs-greek-dictionary.js");
  const hebrewRaw = require(hebrewPath);
  const greekRaw = require(greekPath);

  const hebrewEntries = {};
  for (const [strong, raw] of Object.entries(hebrewRaw)) {
    hebrewEntries[strong] = compactHebrewEntry(strong, raw);
  }
  const greekEntries = {};
  for (const [strong, raw] of Object.entries(greekRaw)) {
    greekEntries[strong] = compactGreekEntry(strong, raw);
  }

  const outputRoot = path.resolve(args.output ?? "engine/resources");

  await buildLanguage({
    languageId: "hbo",
    entries: hebrewEntries,
    outputRoot,
    checkout,
    packageVersion: packageJson.version,
    sourceFile: "hebrew/strongs-hebrew-dictionary.js",
  });
  await buildLanguage({
    languageId: "el-x-koine",
    entries: greekEntries,
    outputRoot,
    checkout,
    packageVersion: packageJson.version,
    sourceFile: "greek/strongs-greek-dictionary.js",
  });
}

await main();

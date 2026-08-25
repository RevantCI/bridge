#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import {
  cp, mkdir, readFile, readdir, rename, rm, stat, writeFile,
} from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import usfm from "usfm-js";
import wordAlignerPackage from "word-aligner";

const aligner = wordAlignerPackage.default ?? wordAlignerPackage;
const SCHEMA = "bridge-original-language-token-pack/v1";
const OWNER = "unfoldingWord";
const resources = [
  {
    key: "uhb",
    languageId: "hbo",
    resourceId: "uhb",
    version: "3.0.0",
    tag: "v3.0.0",
    commit: "74022f0fed012a3ef169886f595dd98e7b200543",
    repository: "https://git.door43.org/unfoldingWord/hbo_uhb.git",
    release: "https://git.door43.org/unfoldingWord/hbo_uhb/releases/tag/v3.0.0",
    expectedBooks: 39,
  },
  {
    key: "ugnt",
    languageId: "el-x-koine",
    resourceId: "ugnt",
    version: "0.34",
    tag: "v0.34",
    commit: "fc95b2b8aad08bb65ab54628ab685413a1139e97",
    repository: "https://git.door43.org/unfoldingWord/el-x-koine_ugnt.git",
    release: "https://git.door43.org/unfoldingWord/el-x-koine_ugnt/releases/tag/v0.34",
    expectedBooks: 27,
  },
];

function usage() {
  console.error(
    "Usage: node scripts/vendor-original-language-resources.mjs " +
    "--uhb <UHB v3.0.0 checkout> --ugnt <UGNT v0.34 checkout> [--output engine/resources]",
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
  if (!parsed.uhb || !parsed.ugnt) {
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

function bookIdFromUsfm(source) {
  const match = source.match(/^\\id\s+([A-Z0-9]{3})\b/m);
  if (!match) throw new Error("USFM file has no valid \\id marker");
  return match[1].toLowerCase();
}

function compactToken(token) {
  const out = {
    word: String(token.word ?? ""),
    occurrence: Number(token.occurrence ?? 1),
    occurrences: Number(token.occurrences ?? 1),
  };
  for (const field of ["strong", "lemma", "morph"]) {
    if (token[field]) out[field] = String(token[field]);
  }
  return out;
}

function tokenPack(source, resource, sourceFile) {
  const converted = usfm.toJSON(source, {
    convertToInt: ["occurrence", "occurrences"],
  });
  const bookId = bookIdFromUsfm(source);
  const chapters = {};
  let tokenCount = 0;
  let verseCount = 0;
  for (const chapter of Object.keys(converted.chapters ?? {})) {
    if (!/^\d+$/.test(chapter)) continue;
    const verses = {};
    for (const [verse, verseData] of Object.entries(converted.chapters[chapter] ?? {})) {
      if (!/^\d+(?:-\d+)?[a-z]?$/.test(verse)) continue;
      const tokens = aligner.generateBlankAlignments(verseData)
        .map((alignment) => compactToken(alignment.topWords[0]));
      verses[verse] = tokens;
      tokenCount += tokens.length;
      verseCount += 1;
    }
    chapters[chapter] = verses;
  }
  return {
    pack: {
      schema: SCHEMA,
      languageId: resource.languageId,
      resourceId: resource.resourceId,
      version: resource.version,
      owner: OWNER,
      sourceCommit: resource.commit,
      sourceFile,
      bookId,
      chapters,
    },
    bookId,
    tokenCount,
    verseCount,
  };
}

async function buildResource(resource, checkout, outputRoot) {
  const resolvedCheckout = path.resolve(checkout);
  if (!(await stat(resolvedCheckout)).isDirectory()) {
    throw new Error(`${resource.key} checkout is not a directory: ${resolvedCheckout}`);
  }
  const actualCommit = gitHead(resolvedCheckout);
  if (actualCommit !== resource.commit) {
    throw new Error(
      `${resource.key} must be checked out at ${resource.commit}; found ${actualCommit}`,
    );
  }

  const manifest = await readFile(path.join(resolvedCheckout, "manifest.yaml"));
  const license = await readFile(path.join(resolvedCheckout, "LICENSE.md"));
  const manifestText = manifest.toString("utf8");
  for (const expected of [
    `identifier: '${resource.resourceId}'`,
    `version: '${resource.version}'`,
    "rights: 'CC BY-SA 4.0'",
  ]) {
    if (!manifestText.includes(expected)) {
      throw new Error(`${resource.key} manifest does not contain ${expected}`);
    }
  }

  const files = (await readdir(resolvedCheckout))
    .filter((name) => /^\d{2}-[A-Z0-9]{3}\.usfm$/.test(name))
    .sort();
  if (files.length !== resource.expectedBooks) {
    throw new Error(
      `${resource.key} expected ${resource.expectedBooks} USFM books; found ${files.length}`,
    );
  }

  const destination = path.resolve(
    outputRoot,
    resource.languageId,
    "bibles",
    resource.resourceId,
    `v${resource.version}_${OWNER}`,
  );
  const expectedParent = path.resolve(
    outputRoot, resource.languageId, "bibles", resource.resourceId,
  );
  if (path.dirname(destination) !== expectedParent) {
    throw new Error(`Unsafe output path: ${destination}`);
  }
  const staging = `${destination}.staging`;
  await rm(staging, { recursive: true, force: true });
  await mkdir(staging, { recursive: true });

  const artifacts = {};
  const index = {};
  let totalTokens = 0;
  let totalVerses = 0;
  for (const file of files) {
    const sourceBytes = await readFile(path.join(resolvedCheckout, file));
    const source = sourceBytes.toString("utf8");
    const { pack, bookId, tokenCount, verseCount } = tokenPack(source, resource, file);
    const packedBytes = gzipSync(Buffer.from(JSON.stringify(pack), "utf8"), {
      level: 9,
      mtime: 0,
    });
    const outputName = `${bookId}.json.gz`;
    await writeFile(path.join(staging, outputName), packedBytes);
    artifacts[bookId] = {
      sourceFile: file,
      sourceSha256: sha256(sourceBytes),
      artifact: outputName,
      artifactSha256: sha256(packedBytes),
      verses: verseCount,
      tokens: tokenCount,
    };
    index[bookId] = { verses: verseCount, tokens: tokenCount };
    totalTokens += tokenCount;
    totalVerses += verseCount;
  }

  await cp(path.join(resolvedCheckout, "manifest.yaml"), path.join(staging, "manifest.yaml"));
  await cp(path.join(resolvedCheckout, "LICENSE.md"), path.join(staging, "LICENSE.md"));
  await writeFile(path.join(staging, "index.json"), `${JSON.stringify({
    schema: SCHEMA,
    languageId: resource.languageId,
    resourceId: resource.resourceId,
    version: resource.version,
    owner: OWNER,
    books: index,
    totals: { books: files.length, verses: totalVerses, tokens: totalTokens },
  }, null, 2)}\n`, "utf8");

  const provenance = {
    schemaVersion: 1,
    artifactName: "Bridge Original-Language Token Index",
    description:
      "A compact derivative token index generated from the named original-language resource. " +
      "It excludes punctuation, ordinary text objects, and footnote words and preserves source " +
      "surface text, Strong's data, lemma, morphology, and occurrence numbering.",
    license: "CC BY-SA 4.0",
    attribution:
      `The original work by unfoldingWord is available from ${resource.release}`,
    source: {
      repository: resource.repository,
      release: resource.release,
      tag: resource.tag,
      commit: resource.commit,
      languageId: resource.languageId,
      resourceId: resource.resourceId,
      version: resource.version,
      owner: OWNER,
      manifestSha256: sha256(manifest),
      licenseSha256: sha256(license),
    },
    generator: {
      script: "scripts/vendor-original-language-resources.mjs",
      schema: SCHEMA,
      packages: { "usfm-js": "3.5.0", "word-aligner": "1.1.1" },
    },
    changes: [
      "Converted USFM 3 books to verse-level source-token indexes.",
      "Retained only tokens translationCore's word-aligner treats as original-language words.",
      "Compressed each book independently for offline, lazy loading.",
      "Did not alter the original manifest.yaml or LICENSE.md included beside this notice.",
    ],
    artifacts,
  };
  await writeFile(
    path.join(staging, "PROVENANCE.json"),
    `${JSON.stringify(provenance, null, 2)}\n`,
    "utf8",
  );
  await writeFile(path.join(staging, "NOTICE.md"), `# Bridge Original-Language Token Index

This directory contains a modified, compressed token index derived from
${resource.resourceId.toUpperCase()} ${resource.version} by unfoldingWord. The original work is
available at ${resource.release}.

The derivative index and the included source material are distributed under CC BY-SA 4.0.
See \`LICENSE.md\` for the upstream attribution and license terms and
\`PROVENANCE.json\` for the exact source commit, input/output hashes, generator versions,
and the changes made by Bridge.
`, "utf8");

  await rm(destination, { recursive: true, force: true });
  await mkdir(expectedParent, { recursive: true });
  await rename(staging, destination);
  console.log(
    `${resource.key}: ${files.length} books, ${totalVerses} verses, ${totalTokens} tokens -> ${destination}`,
  );
}

const args = parseArgs(process.argv.slice(2));
const outputRoot = path.resolve(args.output ?? "engine/resources");
await buildResource(resources[0], args.uhb, outputRoot);
await buildResource(resources[1], args.ugnt, outputRoot);

import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/svelte";

// jsdom implements no scrolling at all, so Element.scrollTo is simply absent.
// VerseList scrolls the selected verse to the top of its container; without
// this the call rejects out of band and Vitest reports an unhandled error even
// though nothing under test is broken.
if (typeof Element.prototype.scrollTo !== "function") {
  Element.prototype.scrollTo = () => {};
}

afterEach(() => cleanup());

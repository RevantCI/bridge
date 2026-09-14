import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/svelte";

// jsdom implements no scrolling at all, so Element.scrollTo is simply absent.
// VerseList scrolls the selected verse to the top of its container; without
// this the call rejects out of band and Vitest reports an unhandled error even
// though nothing under test is broken.
if (typeof Element.prototype.scrollTo !== "function") {
  Element.prototype.scrollTo = () => {};
}

// jsdom keeps one localStorage for every test in a file, so anything the app
// persists leaks into the next test. That became a real hazard once the review
// filters started remembering themselves (#61): `resetReviewState()` rehydrates
// from storage, so a test that clicked a filter chip silently armed the next
// test that called it for isolation. Clear it before each test rather than
// leaving each file to remember -- forgetting produces a confusing failure in
// a test that never mentions storage.
beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    // A test may have stubbed storage to throw; nothing to clear in that case.
  }
});

afterEach(() => cleanup());

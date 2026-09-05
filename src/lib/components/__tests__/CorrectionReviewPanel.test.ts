import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const api = vi.hoisted(() => ({
  eligibility: vi.fn(),
  context: vi.fn(),
  list: vi.fn(),
  history: vi.fn(),
  create: vi.fn(),
  edit: vi.fn(),
  reject: vi.fn(),
  regenerate: vi.fn(),
  settings: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    correctionGetEligibility: api.eligibility,
    correctionGetReviewContext: api.context,
    correctionListForFinding: api.list,
    correctionGetProposalHistory: api.history,
    correctionCreateProposal: api.create,
    correctionEditProposal: api.edit,
    correctionRejectProposal: api.reject,
    correctionRegenerateProposal: api.regenerate,
    getSettings: api.settings,
  },
}));

import CorrectionReviewPanel from "../CorrectionReviewPanel.svelte";

const targetText = "வசனம் மூன்று என்று கூறுகிறது";
const affectedText = "மூன்று";
const affectedStart = Array.from(targetText.slice(0, targetText.indexOf(affectedText))).length;
const affectedEnd = affectedStart + Array.from(affectedText).length;

const intent = {
  failedDimension: "QUANTITY",
  observedMeaning: "three",
  requiredMeaning: "all",
  affectedSourceSemanticUnitIds: ["source-quantity"],
  affectedTargetSpan: {
    displayedReference: "PHP 1:5",
    canonicalReferences: ["PHP 1:5"],
    startCodePoint: affectedStart,
    endCodePoint: affectedEnd,
    originalText: affectedText,
    targetTextRevision: "target-revision-5",
    targetContentHash: "target-hash-5",
  },
};

const proposal = {
  id: "proposal-1",
  proposalSchemaVersion: 2,
  qaFindingId: "qa-quantity",
  projectId: "project-1",
  intent,
  affectedReferences: ["PHP 1:5"],
  currentText: "மூன்று",
  proposedText: "எல்லாரும்",
  explanation: "Restores the required quantity.",
  evidenceIds: ["evidence-1"],
  semanticRelationshipIds: ["relationship-1"],
  meaningAssessmentIds: ["meaning-1"],
  locationRelationshipIds: ["location-1"],
  createdBy: "Reviewer",
  createdAt: "2026-09-05T10:00:00Z",
  creationMode: "MACHINE_SUGGESTED",
  policyBinding: {
    confidencePolicyVersion: "confidence-v1",
    calibrationVersion: "calibration-v1",
    auditPolicyVersion: "audit-v1",
  },
  reviewStatus: "AI_PROPOSED",
  lifecycleStatus: "ACTIVE",
  verificationStatus: "NOT_RUN",
  verificationJobIds: [],
  appliedTargetRevision: null,
  appliedBy: null,
  appliedAt: null,
  revision: 1,
  alternatives: [{
    proposedText: "அனைவரும்",
    explanation: "Natural alternative.",
    evidenceIds: ["evidence-1"],
    creationMode: "MACHINE_SUGGESTED",
    providerMetadata: { providerName: "openai", model: "gpt-test" },
  }],
  providerMetadata: { providerName: "openai", model: "gpt-test" },
  warnings: [],
  originalSuggestedText: "எல்லாரும்",
  supersedesProposalId: null,
};

const reviewContext = {
  findingId: "qa-quantity",
  currentTargets: [{
    displayedReference: "PHP 1:5",
    canonicalReferences: ["PHP 1:5"],
    text: targetText,
    targetTextRevision: "target-revision-5",
    targetContentHash: "target-hash-5",
  }],
  candidateSpans: [intent.affectedTargetSpan],
  suggestedIntent: {
    failedDimension: "QUANTITY",
    observedMeaning: "three",
    requiredMeaning: "all",
    affectedSourceSemanticUnitIds: ["source-quantity"],
  },
  sourceEvidence: [{ id: "source-quantity", rawSurface: "πάντας" }],
  resources: [{ id: "evidence-1", kind: "TRANSLATION_NOTE", content: "Refers to all." }],
  location: [{ id: "location-1", displayedReferences: ["PHP 1:5"], quote: "மூன்று" }],
};

const settings = {
  provider: "openai", apiBaseUrl: "", model: "gpt-test", reviewerName: "Reviewer",
  reviewerMode: "advanced", paratextUsername: "", paratextNavigation: false,
  logosNavigation: false, hasApiKey: true, aiUsage: { tokens: 0, estimatedCostUSD: 0 },
};

function event(type: string, snapshot = proposal, revision = 1) {
  return {
    id: `event-${type}-${revision}`, proposalId: snapshot.id, eventType: type,
    actorType: "HUMAN", actorId: "Reviewer", createdAt: "2026-09-05T10:00:00Z",
    baseRevision: revision - 1, newRevision: revision, note: "review note",
    reason: "", providerMetadata: snapshot.providerMetadata,
    proposalSnapshot: snapshot,
  };
}

function eligible() {
  return {
    findingId: "qa-quantity", eligible: true,
    reasons: [{ code: "ELIGIBLE", detail: "Eligible.", entityType: "", entityId: "" }],
    findingRevision: 2, currentTargetContentHash: "target-hash-5",
    displayedReferences: ["PHP 1:5"], engineVersion: "eligibility-v1", existingProposalIds: [],
  };
}

describe("CorrectionReviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.eligibility.mockResolvedValue(eligible());
    api.context.mockResolvedValue(reviewContext);
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [] });
    api.history.mockResolvedValue({ proposalId: "proposal-1", events: [event("CREATED")] });
    api.settings.mockResolvedValue(settings);
    api.create.mockResolvedValue(proposal);
    api.edit.mockResolvedValue({ ...proposal, proposedText: "திருத்திய உரை", revision: 2, creationMode: "MACHINE_SUGGESTED_HUMAN_EDITED" });
    api.reject.mockResolvedValue({ ...proposal, reviewStatus: "HUMAN_REJECTED", lifecycleStatus: "INACTIVE", revision: 2 });
    api.regenerate.mockResolvedValue({ ...proposal, id: "proposal-2", supersedesProposalId: "proposal-1" });
  });

  it("shows backend blocker reasons and no active creation control", async () => {
    api.eligibility.mockResolvedValue({
      ...eligible(), eligible: false,
      reasons: [
        { code: "FINDING_STALE", detail: "The finding is stale.", entityType: "QA_FINDING", entityId: "qa-quantity" },
        { code: "LOCATION_EVIDENCE_UNUSABLE", detail: "Location is ambiguous.", entityType: "LOCATION_RELATIONSHIP", entityId: "location-1" },
      ],
    });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByText("Correction proposal unavailable")).toBeInTheDocument();
    expect(screen.getByText("The finding is stale.")).toBeInTheDocument();
    expect(screen.getByText("Location is ambiguous.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create correction proposal" })).toBeNull();
  });

  it("offers manual and provider paths only for an eligible confirmed finding", async () => {
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Create correction proposal" }));
    expect(screen.getByRole("button", { name: "Write correction manually" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suggest wording" })).toBeInTheDocument();
  });

  it("rechecks backend eligibility when the finding review revision changes", async () => {
    api.eligibility.mockResolvedValueOnce({
      ...eligible(), eligible: false,
      reasons: [{ code: "DISPOSITION_NOT_CONFIRMED", detail: "Confirm the finding first.", entityType: "QA_FINDING", entityId: "qa-quantity" }],
    }).mockResolvedValue(eligible());
    const { component } = render(CorrectionReviewPanel, {
      props: { findingId: "qa-quantity", findingRevision: 1 },
    });
    expect(await screen.findByText("Confirm the finding first.")).toBeInTheDocument();
    await component.$set({ findingRevision: 2 });
    expect(await screen.findByRole("button", { name: "Create correction proposal" })).toBeInTheDocument();
    expect(api.eligibility).toHaveBeenCalledTimes(2);
  });

  it("keeps human-authored correction available without a provider", async () => {
    api.settings.mockResolvedValue({ ...settings, hasApiKey: false });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Create correction proposal" }));
    expect(screen.queryByRole("button", { name: "Suggest wording" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Write correction manually" }));
    await fireEvent.input(screen.getByLabelText("Proposed wording"), { target: { value: "எல்லாரும்" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save proposal" }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      findingId: "qa-quantity", humanProposedText: "எல்லாரும்", requestSuggestion: false,
      intent: expect.objectContaining({ affectedTargetSpan: intent.affectedTargetSpan }),
    })));
  });

  it("renders an optional provider suggestion without treating it as authoritative", async () => {
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Create correction proposal" }));
    await fireEvent.click(screen.getByRole("button", { name: "Suggest wording" }));
    await fireEvent.click(screen.getByRole("button", { name: "Generate suggestion" }));
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ requestSuggestion: true }));
    expect((await screen.findAllByText("எல்லாரும்")).length).toBeGreaterThan(0);
    expect(screen.getByText("Machine-suggested")).toBeInTheDocument();
  });

  it("renders correction intent, exact span, evidence, alternatives and provenance", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect((await screen.findAllByText("எல்லாரும்")).length).toBeGreaterThan(0);
    expect(screen.getByText(`Affected span [${affectedStart}, ${affectedEnd})`)).toBeInTheDocument();
    expect(screen.getByText("three")).toBeInTheDocument();
    expect(screen.getByText("all")).toBeInTheDocument();
    expect(screen.getByText("πάντας")).toBeInTheDocument();
    expect(screen.getByText("Refers to all.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use alternative: அனைவரும்/i })).toBeInTheDocument();
    expect(screen.getByText("Machine-suggested")).toBeInTheDocument();
  });

  it("edits with CAS and preserves the original machine suggestion in view", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Edit proposal" }));
    await fireEvent.input(screen.getByLabelText("Edit proposed wording"), { target: { value: "திருத்திய உரை" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save proposal edit" }));
    expect(api.edit).toHaveBeenCalledWith("proposal-1", expect.objectContaining({
      proposedText: "திருத்திய உரை", expectedProposalRevision: 1,
    }));
    expect(await screen.findByText("Original machine suggestion: எல்லாரும்")).toBeInTheDocument();
  });

  it("reloads and informs on a proposal revision conflict", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    api.edit.mockRejectedValueOnce(new Error("revision_conflict: proposal changed"));
    api.list.mockResolvedValueOnce({ findingId: "qa-quantity", proposals: [proposal] })
      .mockResolvedValue({ findingId: "qa-quantity", proposals: [{ ...proposal, revision: 2 }] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Edit proposal" }));
    await fireEvent.input(screen.getByLabelText("Edit proposed wording"), { target: { value: "new" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save proposal edit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed elsewhere.*reloaded/i);
  });

  it("rejects without deleting wording and retains rejection history", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    api.history.mockResolvedValue({ proposalId: "proposal-1", events: [event("CREATED"), event("REJECTED", proposal, 2)] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.input(await screen.findByLabelText(/Proposal review note/i), { target: { value: "Not natural." } });
    await fireEvent.click(screen.getByRole("button", { name: "Reject proposal" }));
    expect(api.reject).toHaveBeenCalledWith("proposal-1", expect.objectContaining({ note: "Not natural.", expectedProposalRevision: 1 }));
    expect(await screen.findByText("Rejected")).toBeInTheDocument();
    expect(screen.getAllByText("எல்லாரும்").length).toBeGreaterThan(0);
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
  });

  it("regenerates by superseding and retains the prior proposal", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    api.regenerate.mockResolvedValue({ ...proposal, id: "proposal-2", supersedesProposalId: "proposal-1" });
    api.list.mockResolvedValueOnce({ findingId: "qa-quantity", proposals: [proposal] })
      .mockResolvedValue({ findingId: "qa-quantity", proposals: [
        { ...proposal, lifecycleStatus: "SUPERSEDED", revision: 2 },
        { ...proposal, id: "proposal-2", supersedesProposalId: "proposal-1" },
      ] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Generate another suggestion" }));
    expect(api.regenerate).toHaveBeenCalledWith("proposal-1", expect.objectContaining({ expectedProposalRevision: 1 }));
    expect(await screen.findByText(/2 proposals retained/i)).toBeInTheDocument();
  });

  it("makes stale state obvious and disables current actions", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [{ ...proposal, lifecycleStatus: "STALE" }] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByRole("status", { name: "Stale correction proposal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit proposal" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate another suggestion" })).toBeDisabled();
  });

  it("disables an existing proposal when backend eligibility gains a mapping blocker", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    api.eligibility.mockResolvedValue({
      ...eligible(), eligible: false,
      reasons: [{ code: "MAPPING_HUMAN_REJECTED", detail: "A reviewer rejected this location mapping.", entityType: "LOCATION_RELATIONSHIP", entityId: "location-1" }],
    });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByText("Correction unavailable")).toBeInTheDocument();
    expect(screen.getByText(/rejected this location mapping/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit proposal" })).toBeDisabled();
  });

  it("shows a zero-length omission as an insertion point", async () => {
    const insertion = {
      ...proposal,
      currentText: "",
      intent: { ...intent, affectedTargetSpan: { ...intent.affectedTargetSpan, startCodePoint: 7, endCodePoint: 7, originalText: "" } },
    };
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [insertion] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByText("Insertion point [7, 7)")).toBeInTheDocument();
    expect(screen.getByLabelText("Insertion diff")).toHaveTextContent("எல்லாரும்");
  });

  it("keeps a PHP 1:3 source correction grounded at its unambiguous PHP 1:6 target", async () => {
    const crossVerseSpan = {
      ...intent.affectedTargetSpan,
      displayedReference: "PHP 1:6",
      canonicalReferences: ["PHP 1:3"],
    };
    api.list.mockResolvedValue({
      findingId: "qa-quantity",
      proposals: [{ ...proposal, intent: { ...intent, affectedTargetSpan: crossVerseSpan } }],
    });
    api.context.mockResolvedValue({
      ...reviewContext,
      currentTargets: [{ ...reviewContext.currentTargets[0], displayedReference: "PHP 1:6", canonicalReferences: ["PHP 1:3"] }],
      candidateSpans: [crossVerseSpan],
      sourceEvidence: [{ id: "source-quantity", rawSurface: "τῷ θεῷ μου", displayedReferences: ["PHP 1:3"] }],
    });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByText("PHP 1:6")).toBeInTheDocument();
    expect(screen.getByText("τῷ θεῷ μου")).toBeInTheDocument();
    expect(screen.getByText(`Affected span [${affectedStart}, ${affectedEnd})`)).toBeInTheDocument();
  });

  it.each([1366, 820])(
    "keeps actions reachable with long multilingual content at %ipx",
    async (viewportWidth) => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: viewportWidth });
      api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [
        { ...proposal, explanation: "reason ".repeat(300), alternatives: Array.from({ length: 12 }, (_, i) => ({ ...proposal.alternatives[0], proposedText: `option ${i}` })) },
      ] });
      api.context.mockResolvedValue({
        ...reviewContext,
        currentTargets: [{ ...reviewContext.currentTargets[0], text: `${targetText} `.repeat(30) }],
        resources: [{ id: "evidence-1", kind: "TRANSLATION_NOTE", content: "long evidence ".repeat(150) }],
      });
      api.history.mockResolvedValue({
        proposalId: "proposal-1",
        events: Array.from({ length: 30 }, (_, index) => event("EDITED", proposal, index + 1)),
      });
      const { container } = render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
      await screen.findAllByText("எல்லாரும்");
      const panel = container.querySelector("[data-correction-panel]")!;
      expect(panel.querySelector("[data-correction-scroll]")).toBeTruthy();
      expect(panel.querySelector("[data-correction-actions]")).toBeTruthy();
      expect(panel.querySelector("[data-correction-scroll] [data-correction-actions]")).toBeNull();
      expect(screen.getByRole("button", { name: "Edit proposal" })).toBeVisible();
    },
  );

  it("is keyboard operable and exposes no Scripture-changing action", async () => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    const edit = await screen.findByRole("button", { name: "Edit proposal" });
    edit.focus();
    expect(edit).toHaveFocus();
    expect(screen.queryByRole("button", { name: /apply correction|apply to scripture|save to scripture|replace verse/i })).toBeNull();
  });
});

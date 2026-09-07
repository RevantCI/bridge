import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  eligibility: vi.fn(),
  context: vi.fn(),
  list: vi.fn(),
  history: vi.fn(),
  create: vi.fn(),
  edit: vi.fn(),
  reject: vi.fn(),
  regenerate: vi.fn(),
  apply: vi.fn(),
  applicationStatus: vi.fn(),
  reanalyze: vi.fn(),
  analysisStatus: vi.fn(),
  analysisCancel: vi.fn(),
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
    correctionApplyProposal: api.apply,
    correctionGetApplicationStatus: api.applicationStatus,
    correctionReanalyzeAffected: api.reanalyze,
    analysisJobStatus: api.analysisStatus,
    analysisJobCancel: api.analysisCancel,
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
  findingDisplayedReferences: ["PHP 1:5"],
  sourceSemanticReferences: ["PHP 1:5"],
  sourceCanonicalReferences: ["PHP 1:5"],
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

const completedApplication = {
  applicationId: "application-1", proposalId: "proposal-1", findingId: "qa-quantity",
  projectId: "project-1", expectedProposalRevision: 2, expectedFindingRevision: 2,
  targetDisplayedReference: "PHP 1:5", canonicalReferences: ["PHP 1:5"],
  sourceProvenanceReferences: ["PHP 1:3"], expectedTargetRevision: "target-revision-5",
  expectedTargetContentHash: "target-hash-5", expectedStartCodePoint: affectedStart,
  expectedEndCodePoint: affectedEnd, expectedOriginalText: affectedText,
  replacementTextSnapshot: "அனைவரும்", intendedFinalVerseHash: "hash",
  pendingInvalidationId: "pending-1", translationCoreJournalTransactionId: "journal-1",
  actor: { actorType: "HUMAN", actorId: "Reviewer" }, createdAt: "now", updatedAt: "now",
  applicationState: "COMPLETED", stateRevision: 5, completedAt: "now", failureCode: "",
  recoveryMetadata: {}, resultMetadata: { verificationStatus: "PENDING", affectedAnalysisStarted: false },
};

function analysisJob(overrides: Record<string, unknown> = {}) {
  return {
    jobId: "analysis-1", projectId: "project-1", book: "PHP",
    requestedScope: { kind: "AFFECTED" }, rangeKey: "PHP 1:3..PHP 1:6",
    displayedReferences: ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
    canonicalReferences: ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
    targetRevision: "current", targetContentHash: "current-hash", targetHashes: {},
    sourceResourceHash: "source-hash", analysisFingerprint: "analysis-fingerprint",
    policyVersions: {}, revision: 1, createdAt: "now", startedAt: "now", completedAt: null,
    currentStage: "TARGET_INVENTORY", overallStatus: "RUNNING",
    stageStatuses: {}, stageProgress: { completedStages: 1, totalStages: 5 },
    reusedRunIds: ["source-run"], createdRunIds: [], warnings: [], failures: [],
    cancellationRequested: false,
    providerCapability: { semanticRetrieval: "FULL", multilingualEmbeddingProvider: "AVAILABLE", providerId: "test", providerVersion: "1", modelHash: "test", fixtureProvider: false },
    timings: {}, qaFindingCount: null, searchIncomplete: false, ...overrides,
  };
}

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
    api.apply.mockResolvedValue({
      applicationId: "application-1", proposalId: "proposal-1", findingId: "qa-quantity",
      projectId: "project-1", expectedProposalRevision: 2, expectedFindingRevision: 2,
      targetDisplayedReference: "PHP 1:5", canonicalReferences: ["PHP 1:5"],
      sourceProvenanceReferences: [], expectedTargetRevision: "target-revision-5",
      expectedTargetContentHash: "target-hash-5", expectedStartCodePoint: affectedStart,
      expectedEndCodePoint: affectedEnd, expectedOriginalText: affectedText,
      replacementTextSnapshot: "அனைவரும்", intendedFinalVerseHash: "hash",
      pendingInvalidationId: "pending-1", translationCoreJournalTransactionId: "journal-1",
      actor: { actorType: "HUMAN", actorId: "Reviewer" }, createdAt: "now", updatedAt: "now",
      applicationState: "COMPLETED", stateRevision: 5, completedAt: "now", failureCode: "",
      recoveryMetadata: {}, resultMetadata: { verificationStatus: "PENDING", affectedAnalysisStarted: false },
    });
    api.applicationStatus.mockResolvedValue(completedApplication);
    api.analysisStatus.mockResolvedValue(analysisJob());
    api.analysisCancel.mockResolvedValue(analysisJob({ overallStatus: "CANCELLED", currentStage: "", completedAt: "now" }));
    api.reanalyze.mockResolvedValue({
      applicationId: "application-1", analysisJobId: "analysis-1",
      resolvedSourceReferences: ["PHP 1:3"], resolvedTargetReferences: ["PHP 1:6"],
      resolvedStructuralRange: {
        startReference: "PHP 1:3", endReference: "PHP 1:6",
        displayedReferences: ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
        canonicalReferences: ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
      },
      jobState: "RUNNING", job: analysisJob(),
    });
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
      canonicalReferences: ["PHP 1:6"],
    };
    api.list.mockResolvedValue({
      findingId: "qa-quantity",
      proposals: [{
        ...proposal,
        affectedReferences: ["PHP 1:6"],
        reviewStatus: "HUMAN_MODIFIED",
        revision: 2,
        intent: {
          ...intent,
          affectedSourceSemanticUnitIds: ["source-quantity"],
          affectedTargetSpan: crossVerseSpan,
        },
      }],
    });
    api.context.mockResolvedValue({
      ...reviewContext,
      findingDisplayedReferences: ["PHP 1:6"],
      sourceSemanticReferences: ["PHP 1:3"],
      sourceCanonicalReferences: ["PHP 1:3"],
      currentTargets: [{ ...reviewContext.currentTargets[0], displayedReference: "PHP 1:6", canonicalReferences: ["PHP 1:6"] }],
      candidateSpans: [crossVerseSpan],
      sourceEvidence: [{ id: "source-quantity", rawSurface: "τῷ θεῷ μου", displayedReferences: ["PHP 1:3"] }],
    });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByText("PHP 1:6")).toBeInTheDocument();
    expect(screen.getByText("τῷ θεῷ μου")).toBeInTheDocument();
    expect(screen.getByText(`Affected span [${affectedStart}, ${affectedEnd})`)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Review application" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm correction application" });
    expect(within(dialog).getByText("Source semantic reference:").closest("p")).toHaveTextContent("PHP 1:3");
    expect(within(dialog).getByText("Finding display reference:").closest("p")).toHaveTextContent("PHP 1:6");
    expect(within(dialog).getByText("Target verse:").closest("p")).toHaveTextContent("PHP 1:6");
    expect(within(dialog).getByText("Affected span:").closest("p")).toHaveTextContent(
      `[${affectedStart}, ${affectedEnd})`,
    );
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

  it("requires a reviewed proposal and a distinct confirmation before applying", async () => {
    const reviewed = { ...proposal, reviewStatus: "HUMAN_MODIFIED", revision: 2 };
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [reviewed] });
    api.list.mockResolvedValueOnce({ findingId: "qa-quantity", proposals: [reviewed] })
      .mockResolvedValue({ findingId: "qa-quantity", proposals: [{ ...reviewed, lifecycleStatus: "STALE", verificationStatus: "PENDING", revision: 4 }] });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(screen.queryByRole("button", { name: "Apply correction" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-analyze affected passage" })).toBeNull();
    await fireEvent.click(await screen.findByRole("button", { name: "Review application" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm correction application" });
    expect(within(dialog).getByText("CURRENT")).toBeInTheDocument();
    expect(within(dialog).getByText("PROPOSED FINAL")).toBeInTheDocument();
    expect(within(dialog).getByText(/Word Alignment becomes invalid\/reviewable/i)).toBeInTheDocument();
    await fireEvent.click(within(dialog).getByRole("button", { name: "Apply correction" }));
    await waitFor(() => expect(api.apply).toHaveBeenCalledWith(expect.objectContaining({
      proposalId: "proposal-1", expectedProposalRevision: 2,
      findingId: "qa-quantity", expectedFindingRevision: 2,
      actor: { actorType: "HUMAN", actorId: "Reviewer" },
    })));
    expect(await screen.findByText("Scripture updated. Semantic verification is pending.")).toBeInTheDocument();
  });

  it("opens Review application by pointer with a mixed-build review context", async () => {
    const reviewed = { ...proposal, reviewStatus: "HUMAN_MODIFIED", revision: 2 };
    const {
      findingDisplayedReferences: _findingReferences,
      sourceSemanticReferences: _sourceReferences,
      sourceCanonicalReferences: _sourceCanonicalReferences,
      ...legacyContext
    } = reviewContext;
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [reviewed] });
    api.context.mockResolvedValue({
      ...legacyContext,
      sourceEvidence: [{
        id: "source-quantity", rawSurface: "τῷ θεῷ μου",
        displayedReferences: ["PHP 1:3"], canonicalReferences: ["PHP 1:3"],
      }],
    });
    const user = userEvent.setup();
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });

    const button = await screen.findByRole("button", { name: "Review application" });
    expect(button).toBeEnabled();
    expect(getComputedStyle(button).pointerEvents).not.toBe("none");
    expect(getComputedStyle(button.closest("[data-correction-actions]")! as Element).pointerEvents).not.toBe("none");
    await user.click(button);

    const dialog = screen.getByRole("dialog", { name: "Confirm correction application" });
    expect(within(dialog).getByText("Source semantic reference:").closest("p")).toHaveTextContent("PHP 1:3");
    expect(api.apply).not.toHaveBeenCalled();
  });

  it.each(["{Enter}", " "])(
    "opens Review application by keyboard activation %s",
    async (key) => {
      const reviewed = { ...proposal, reviewStatus: "HUMAN_MODIFIED", revision: 2 };
      api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [reviewed] });
      const user = userEvent.setup();
      render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });

      const button = await screen.findByRole("button", { name: "Review application" });
      button.focus();
      expect(button).toHaveFocus();
      await user.keyboard(key);

      expect(screen.getByRole("dialog", { name: "Confirm correction application" })).toBeInTheDocument();
      expect(api.apply).not.toHaveBeenCalled();
    },
  );

  it("starts the backend-resolved affected analysis only after completed Apply", async () => {
    const applied = {
      ...proposal, lifecycleStatus: "STALE", reviewStatus: "HUMAN_APPROVED",
      verificationStatus: "PENDING", revision: 3,
    };
    api.list.mockResolvedValue({
      findingId: "qa-quantity", proposals: [applied], applications: [completedApplication],
    });
    const user = userEvent.setup();
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });

    const button = await screen.findByRole("button", { name: "Re-analyze affected passage" });
    expect(screen.getByText("Correction application").closest("dl")).toHaveTextContent("COMPLETED");
    expect(screen.getByText("Semantic verification").closest("dl")).toHaveTextContent("PENDING");
    await user.click(button);

    await waitFor(() => expect(api.reanalyze).toHaveBeenCalledTimes(1));
    expect(api.reanalyze).toHaveBeenCalledWith({
      applicationId: "application-1", requestedBy: "Reviewer", retry: false,
    });
    expect(screen.getByText("Building target semantic inventory…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel affected analysis" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-analyze affected passage" })).toBeNull();
    expect(screen.queryByText("CORRECTED")).toBeNull();
  });

  it("emits a QA refresh only after affected analysis completes", async () => {
    const applied = {
      ...proposal, lifecycleStatus: "STALE", reviewStatus: "HUMAN_APPROVED",
      verificationStatus: "PENDING", revision: 3,
    };
    api.list.mockResolvedValue({
      findingId: "qa-quantity", proposals: [applied], applications: [completedApplication],
    });
    api.analysisStatus.mockResolvedValue(analysisJob({
      overallStatus: "COMPLETED", currentStage: "", completedAt: "now",
    }));
    const refreshed = vi.fn();
    const { component } = render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    component.$on("reanalyzed", (event) => refreshed(event.detail));

    await fireEvent.click(await screen.findByRole("button", { name: "Re-analyze affected passage" }));

    await waitFor(() => expect(refreshed).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(refreshed.mock.calls[0][0].result.jobState).toBe("COMPLETED");
    expect(screen.getByText(/Current semantic evidence has been refreshed/i)).toBeInTheDocument();
    expect(screen.getByText("Semantic verification").closest("dl")).toHaveTextContent("PENDING");
    expect(screen.queryByText("CORRECTED")).toBeNull();
  });

  it.each([
    ["FAILED", "Retry affected analysis"],
    ["CANCELLED", "Retry affected analysis"],
    ["SEARCH_INCOMPLETE", "Retry affected analysis"],
    ["COMPLETED", ""],
  ])("restores affected analysis state %s without changing verification", async (state, action) => {
    const persistedApplication = {
      ...completedApplication,
      resultMetadata: {
        verificationStatus: "PENDING", affectedAnalysisStarted: true,
        affectedAnalysisJobId: "analysis-1",
        affectedAnalysisAttempts: [{ analysisJobId: "analysis-1" }],
      },
    };
    const applied = {
      ...proposal, lifecycleStatus: "STALE", reviewStatus: "HUMAN_APPROVED",
      verificationStatus: "PENDING", revision: 3,
    };
    const overallStatus = state === "SEARCH_INCOMPLETE" ? "COMPLETED_WITH_WARNINGS" : state;
    api.analysisStatus.mockResolvedValue(analysisJob({
      overallStatus, searchIncomplete: state === "SEARCH_INCOMPLETE",
      currentStage: "", completedAt: "now",
    }));
    api.list.mockResolvedValue({
      findingId: "qa-quantity", proposals: [applied], applications: [persistedApplication],
    });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });

    expect(await screen.findByText("Semantic verification")).toBeInTheDocument();
    expect(screen.getByText("Affected analysis").closest("dl")).toHaveTextContent(state);
    if (action) expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
    else expect(screen.queryByRole("button", { name: /affected analysis/i })).toBeNull();
    expect(screen.queryByText("CORRECTED")).toBeNull();
  });

  it.each([
    [["s1"], ["t1"], "1 → 1"],
    [["s1"], ["t1", "t2"], "1 → many"],
    [["s1", "s2"], ["t1"], "many → 1"],
    [["s1", "s2"], ["t1", "t2"], "many → many"],
    [["s1"], [], "1 → null"],
    [[], ["t1"], "null → 1"],
  ])("shows grouped relationship cardinality %s to %s", async (sourceIds, targetIds, expected) => {
    api.list.mockResolvedValue({ findingId: "qa-quantity", proposals: [proposal], applications: [] });
    api.context.mockResolvedValue({
      ...reviewContext,
      sourceSemanticReferences: ["PHP 1:3"],
      location: [{
        id: "location-cardinality", sourceSemanticUnitIds: sourceIds,
        targetTokenInstanceIds: targetIds, displayedReferences: ["PHP 1:6"],
        realization: targetIds.length ? "LEXICALLY_REALIZED" : "NOT_LOCATED",
        properties: ["CROSS_VERSE", "REORDERED"],
      }],
      sourceEvidence: sourceIds.map((id) => ({ id, rawSurface: id, tokenInstanceIds: [id] })),
    });
    render(CorrectionReviewPanel, { props: { findingId: "qa-quantity" } });
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.getByText("CROSS_VERSE · REORDERED")).toBeInTheDocument();
    if (expected === "1 → null") {
      expect(screen.getByText("No realization located · NOT_LOCATED")).toBeInTheDocument();
      expect(screen.queryByText(/^Omission$/i)).toBeNull();
    }
    if (expected === "null → 1") expect(screen.queryByText(/^Addition$/i)).toBeNull();
  });
});

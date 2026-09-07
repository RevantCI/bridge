import { bridge } from "./api/bridgeClient";
import type {
  CorrectionApplicationIntent,
  CorrectionEligibility,
  CorrectionProposal,
} from "./types/correctionReview";

export interface ApplicableCorrection {
  eligibility: CorrectionEligibility;
  proposal: CorrectionProposal | null;
  actorId: string;
  disabledReason: string;
}

export function newCorrectionApplicationId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `correction-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function latestActiveProposal(proposals: CorrectionProposal[]): CorrectionProposal | null {
  return [...proposals].reverse().find((proposal) => proposal.lifecycleStatus === "ACTIVE") ?? null;
}

/** Resolve the same guards used by CorrectionReviewPanel before enabling application. */
export async function getApplicableCorrection(findingId: string): Promise<ApplicableCorrection> {
  const [eligibility, listed, settings] = await Promise.all([
    bridge.correctionGetEligibility(findingId),
    bridge.correctionListForFinding(findingId),
    bridge.getSettings(),
  ]);
  const proposal = latestActiveProposal(listed.proposals ?? []);
  let disabledReason = "";
  if (!proposal) disabledReason = "No proposed fix is available for this finding.";
  else if (listed.correctionWritesBlocked) disabledReason = "Correction writes are currently blocked.";
  else {
    const blocking = (eligibility.reasons ?? []).filter((reason) =>
      reason.code !== "ELIGIBLE"
      && !(reason.code === "CONFLICTING_CORRECTION"
        && (listed.proposals ?? []).some((item) => item.id === reason.entityId)),
    );
    if (blocking.length) disabledReason = blocking[0].detail;
    else if (!["HUMAN_APPROVED", "HUMAN_MODIFIED"].includes(proposal.reviewStatus)) {
      disabledReason = "Review the proposed wording before applying it.";
    } else if (proposal.verificationStatus !== "NOT_RUN") {
      disabledReason = "This proposal has already been applied or verified.";
    }
  }
  return {
    eligibility,
    proposal,
    actorId: settings.reviewerName || "human",
    disabledReason,
  };
}

/** The single frontend entry point for the guarded correction writer. */
export function applyCorrectionProposal(options: {
  findingId: string;
  findingRevision: number;
  proposal: CorrectionProposal;
  actorId: string;
  applicationId?: string;
}): Promise<CorrectionApplicationIntent> {
  return bridge.correctionApplyProposal({
    proposalId: options.proposal.id,
    expectedProposalRevision: options.proposal.revision,
    findingId: options.findingId,
    expectedFindingRevision: options.findingRevision,
    applicationId: options.applicationId || newCorrectionApplicationId(),
    actor: { actorType: "HUMAN", actorId: options.actorId || "human" },
  });
}

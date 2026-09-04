import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";

const { getSettings, getNavigationStatus } = vi.hoisted(() => ({
  getSettings: vi.fn(),
  getNavigationStatus: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    getSettings,
    navigationStatus: getNavigationStatus,
    setSettings: vi.fn(),
  },
}));

import SettingsModal from "../SettingsModal.svelte";

const target = {
  enabled: true,
  checking: true,
  connected: false,
  reference: "",
  error: "",
  checkedAt: 1,
};

function navigationState(
  paratextOverrides: Record<string, unknown> = {},
  logosOverrides: Record<string, unknown> = {},
) {
  return {
    enabled: true,
    ownsNavigation: true,
    ownerConflict: false,
    currentReference: "PHP 1:5",
    currentOrigin: "bridge",
    candidate: null,
    paratext: { ...target, ...paratextOverrides },
    logos: { ...target, ...logosOverrides },
  };
}

describe("SettingsModal connections", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSettings.mockResolvedValue({
      provider: "openai",
      apiBaseUrl: "",
      model: "gpt-5.6",
      hasApiKey: false,
      reviewerMode: "basic",
      paratextNavigation: true,
      logosNavigation: true,
    });
  });

  it("keeps the last connected status visible during a background refresh", async () => {
    getNavigationStatus.mockResolvedValue(navigationState({
      connected: true,
      project_name: "IRVTam",
      reference: "PHP 1:5",
    }));

    const { container } = render(SettingsModal, { props: { initialPane: "connections", onClose: vi.fn() } });

    await waitFor(() => {
      expect(container.querySelector(".connection-detail")).toHaveTextContent(/Connected.*IRVTam.*PHP 1:5/);
    });
  });

  it("keeps an actionable connector error visible during a background refresh", async () => {
    getNavigationStatus.mockResolvedValue(navigationState({}, { error: "Logos COM registration needs repair." }));

    render(SettingsModal, { props: { initialPane: "connections", onClose: vi.fn() } });

    expect(await screen.findByText("Logos COM registration needs repair.")).toBeInTheDocument();
    expect(screen.getAllByText("Checking…")).toHaveLength(1);
  });
});

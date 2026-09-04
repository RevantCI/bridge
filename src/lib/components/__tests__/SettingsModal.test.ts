import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { getSettings, getNavigationStatus, setSettings } = vi.hoisted(() => ({
  getSettings: vi.fn(),
  getNavigationStatus: vi.fn(),
  setSettings: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    getSettings,
    navigationStatus: getNavigationStatus,
    setSettings,
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

describe("SettingsModal manual override", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getNavigationStatus.mockResolvedValue(navigationState());
    setSettings.mockImplementation(async (params: Record<string, unknown>) => ({
      ...params, hasApiKey: false,
    }));
    getSettings.mockResolvedValue({
      provider: "openai",
      apiBaseUrl: "",
      model: "gpt-5.6",
      hasApiKey: false,
      reviewerMode: "basic",
      paratextNavigation: false,
      logosNavigation: false,
    });
  });

  it("offers manual override as a single checkbox, not a mode choice", async () => {
    const { container } = render(SettingsModal, { props: { initialPane: "quality", onClose: vi.fn() } });

    const checkbox = await screen.findByRole("checkbox", { name: /Allow manual override/ });
    expect(checkbox).not.toBeChecked();
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(0);
    expect(screen.queryByText("Basic")).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced")).not.toBeInTheDocument();
  });

  it("reflects a stored advanced setting as override enabled", async () => {
    getSettings.mockResolvedValue({
      provider: "openai", apiBaseUrl: "", model: "gpt-5.6", hasApiKey: false,
      reviewerMode: "advanced", paratextNavigation: false, logosNavigation: false,
    });
    render(SettingsModal, { props: { initialPane: "quality", onClose: vi.fn() } });

    expect(await screen.findByRole("checkbox", { name: /Allow manual override/ })).toBeChecked();
  });

  it("saves the checkbox back as the stored basic/advanced value", async () => {
    render(SettingsModal, { props: { initialPane: "quality", onClose: vi.fn() } });
    const checkbox = await screen.findByRole("checkbox", { name: /Allow manual override/ });

    await fireEvent.click(checkbox);
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(setSettings).toHaveBeenCalledWith(
      expect.objectContaining({ reviewerMode: "advanced" }),
    ));
  });
});

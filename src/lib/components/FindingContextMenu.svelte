<script lang="ts">
  import { createEventDispatcher, onMount, tick } from "svelte";

  interface FindingMenuAction {
    id: string;
    label: string;
    disabled?: boolean;
    title?: string;
    separatorBefore?: boolean;
  }

  export let x = 0;
  export let y = 0;
  export let findingLabel = "Finding actions";
  export let actions: FindingMenuAction[] = [];

  const dispatch = createEventDispatcher<{
    action: { id: string };
    close: void;
  }>();

  const EDGE_GAP = 8;
  let menu: HTMLDivElement | null = null;
  let left = x;
  let top = y;
  let previousFocus: HTMLElement | null = null;

  function close(restoreFocus = false): void {
    if (restoreFocus && previousFocus?.isConnected) previousFocus.focus();
    dispatch("close");
  }

  function choose(action: FindingMenuAction): void {
    if (action.disabled) return;
    dispatch("action", { id: action.id });
  }

  function enabledItems(): HTMLButtonElement[] {
    return menu
      ? Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'))
      : [];
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
      return;
    }
    if (event.key === "Tab") {
      close();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = enabledItems();
    if (!items.length) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }

  function onOutsidePointer(event: PointerEvent): void {
    if (menu && !menu.contains(event.target as Node)) close();
  }

  function positionInsideViewport(): void {
    if (!menu) return;
    const rect = menu.getBoundingClientRect();
    left = Math.max(EDGE_GAP, Math.min(x, window.innerWidth - rect.width - EDGE_GAP));
    top = Math.max(EDGE_GAP, Math.min(y, window.innerHeight - rect.height - EDGE_GAP));
  }

  onMount(() => {
    previousFocus = document.activeElement as HTMLElement | null;
    const start = async (): Promise<void> => {
      await tick();
      positionInsideViewport();
      enabledItems()[0]?.focus();
    };
    void start();
    window.addEventListener("pointerdown", onOutsidePointer, true);
    window.addEventListener("resize", positionInsideViewport);
    return () => {
      window.removeEventListener("pointerdown", onOutsidePointer, true);
      window.removeEventListener("resize", positionInsideViewport);
    };
  });
</script>

<div
  bind:this={menu}
  class="finding-menu"
  role="menu"
  tabindex="-1"
  aria-label={findingLabel}
  style:left="{left}px"
  style:top="{top}px"
  on:keydown={onKeydown}
  on:contextmenu|preventDefault
>
  {#each actions as action (action.id)}
    {#if action.separatorBefore}<div class="separator" role="separator"></div>{/if}
    <button
      type="button"
      role="menuitem"
      disabled={action.disabled}
      title={action.title}
      on:click={() => choose(action)}
    >{action.label}</button>
  {/each}
</div>

<style>
  .finding-menu {
    position: fixed;
    z-index: 10000;
    box-sizing: border-box;
    min-width: 14rem;
    max-width: min(22rem, calc(100vw - 16px));
    padding: 0.3rem;
    border: 1px solid var(--border-strong, #cbd5e1);
    border-radius: 7px;
    background: var(--surface, #fff);
    color: var(--text, #111827);
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.22);
  }

  button {
    display: block;
    width: 100%;
    padding: 0.45rem 0.6rem;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: var(--fs-md);
    text-align: left;
    cursor: pointer;
  }

  button:hover:not(:disabled), button:focus-visible:not(:disabled) {
    background: var(--accent-bg, #eff6ff);
    outline: none;
  }

  button:disabled {
    color: var(--text-3, #94a3b8);
    cursor: not-allowed;
  }

  .separator {
    height: 1px;
    margin: 0.25rem 0.15rem;
    background: var(--border, #e5e7eb);
  }
</style>

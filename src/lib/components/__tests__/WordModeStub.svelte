<script lang="ts">
  /**
   * Stands in for AlignmentModal in shell tests.
   *
   * The real word aligner reaches for Tauri and project state; the shell only
   * needs to prove it mounts that component rather than reimplementing it,
   * so this records the mount and the props it was handed.
   */
  export let chapter: string = "";
  export let verse: string = "";
  export let onClose: () => void = () => {};
</script>

<div data-testid="word-alignment-editor" data-chapter={chapter} data-verse={verse}>
  <button type="button" on:click={onClose}>Close word alignment</button>
</div>

<script>
  import DraftBoard from './DraftBoard.svelte';
  import SeasonTracker from './SeasonTracker.svelte';

  const TABS = [
    { id: 'season', label: 'Season', subtitle: 'Live standings, projections, and title odds.' },
    { id: 'draft', label: 'Draft board', subtitle: 'Auction inflation and the fair-value board.' },
  ];

  // The draft is over, so the season view is the one people open the app for.
  let active = $state('season');
  const current = $derived(TABS.find((t) => t.id === active));
</script>

<header>
  <h1>Endzone</h1>
  <nav class="tabs">
    {#each TABS as tab (tab.id)}
      <button
        type="button"
        class="tab"
        class:active={active === tab.id}
        aria-current={active === tab.id ? 'page' : undefined}
        onclick={() => (active = tab.id)}
      >{tab.label}</button>
    {/each}
  </nav>
</header>
<p class="subtitle">{current.subtitle}</p>

{#if active === 'season'}
  <SeasonTracker />
{:else}
  <DraftBoard />
{/if}

<style>
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  .tabs {
    display: flex;
    gap: 4px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 3px;
  }

  .tab {
    background: transparent;
    color: var(--muted);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 0.9rem;
  }

  .tab.active {
    background: var(--accent);
    color: white;
  }
</style>

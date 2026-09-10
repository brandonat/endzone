<script>
  import { onMount } from 'svelte';

  let market = $state(null);
  let loading = $state(true);
  let loadError = $state('');

  let team = $state('');
  let price = $state('');
  let managerId = $state('');
  let submitting = $state(false);
  let formError = $state('');

  const inflationPct = $derived(market ? market.inflation_factor * 100 : 100);
  const undraftedTeams = $derived(market ? market.teams.filter((t) => !t.drafted) : []);

  async function fetchTeams() {
    loadError = '';
    try {
      const res = await fetch('/api/teams');
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      market = await res.json();
      if (!managerId && market.managers.length) managerId = market.managers[0].id;
    } catch (err) {
      loadError = `Could not reach the draft server: ${err.message}`;
    } finally {
      loading = false;
    }
  }

  async function submitPick(event) {
    event.preventDefault();
    formError = '';

    if (!team || !price || !managerId) {
      formError = 'Team, sale price, and manager are all required.';
      return;
    }

    submitting = true;
    try {
      const res = await fetch('/api/pick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team, price: Number(price), manager_id: managerId }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Server responded ${res.status}`);

      market = body.market;
      team = '';
      price = '';
    } catch (err) {
      formError = err.message;
    } finally {
      submitting = false;
    }
  }

  async function renameManager(id, name) {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const res = await fetch(`/api/managers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Server responded ${res.status}`);
      market = body.market;
    } catch (err) {
      loadError = `Could not rename manager: ${err.message}`;
    }
  }

  onMount(fetchTeams);
</script>

<h1>Endzone Draft Board</h1>
<p class="subtitle">Live auction inflation and fair-value board.</p>

{#if loadError}
  <div class="card error">{loadError}</div>
{/if}

{#if market}
  <div class="layout">
    <aside class="sidebar">
      <div class="card">
        <div class="inflation" class:up={market.inflation_factor > 1} class:down={market.inflation_factor < 1}>
          <span class="value">{inflationPct.toFixed(1)}%</span>
          <span class="label">market inflation</span>
        </div>
        <div class="budget-row">
          <span>Spent: ${market.total_spent.toFixed(1)}</span>
          <span>Remaining: ${market.remaining_budget.toFixed(1)}</span>
        </div>
      </div>

      <div class="card">
        <h2>Record a pick</h2>
        <form class="pick-form" onsubmit={submitPick}>
          <div class="field">
            <label for="team">Team</label>
            <select id="team" bind:value={team} disabled={submitting}>
              <option value="" disabled>Select a team</option>
              {#each undraftedTeams as t (t.team)}
                <option value={t.team}>{t.team}</option>
              {/each}
            </select>
          </div>
          <div class="field">
            <label for="price">Sale price</label>
            <input id="price" type="number" min="0" step="0.1" placeholder="e.g. 42.5" bind:value={price} disabled={submitting} />
          </div>
          <div class="field">
            <label for="manager">Manager</label>
            <select id="manager" bind:value={managerId} disabled={submitting}>
              {#each market.managers as m (m.id)}
                <option value={m.id}>{m.name} (${m.remaining_budget.toFixed(0)} left)</option>
              {/each}
            </select>
          </div>
          <button type="submit" disabled={submitting}>{submitting ? 'Saving…' : 'Record pick'}</button>
        </form>
        {#if formError}
          <div class="error">{formError}</div>
        {/if}
      </div>

      <div class="card">
        <h2>Managers</h2>
        <ul class="managers">
          {#each market.managers as m (m.id)}
            <li class="manager">
              <div class="manager-head">
                <input
                  class="manager-name"
                  value={m.name}
                  onblur={(e) => renameManager(m.id, e.currentTarget.value)}
                  onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                />
                <span class="manager-budget">${m.remaining_budget.toFixed(0)} left</span>
              </div>
              {#if m.teams.length}
                <ul class="manager-teams">
                  {#each m.teams as t (t.team)}
                    <li><span class="team-tag">{t.team}</span><span class="team-price">${t.price.toFixed(1)}</span></li>
                  {/each}
                </ul>
              {:else}
                <p class="empty small">No teams yet.</p>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    </aside>

    <main class="board">
      <div class="card">
        <h2>Fair value board</h2>
        <table>
          <thead>
            <tr>
              <th>Team</th>
              <th class="num">Fair value</th>
              <th class="num">Adjusted value</th>
              <th>Owner</th>
            </tr>
          </thead>
          <tbody>
            {#each market.teams as t (t.team)}
              {@const delta = t.drafted ? 0 : t.adjusted_value - t.baseline_value}
              <tr class:drafted={t.drafted}>
                <td>{t.team}</td>
                <td class="num">${t.baseline_value.toFixed(1)}</td>
                <td class="num delta" class:up={delta > 0} class:down={delta < 0}>
                  {t.drafted ? '—' : `$${t.adjusted_value.toFixed(1)}`}
                </td>
                <td class="owner">{t.drafted ? `${t.manager_name} · $${t.price.toFixed(1)}` : '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </main>
  </div>
{:else if loading}
  <p class="empty">Loading draft board…</p>
{/if}

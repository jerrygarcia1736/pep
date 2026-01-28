/* Peptide Tracker - UI Enhancements
 * Dashboard: Age Slider + Goals toggles + Recommendations render
 * Safe to include on every page.
 */

(function () {
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  // Debounce helper
  function debounce(fn, wait) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  // ---------------- Dashboard recommendations ----------------
  function getSelectedGoals() {
    const goals = qsa('.goal-toggle:checked').map(el => el.value).filter(Boolean);
    return goals;
  }

  function setRecoStatus(text, isError) {
    const el = qs('#recoStatus');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('text-danger', !!isError);
  }

  function renderReco(items) {
    const list = qs('#recoList');
    const btns = qs('#recoButtons');
    if (!list) return;

    list.innerHTML = '';
    if (btns) btns.innerHTML = '';

    if (!items || !items.length) {
      setRecoStatus('No matches', false);
      list.innerHTML = '<div class="text-muted small mt-2">No recommendations yet (add more peptide notes/benefits text).</div>';
      return;
    }

    setRecoStatus('Updated', false);

    // List items
    items.slice(0, 6).forEach((it) => {
      const id = it.id;
      const title = it.common_name ? `${it.name} (${it.common_name})` : it.name;
      const reason = it.reason || 'Based on age/goals + peptide notes/benefits text';
      const img = it.image_url;

      const a = document.createElement('a');
      a.className = 'list-group-item list-group-item-action d-flex gap-3 align-items-start reco-item';
      a.href = `/peptides/${id}`;

      a.innerHTML = `
        ${img ? `<img src="${img}" loading="lazy" class="reco-thumb" alt="${it.name}">` : `<div class="reco-thumb placeholder"></div>`}
        <div class="flex-grow-1">
          <div class="d-flex justify-content-between align-items-start">
            <div class="fw-semibold">${title}</div>
            <span class="badge bg-secondary-subtle text-secondary border">${Math.round(it.score || 0)}</span>
          </div>
          <div class="small text-muted mt-1">${reason}</div>
          <div class="mt-2 d-flex gap-2 flex-wrap">
            <span class="badge text-bg-light border">${(it.category || 'General')}</span>
            ${(it.goals_matched || []).slice(0,3).map(g => `<span class="badge text-bg-light border">${g}</span>`).join('')}
          </div>
        </div>
      `;
      list.appendChild(a);

      // Quick buttons
      if (btns) {
        const b = document.createElement('a');
        b.href = `/peptides/${id}`;
        b.className = 'btn btn-sm btn-outline-primary reco-chip';
        b.textContent = it.name;
        btns.appendChild(b);
      }
    });
  }

  async function fetchRecommendations(age, goals) {
    const params = new URLSearchParams();
    if (age) params.set('age', String(age));
    if (goals && goals.length) params.set('goals', goals.join(','));

    setRecoStatus('Loading…', false);

    const res = await fetch(`/api/recommendations?${params.toString()}`, { headers: { 'Accept': 'application/json' }});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  }

  function initDashboardReco() {
    const slider = qs('#ageSlider');
    const agePill = qs('#agePill');
    const list = qs('#recoList');
    if (!slider || !list) return; // not on dashboard

    const updateAgeUI = (v) => { if (agePill) agePill.textContent = String(v); };

    const load = debounce(async () => {
      try {
        const age = parseInt(slider.value || '35', 10);
        const goals = getSelectedGoals();
        updateAgeUI(age);
        const data = await fetchRecommendations(age, goals);
        renderReco(data.items || []);
      } catch (e) {
        console.error('Reco error', e);
        setRecoStatus('Error', true);
        const list = qs('#recoList');
        if (list) list.innerHTML = '<div class="text-danger small mt-2">Could not load recommendations.</div>';
      }
    }, 250);

    slider.addEventListener('input', () => { updateAgeUI(slider.value); load(); });
    qsa('.goal-toggle').forEach(el => el.addEventListener('change', load));

    // Initial load
    updateAgeUI(slider.value || 35);
    load();
  }

  document.addEventListener('DOMContentLoaded', initDashboardReco);
})();

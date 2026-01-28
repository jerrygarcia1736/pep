// Lazy-load images + Age/Goals recommendations
(function () {
  // --- lazy images ---
  const lazyImgs = document.querySelectorAll('img[data-src]');
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        const img = e.target;
        img.src = img.dataset.src;
        img.removeAttribute('data-src');
        obs.unobserve(img);
      });
    }, { rootMargin: '200px' });
    lazyImgs.forEach(img => io.observe(img));
  } else {
    lazyImgs.forEach(img => { img.src = img.dataset.src; img.removeAttribute('data-src'); });
  }

  // --- dashboard recommendations widget ---
  const slider = document.getElementById('ageSlider');
  const agePill = document.getElementById('ageValuePill');
  const recList = document.getElementById('recommendationsList');
  const recError = document.getElementById('recommendationsError');

  function selectedGoals() {
    const checks = document.querySelectorAll('input[name="goalToggle"]:checked');
    return Array.from(checks).map(c => c.value).join(',');
  }

  async function loadRecs() {
    if (!slider || !recList) return;

    const age = parseInt(slider.value || '35', 10);
    if (agePill) agePill.textContent = String(age);

    recError && (recError.textContent = '');
    recList.innerHTML = '<li class="list-group-item text-muted">Loading…</li>';

    const goals = selectedGoals();

    try {
      const url = `/api/recommendations?age=${encodeURIComponent(age)}&goals=${encodeURIComponent(goals)}`;
      const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const items = (data.items || []);
      if (!items.length) {
        recList.innerHTML = '<li class="list-group-item text-muted">No suggestions found yet.</li>';
        return;
      }

      recList.innerHTML = '';
      items.forEach(it => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center';
        const name = document.createElement('a');
        name.href = `/peptides/${it.id}`;
        name.textContent = it.common_name ? `${it.name} (${it.common_name})` : it.name;

        const score = document.createElement('span');
        score.className = 'badge bg-secondary badge-pill';
        score.textContent = `score ${it.score}`;

        li.appendChild(name);
        li.appendChild(score);
        recList.appendChild(li);
      });
    } catch (e) {
      recList.innerHTML = '';
      if (recError) recError.textContent = 'Could not load recommendations.';
      console.error(e);
    }
  }

  if (slider) {
    slider.addEventListener('input', loadRecs);
  }
  const goalToggles = document.querySelectorAll('input[name="goalToggle"]');
  goalToggles.forEach(t => t.addEventListener('change', loadRecs));

  // kick off
  loadRecs();
})();

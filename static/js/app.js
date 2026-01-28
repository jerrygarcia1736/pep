// Peptide Tracker - UI helpers for dashboard + compare
// Free tier: recommendations are locked (no network calls; no red errors).

(function () {
  const qs = (sel) => document.querySelector(sel);

  function showPaidOnlyRecommendations() {
    const recoList = document.getElementById("recoList");
    const recoStatus = document.getElementById("recoStatus");
    const placeholder = document.getElementById("recoPlaceholder");
    const badge = document.getElementById("recoPaidBadge");

    if (badge) badge.classList.remove("d-none");
    if (placeholder) placeholder.classList.remove("d-none");
    if (recoList) recoList.classList.add("d-none");
    if (recoStatus) recoStatus.classList.add("d-none");
    if (recoStatus) recoStatus.textContent = "";
  }

  function initDashboardRecommendations() {
    const ageSlider = document.getElementById("ageSlider");
    const ageValue = document.getElementById("ageValue");
    const recoList = document.getElementById("recoList");
    const goalButtons = document.querySelectorAll(".goal-toggle");
    const isPaid = window.PEPTIDE_RECO_PAID === true; // future toggle

    if (!ageSlider || !ageValue) return; // not on dashboard

    // Always keep the age pill in sync
    const syncAge = () => { ageValue.textContent = String(ageSlider.value); };
    ageSlider.addEventListener("input", syncAge);
    syncAge();

    if (!isPaid) {
      // Free version: no API calls, no red errors.
      showPaidOnlyRecommendations();
      return;
    }

    // Paid version (optional): fetch recommendations from backend.
    const recoStatus = document.getElementById("recoStatus");
    const placeholder = document.getElementById("recoPlaceholder");
    const badge = document.getElementById("recoPaidBadge");

    if (badge) badge.classList.add("d-none");
    if (placeholder) placeholder.classList.add("d-none");
    if (recoList) recoList.classList.remove("d-none");
    if (recoStatus) recoStatus.classList.remove("d-none");

    let activeGoals = new Set();

    const setStatus = (txt) => { if (recoStatus) recoStatus.textContent = txt || ""; };

    async function loadRecommendations() {
      try {
        setStatus("Loading…");
        const age = Number(ageSlider.value || 35);
        const goals = Array.from(activeGoals).join(",");
        const url = `/api/recommendations?age=${encodeURIComponent(age)}&goals=${encodeURIComponent(goals)}`;
        const res = await fetch(url, { headers: { "Accept": "application/json" } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
          recoList.innerHTML = `<div class="list-group-item small text-muted">No recommendations returned.</div>`;
          setStatus("");
          return;
        }

        recoList.innerHTML = data.map((item) => {
          const title = (item.title || item.name || "Recommendation").toString();
          const detail = (item.detail || item.reason || "").toString();
          return `
            <div class="list-group-item">
              <div class="fw-semibold">${escapeHtml(title)}</div>
              ${detail ? `<div class="small text-muted mt-1">${escapeHtml(detail)}</div>` : ""}
            </div>`;
        }).join("");

        setStatus("");
      } catch (e) {
        // Never show red error. Fall back to paid-only placeholder.
        console.warn("Recommendations failed:", e);
        showPaidOnlyRecommendations();
      }
    }

    goalButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const goal = btn.getAttribute("data-goal");
        if (!goal) return;
        const isActive = btn.classList.toggle("active");
        if (isActive) activeGoals.add(goal);
        else activeGoals.delete(goal);
        loadRecommendations();
      });
    });

    ageSlider.addEventListener("change", loadRecommendations);
    loadRecommendations();
  }

  // Simple HTML escape for safe rendering
  function escapeHtml(str) {
    return str.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  document.addEventListener("DOMContentLoaded", () => {
    initDashboardRecommendations();
  });
})();

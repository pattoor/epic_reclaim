fetch('/health')
  .then(response => response.json())
  .then(health => {
    document.querySelector('#health').textContent =
      `Application ${health.status} · Database ${health.database} · Playwright ${health.playwright}`;
  })
  .catch(() => { document.querySelector('#health').textContent = 'Health check unavailable'; });

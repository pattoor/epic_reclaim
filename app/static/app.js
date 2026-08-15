const health = document.getElementById("health");
fetch("/health")
  .then((r) => r.json())
  .then((data) => {
    health.textContent = `status: ${data.status}, database: ${data.database}, playwright: ${data.playwright}`;
  })
  .catch(() => {
    health.textContent = "health check failed";
  });

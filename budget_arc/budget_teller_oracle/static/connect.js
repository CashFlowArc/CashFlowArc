(async function () {
  const status = document.getElementById("connect-status");
  const button = document.getElementById("connect");

  function show(payload) {
    status.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  }

  try {
    const configResponse = await fetch("./api/config", { cache: "no-store" });
    const config = await configResponse.json();
    if (!config.ok) {
      show(config);
      button.disabled = true;
      return;
    }

    show(`Ready. Environment: ${config.environment}; institution: ${config.institutionId || "picker"}`);
    const tellerConnect = TellerConnect.setup({
      applicationId: config.applicationId,
      environment: config.environment,
      products: config.products,
      selectAccount: "multiple",
      nonce: config.nonce,
      institution: config.institutionId || undefined,
      onSuccess: async function (enrollment) {
        show("Enrollment received. Verifying signature, encrypting token, and syncing Oracle...");
        const response = await fetch("./api/teller/enrollment", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": config.csrfToken
          },
          body: JSON.stringify({ nonce: config.nonce, enrollment })
        });
        const payload = await response.json();
        show(payload);
      },
      onExit: function () {
        show("Teller Connect closed before enrollment completed.");
      },
      onFailure: function (failure) {
        show(failure);
      }
    });

    button.addEventListener("click", function () {
      tellerConnect.open();
    });
  } catch (error) {
    show("Setup error: " + error.message);
    button.disabled = true;
  }
})();


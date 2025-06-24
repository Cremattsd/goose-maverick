document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("settings-form");

    // Load existing settings
    fetch("/settings-data", {
        headers: {
            "Authorization": "Bearer " + localStorage.getItem("token")
        }
    })
    .then(res => res.json())
    .then(data => {
        if (!data || data.error) return console.error("Failed to load settings", data);
        Object.entries(data).forEach(([key, value]) => {
            const input = form.querySelector(`[name="${key}"]`);
            if (input) input.value = value;
        });
    });

    // Save settings
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const settings = {};
        form.querySelectorAll("input[name]").forEach(input => {
            settings[input.name] = input.value;
        });

        fetch("/save-settings", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + localStorage.getItem("token")
            },
            body: JSON.stringify(settings)
        })
        .then(res => res.json())
        .then(data => {
            alert(data.status || data.error || "Unknown error");
        });
    });
});

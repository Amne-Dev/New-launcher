// Auto-update version from GitHub
fetch('https://api.github.com/repos/Amne-Dev/New-launcher/releases/latest')
    .then(response => response.json())
    .then(data => {
        if(data.tag_name) {
            // Remove 'v' prefix if present for cleaner display
            const ver = data.tag_name.replace(/^v/, '');
            document.getElementById('version-text').innerText = `Version ${ver} • Open Source • Free`;
        }
    })
    .catch(e => console.error("Could not fetch version", e));

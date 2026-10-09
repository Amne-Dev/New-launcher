// Auto-update version from GitHub
fetch('https://api.github.com/repos/Amne-Dev/New-launcher/releases/latest')
    .then(response => response.json())
    .then(data => {
        if(data.tag_name) {
            // Remove 'v' prefix if present for cleaner display
            const ver = data.tag_name.replace(/^v/, '');
            const versionEl = document.getElementById('version-text');
            if (versionEl) {
                versionEl.innerText = `Version ${ver} • Open Source • Free`;
            }
        }
    })
    .catch(e => console.error("Could not fetch version", e));

// Switch between Modpacks and Mods views in Modrinth showcase
function switchModrinthTab(tab) {
    const imgModpacks = document.getElementById('img-modpacks');
    const imgMods = document.getElementById('img-mods');
    const btnModpacks = document.getElementById('tab-btn-modpacks');
    const btnMods = document.getElementById('tab-btn-mods');

    if (!imgModpacks || !imgMods) return;

    if (tab === 'mods') {
        imgModpacks.style.display = 'none';
        imgMods.style.display = 'block';
        btnModpacks?.classList.remove('active');
        btnMods?.classList.add('active');
    } else {
        imgModpacks.style.display = 'block';
        imgMods.style.display = 'none';
        btnModpacks?.classList.add('active');
        btnMods?.classList.remove('active');
    }
}
